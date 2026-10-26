"""KB coiffeur : salon démo, ou vrai salon (faits réels seuls).

Usage :
    python scripts/seed_kb_coiffeur.py                 # salon démo (slug demo)
    python scripts/seed_kb_coiffeur.py --dry-run       # affiche sans écrire
    python scripts/seed_kb_coiffeur.py --slug mon-salon --salon-reel
    python scripts/seed_kb_coiffeur.py --slug mon-salon --restore var/kb_backups/x.json

Salon démo : toute la KB est remplacée par les fiches démo (dont des faits
inventés : adresse, équipe...). Vrai salon (--salon-reel obligatoire) :
seules les fiches tirées de sa base (horaires, prestations, acompte,
rappels, équipe) ou ce que Jenny fait vraiment ; les fiches du gérant
restent. Dans les deux cas la KB est d'abord exportée en JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jenny.rag.kb_coiffeur import (  # noqa: E402
    DEMO_SLUG,
    LEGACY_HOURS_TEXT,
    REAL_TAG,
    SEED_TAG,
    UNCOVERED_TOPICS,
    build_entries,
    describe_hours,
    fmt_duration,
    fmt_hour,
    fmt_price,
    load_salon,
    slugify,
)

__all__ = [
    "build_entries",
    "describe_hours",
    "fmt_duration",
    "fmt_hour",
    "fmt_price",
    "slugify",
]

# sauvegardes hors git (var/)
BACKUP_DIR = ROOT / "var" / "kb_backups"


def check_target(slug: str, *, salon_reel: bool, force: bool, dry_run: bool) -> None:
    """Refuse un vrai salon sans accord."""
    if slug == DEMO_SLUG:
        if salon_reel:
            raise SystemExit("--salon-reel est pour un vrai salon, pas la démo.")
        return
    if force and not salon_reel:
        raise SystemExit(
            "--force ne suffit plus : pour un vrai salon, utilise --salon-reel "
            "(faits tirés de sa base seulement, ses fiches gardées)."
        )
    if not (salon_reel or dry_run):
        raise SystemExit(
            f"« {slug} » n'est pas la démo : ajoute --salon-reel (faits réels seulement)."
        )


async def export_kb(session, business: dict, backup_dir: Path = BACKUP_DIR) -> Path:
    """Exporte la KB en JSON, avant tout."""
    from sqlalchemy import text

    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, content, source, chunk_index, metadata_, created_at "
                    "FROM document_embeddings WHERE business_id = :bid "
                    "ORDER BY chunk_index, id"
                ),
                {"bid": str(business["id"])},
            )
        )
        .mappings()
        .all()
    )
    out = []
    for r in rows:
        meta = r["metadata_"]
        if isinstance(meta, str):
            meta = json.loads(meta or "{}")
        out.append(
            {
                "id": str(r["id"]),
                "content": r["content"],
                "source": r["source"],
                "chunk_index": r["chunk_index"],
                "metadata": meta or {},
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
        )
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = backup_dir / f"{business.get('slug') or business['id']}-{stamp}-{uuid4().hex[:6]}.json"
    payload = {
        "business_id": str(business["id"]),
        "slug": business.get("slug"),
        "exported_at": datetime.now(UTC).isoformat(),
        "rows": out,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


async def _chunks_for(kb, entries: list[dict], tag: str) -> list[dict]:
    chunks: list[dict] = []
    for e in entries:
        chunks += await kb.prepare_chunks(
            e["content"],
            knowledge_id=str(uuid4()),
            title=e["title"],
            category=e["category"],
            source="text",
            extra_metadata={"kb_key": e["key"], "seed": tag},
        )
    return chunks


async def _owner_titles(session, bid: str, tags: tuple[str, ...]) -> set[str]:
    """Titres des fiches du gérant."""
    from sqlalchemy import text

    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT metadata_->>'title' AS title, metadata_->>'seed' AS seed, "
                "content FROM document_embeddings WHERE business_id = :bid"
            ),
            {"bid": bid},
        )
    ).all()
    # vieille fiche horaires : à nous
    return {
        slugify(r.title or "")
        for r in rows
        if r.seed not in tags and (r.content or "").strip() != LEGACY_HOURS_TEXT
    }


async def seed(
    session,
    slug: str,
    *,
    salon_reel: bool = False,
    dry_run: bool = False,
    backup_dir: Path = BACKUP_DIR,
    commit: bool = True,
) -> dict:
    """Seed de la KB d'un salon."""
    from sqlalchemy import text

    from jenny.rag.knowledge_base import KnowledgeBase
    from jenny.rag.vector_store import lock_business_kb

    bid = (
        await session.execute(text("SELECT id FROM businesses WHERE slug = :s"), {"s": slug})
    ).scalar()
    if bid is None:
        raise SystemExit(f"Business introuvable : {slug}")
    business, prestas, staff = await load_salon(session, bid)
    demo = slug == DEMO_SLUG
    entries = build_entries(business, prestas, demo=demo, staff=staff)
    report = {"business": business["name"], "entries": entries, "demo": demo}
    if dry_run:
        return report

    kb = KnowledgeBase(business_id=bid, session=session)
    tag = SEED_TAG if demo else REAL_TAG
    # vectorise avant de verrouiller
    if not demo:
        owner = await _owner_titles(session, str(bid), (SEED_TAG, REAL_TAG))
        skipped = [e for e in entries if slugify(e["title"]) in owner]
        entries = [e for e in entries if slugify(e["title"]) not in owner]
        report["kept_owner"] = [e["key"] for e in skipped]
    chunks = await _chunks_for(kb, entries, tag)
    await session.rollback()

    # personne n'écrit pendant ce temps
    await lock_business_kb(session, bid)
    report["backup"] = str(await export_kb(session, business, backup_dir))
    if demo:
        # démo : tout remplacé
        where, params = "business_id = :bid", {"bid": str(bid)}
    else:
        # vrai salon : nos fiches seules
        where = (
            "business_id = :bid AND (metadata_->>'seed' IN (:a, :b) OR btrim(content) = :legacy)"
        )
        params = {"bid": str(bid), "a": SEED_TAG, "b": REAL_TAG, "legacy": LEGACY_HOURS_TEXT}
    deleted = (
        await session.execute(text(f"DELETE FROM document_embeddings WHERE {where}"), params)
    ).rowcount
    inserted = await kb.vector_store.add_chunks(session, bid, chunks)
    if commit:
        await session.commit()
    report.update(deleted=deleted, inserted=inserted)
    return report


