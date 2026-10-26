"""Ré-indexe la KB avec l'embedder courant.

Usage :
    python scripts/reindex_kb.py                       # toutes les entreprises
    python scripts/reindex_kb.py <business_id>         # une seule
    python scripts/reindex_kb.py --rechunk [<id>]      # redécoupe aussi
    python scripts/reindex_kb.py --rechunk --dry-run   # essai, rien écrit

Sûr avec l'app qui tourne : chaque entrée est relue sous verrou
(le même que les éditions de la KB) puis écrite et commitée seule.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text

from jenny.db.session import async_session_factory
from jenny.rag.embeddings import get_default_embedder
from jenny.rag.ingestion import build_embed_text, reassemble
from jenny.rag.knowledge_base import LAYOUT_KEYS as _LAYOUT_KEYS
from jenny.rag.knowledge_base import KnowledgeBase
from jenny.rag.vector_store import PgVectorStore, _vector_literal, lock_entry

BATCH = 32
# entrée modifiée : on réessaie
MAX_TRIES = 2

_COLS = "id, business_id, content, source, chunk_index, metadata_, created_at"


def _meta(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


@dataclass
class Report:
    """Bilan du redécoupage."""

    before: int = 0
    after: int = 0
    done: int = 0
    gone: list[str] = field(default_factory=list)
    busy: list[str] = field(default_factory=list)


async def _rows(session, business_id: str | None):
    where = "WHERE business_id = :bid" if business_id else ""
    params = {"bid": business_id} if business_id else {}
    return (
        await session.execute(
            text(
                f"SELECT {_COLS} FROM document_embeddings {where} ORDER BY business_id, chunk_index, id"
            ),
            params,
        )
    ).all()


async def entry_rows(session, business_id: str, knowledge_id: str):
    """Fragments actuels d'une entrée."""
    return (
        await session.execute(
            text(
                f"SELECT {_COLS} FROM document_embeddings "
                "WHERE business_id = :bid AND metadata_->>'knowledge_id' = :kid "
                "ORDER BY chunk_index, id"
            ),
            {"bid": business_id, "kid": knowledge_id},
        )
    ).all()


def fingerprint(rows) -> tuple:
    """Empreinte : ids + textes."""
    return tuple(sorted((str(r.id), r.content or "") for r in rows))


async def reembed(session, embedder, rows, *, dry_run: bool = False) -> int:
    """Re-vectorise en place, commit par lot."""
    done = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        texts = []
        for r in batch:
            meta = _meta(r.metadata_)
            texts.append(
                build_embed_text(r.content, meta.get("title", ""), meta.get("category", ""))
            )
        vectors = await embedder.embed_passages(texts)
        for r, vec in zip(batch, vectors, strict=True):
            # ligne effacée entre-temps : rien
            await session.execute(
                text(
                    "UPDATE document_embeddings SET embedding = CAST(:emb AS vector) WHERE id = :id"
                ),
                {"emb": _vector_literal(vec), "id": r.id},
            )
        await (session.rollback() if dry_run else session.commit())
        done += len(batch)
        print(f"  {done}/{len(rows)}")
    return done


async def _prepare(session, embedder, bid: str, kid: str, items) -> list[dict]:
    """Recolle puis redécoupe, sans écrire."""
    first = _meta(items[0].metadata_)
    full = reassemble(
        [(r.content, {**_meta(r.metadata_), "chunk_index": r.chunk_index}) for r in items]
    )
    kb = KnowledgeBase(business_id=bid, session=session, embedder=embedder)
    extra = {k: v for k, v in first.items() if k not in _LAYOUT_KEYS}
    chunks = await kb.prepare_chunks(
        full,
        knowledge_id=kid,
        title=first.get("title", ""),
        category=first.get("category", "general"),
        source=first.get("source") or items[0].source or "text",
        extra_metadata=extra,
    )
    created = min(r.created_at for r in items)
    for c in chunks:
        c["created_at"] = created
    return chunks


async def rechunk_entry(
    session, embedder, bid: str, kid: str, items, report: Report, *, dry_run: bool = False
) -> None:
    """Une entrée : vectorise, verrouille, vérifie, écrit."""
    store = PgVectorStore(embedding_dim=embedder.dimension)
    for _ in range(MAX_TRIES):
        # vectorise hors verrou
        chunks = await _prepare(session, embedder, bid, kid, items)
        # transaction neuve pour le verrou
        await session.rollback()
        await lock_entry(session, bid, kid)
        fresh = await entry_rows(session, bid, kid)
        if not fresh:
            # supprimée pendant le run
            await session.rollback()
            report.gone.append(kid)
            return
        if fingerprint(fresh) != fingerprint(items):
            # éditée pendant le run
            await session.rollback()
            items = fresh
            continue
        deleted = (
            await session.execute(
                text("DELETE FROM document_embeddings WHERE id = ANY(:ids)"),
                {"ids": [r.id for r in fresh]},
            )
        ).rowcount
        if deleted != len(fresh):
            await session.rollback()
            report.busy.append(kid)
            return
        await store.add_chunks(session, bid, chunks)
        await (session.rollback() if dry_run else session.commit())
        report.before += len(fresh)
        report.after += len(chunks)
        report.done += 1
        return
    report.busy.append(kid)


async def rechunk(session, embedder, rows, *, dry_run: bool = False) -> Report:
    """Recolle puis redécoupe chaque entrée."""
    groups: dict[tuple[str, str], list] = {}
    loose = []
    for r in rows:
        kid = _meta(r.metadata_).get("knowledge_id")
        if kid:
            groups.setdefault((str(r.business_id), kid), []).append(r)
        else:
            loose.append(r)
    report = Report()
    for (bid, kid), items in groups.items():
        await rechunk_entry(session, embedder, bid, kid, items, report, dry_run=dry_run)
    if loose:
        # sans knowledge_id : en place
        await reembed(session, embedder, loose, dry_run=dry_run)
        report.before += len(loose)
        report.after += len(loose)
    return report


async def main(business_id: str | None, do_rechunk: bool, dry_run: bool = False) -> None:
    embedder = get_default_embedder()
    await embedder.prepare()
    print(f"Embedder courant : {type(embedder).__name__} (dim {embedder.dimension})")

    async with async_session_factory() as session:
        rows = await _rows(session, business_id)
        await session.rollback()
        if not rows:
            print("Aucun chunk à ré-indexer.")
            return
        if do_rechunk:
            rep = await rechunk(session, embedder, rows, dry_run=dry_run)
            print(
                f"Redécoupage : {rep.before} fragments -> {rep.after} fragments "
                f"({rep.done} entrées)."
            )
            if rep.gone:
                print(f"Supprimées pendant le run (ignorées) : {len(rep.gone)}")
            if rep.busy:
                print(f"Modifiées pendant le run (à relancer) : {', '.join(rep.busy)}")
        else:
            print(f"{len(rows)} chunks à ré-embedder…")
            await reembed(session, embedder, rows, dry_run=dry_run)
    print("Essai terminé, rien écrit." if dry_run else "Ré-indexation terminée.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ré-indexe la KB")
    parser.add_argument("business_id", nargs="?", default=None)
    parser.add_argument("--rechunk", action="store_true", help="recolle et redécoupe")
    parser.add_argument("--dry-run", action="store_true", help="annule chaque écriture")
    args = parser.parse_args()
    asyncio.run(main(args.business_id, args.rechunk, args.dry_run))
