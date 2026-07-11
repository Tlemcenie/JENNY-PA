"""Ré-indexe la base de connaissances avec l'embedder COURANT.

À lancer après tout changement de modèle d'embeddings (ex. nomic → mpnet) :
les vecteurs stockés et les vecteurs de requête doivent vivre dans le même
espace, sinon les scores cosinus n'ont AUCUN sens (la recherche « marche »
sans erreur mais renvoie n'importe quoi — même dimension ≠ même espace).

Usage :
    python scripts/reindex_kb.py            # toutes les entreprises
    python scripts/reindex_kb.py <business_id>   # une seule

Idempotent : re-embedde le texte de chaque chunk en place (l'UUID, le contenu
et les métadonnées ne bougent pas).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text

from jenny.db.session import async_session_factory
from jenny.rag.embeddings import get_default_embedder
from jenny.rag.vector_store import _vector_literal

BATCH = 32


async def main(business_id: str | None = None) -> None:
    embedder = get_default_embedder()
    print(f"Embedder courant : {type(embedder).__name__} (dim {embedder.dimension})")

    async with async_session_factory() as session:
        where = "WHERE business_id = :bid" if business_id else ""
        params = {"bid": business_id} if business_id else {}
        rows = (
            await session.execute(
                text(f"SELECT id, content FROM document_embeddings {where} ORDER BY id"),
                params,
            )
        ).all()
        if not rows:
            print("Aucun chunk à ré-indexer.")
            return
        print(f"{len(rows)} chunks à ré-embedder…")

        done = 0
        for i in range(0, len(rows), BATCH):
            batch = rows[i : i + BATCH]
            vectors = await embedder.embed_batch([content for _, content in batch])
            for (chunk_id, _), vec in zip(batch, vectors, strict=True):
                await session.execute(
                    text("UPDATE document_embeddings SET embedding = :emb WHERE id = :id"),
                    {"emb": _vector_literal(vec), "id": chunk_id},
                )
            done += len(batch)
            print(f"  {done}/{len(rows)}")
        await session.commit()
    print("✅ Ré-indexation terminée. Vérifie les scores : ils doivent remonter nettement.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