async def restore(
    session, slug: str, path: Path, *, backup_dir: Path = BACKUP_DIR, commit: bool = True
) -> dict:
    """Remet une sauvegarde JSON (re-vectorisée)."""
    from sqlalchemy import text

    from jenny.rag.ingestion import build_embed_text, reassemble
    from jenny.rag.knowledge_base import LAYOUT_KEYS, KnowledgeBase
    from jenny.rag.vector_store import lock_business_kb

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    bid = (
        await session.execute(text("SELECT id FROM businesses WHERE slug = :s"), {"s": slug})
    ).scalar()
    if bid is None or str(bid) != data.get("business_id"):
        raise SystemExit("Sauvegarde d'un autre salon : refusé.")
    business, _prestas, _staff = await load_salon(session, bid)
    kb = KnowledgeBase(business_id=bid, session=session)
    groups: dict[str, list[dict]] = {}
    loose: list[dict] = []
    for r in data.get("rows") or []:
        kid = (r.get("metadata") or {}).get("knowledge_id")
        (groups.setdefault(kid, []) if kid else loose).append(r)
    chunks: list[dict] = []
    for kid, rows in groups.items():
        first = rows[0]["metadata"]
        full = reassemble(
            [(r["content"], {**r["metadata"], "chunk_index": r["chunk_index"]}) for r in rows]
        )
        chunks += await kb.prepare_chunks(
            full,
            knowledge_id=kid,
            title=first.get("title", ""),
            category=first.get("category", "general"),
            source=first.get("source") or rows[0].get("source") or "text",
            extra_metadata={k: v for k, v in first.items() if k not in LAYOUT_KEYS},
        )
    if loose:
        texts = [
            build_embed_text(
                r["content"], r["metadata"].get("title", ""), r["metadata"].get("category", "")
            )
            for r in loose
        ]
        vectors = await kb.embedder.embed_passages(texts)
        for r, vec in zip(loose, vectors, strict=True):
            chunks.append(
                {
                    "content": r["content"],
                    "embedding": vec,
                    "source": r.get("source"),
                    "chunk_index": r.get("chunk_index"),
                    "metadata": r["metadata"],
                }
            )
    await session.rollback()
    await lock_business_kb(session, bid)
    # l'état actuel aussi, au cas où
    before = await export_kb(session, business, backup_dir)
    deleted = (
        await session.execute(
            text("DELETE FROM document_embeddings WHERE business_id = :bid"), {"bid": str(bid)}
        )
    ).rowcount
    inserted = await kb.vector_store.add_chunks(session, bid, chunks)
    if commit:
        await session.commit()
    return {"backup": str(before), "deleted": deleted, "inserted": inserted, "entries": len(groups)}


async def main(args) -> None:
    from jenny.db.session import async_session_factory

    async with async_session_factory() as session:
        if args.restore:
            rep = await restore(
                session, args.slug, Path(args.restore), backup_dir=Path(args.backup_dir)
            )
            print(f"Sauvegarde de l'état actuel : {rep['backup']}")
            print(f"Restauré : {rep['entries']} entrées ({rep['inserted']} fragments).")
            return
        rep = await seed(
            session,
            args.slug,
            salon_reel=args.salon_reel,
            dry_run=args.dry_run,
            backup_dir=Path(args.backup_dir),
        )
    entries = rep["entries"]
    mode = "démo (faits inventés)" if rep["demo"] else "salon réel (faits de la base)"
    print(f"{rep['business']} : {len(entries)} entrées, mode {mode}")
    if rep["demo"]:
        print("Sujets non couverts exprès :", ", ".join(UNCOVERED_TOPICS))
    if args.dry_run:
        for e in entries:
            print(f"- [{e['key']}] {e['title']} :: {e['content'][:90]}")
        return
    if rep.get("kept_owner"):
        print("Fiches du gérant gardées :", ", ".join(rep["kept_owner"]))
    print(f"Sauvegarde : {rep['backup']}")
    print(f"Supprimés : {rep['deleted']} fragments ; insérés : {rep['inserted']} fragments.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed KB coiffeur")
    parser.add_argument("--slug", default=DEMO_SLUG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--salon-reel", action="store_true", help="vrai salon : faits réels seuls")
    parser.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--restore", metavar="FICHIER", help="remet une sauvegarde JSON")
    parser.add_argument("--backup-dir", default=str(BACKUP_DIR), help="dossier des sauvegardes")
    args = parser.parse_args()
    if not args.restore:
        check_target(args.slug, salon_reel=args.salon_reel, force=args.force, dry_run=args.dry_run)
    asyncio.run(main(args))
