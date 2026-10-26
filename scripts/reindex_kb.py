"""Ré-indexe la KB avec l'embedder courant.

Usage :
    python scripts/reindex_kb.py                       # toutes les entreprises
    python scripts/reindex_kb.py <business_id>         # une seule
    python scripts/reindex_kb.py --rechunk [<id>]      # redécoupe aussi
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text

from jenny.db.session import async_session_factory
from jenny.rag.embeddings import get_default_embedder
from jenny.rag.ingestion import build_embed_text, reassemble
from jenny.rag.knowledge_base import LAYOUT_KEYS as _LAYOUT_KEYS
from jenny.rag.knowledge_base import KnowledgeBase
from jenny.rag.vector_store import _vector_literal

BATCH = 32


def _meta(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


async def _rows(session, business_id: str | None):
    where = "WHERE business_id = :bid" if business_id else ""
    params = {"bid": business_id} if business_id else {}
    return (
        await session.execute(
            text(
                "SELECT id, business_id, content, source, chunk_index, metadata_, created_at "
                f"FROM document_embeddings {where} ORDER BY business_id, chunk_index, id"
            ),
            params,
        )
    ).all()


async def reembed(session, embedder, rows) -> int:
    """Re-vectorise en place."""
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
            await session.execute(
                text(
                    "UPDATE document_embeddings SET embedding = CAST(:emb AS vector) WHERE id = :id"
                ),
                {"emb": _vector_literal(vec), "id": r.id},
            )
        done += len(batch)
        print(f"  {done}/{len(rows)}")
    return done


async def rechunk(session, embedder, rows) -> tuple[int, int]:
    """Recolle puis redécoupe chaque entrée."""
    groups: dict[tuple[str, str], list] = {}
    loose = []
    for r in rows:
        kid = _meta(r.metadata_).get("knowledge_id")
        if kid:
            groups.setdefault((str(r.business_id), kid), []).append(r)
        else:
            loose.append(r)
    before = after = 0
    for (bid, kid), items in groups.items():
        first = _meta(items[0].metadata_)
        full = reassemble([(r.content, _meta(r.metadata_)) for r in items])
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
        await session.execute(
            text("DELETE FROM document_embeddings WHERE id = ANY(:ids)"),
            {"ids": [r.id for r in items]},
        )
        await kb.vector_store.add_chunks(session, bid, chunks)
        before += len(items)
        after += len(chunks)
    if loose:
        # sans knowledge_id : en place
        await reembed(session, embedder, loose)
    return before + len(loose), after + len(loose)


async def main(business_id: str | None, do_rechunk: bool) -> None:
    embedder = get_default_embedder()
    await embedder.prepare()
    print(f"Embedder courant : {type(embedder).__name__} (dim {embedder.dimension})")

    async with async_session_factory() as session:
        rows = await _rows(session, business_id)
        if not rows:
            print("Aucun chunk à ré-indexer.")
            return
        if do_rechunk:
            before, after = await rechunk(session, embedder, rows)
            print(f"Redécoupage : {before} fragments -> {after} fragments.")
        else:
            print(f"{len(rows)} chunks à ré-embedder…")
            await reembed(session, embedder, rows)
        await session.commit()
    print("Ré-indexation terminée.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ré-indexe la KB")
    parser.add_argument("business_id", nargs="?", default=None)
    parser.add_argument("--rechunk", action="store_true", help="recolle et redécoupe")
    args = parser.parse_args()
    asyncio.run(main(args.business_id, args.rechunk))
