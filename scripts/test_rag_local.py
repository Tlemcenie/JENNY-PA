"""Test RAG bout-en-bout EN LOCAL : ingestion de fichiers → recherche → réponse groundée.

Donne 3 fichiers de connaissances à Jenny (mêmes embeddings Ollama + Postgres que
la vraie route /knowledge), puis :
  1) vérifie la recherche sémantique (les bons chunks remontent) ;
  2) interroge le MOTEUR avec des questions dont la réponse n'est QUE dans les fichiers,
     et montre que Jenny répond en se basant dessus.
"""

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

BID = UUID("acac65a8-96d7-4c75-9d42-e1f6b7db566d")  # Jenny Demo Boutique (local)
FILES = [
    ("Politiques & infos pratiques", "knowledge_samples/01_politiques_salon.md"),
    ("Produits & marques", "knowledge_samples/02_produits_marques.md"),
    ("Équipe & expertises", "knowledge_samples/03_equipe_expertise.md"),
]
# Questions dont la réponse est UNIQUEMENT dans les fichiers (pas dans le catalogue).
QUESTIONS = [
    "Bonjour, est-ce que vous avez un parking ?",
    "Quelles marques de produits utilisez-vous ?",
    "Je peux payer mon balayage en plusieurs fois ?",
    "C'est accessible en fauteuil roulant ?",
]


async def main() -> None:
    from jenny.db.session import async_session_factory
    from jenny.rag.knowledge_base import KnowledgeBase

    print("═" * 70)
    print("1) INGESTION — on donne les fichiers à Jenny")
    print("═" * 70)
    async with async_session_factory() as db:
        kb = KnowledgeBase(business_id=BID, session=db)
        for title, path in FILES:
            content = Path(path).read_text(encoding="utf-8")
            entry = await kb.add_text(content=content, title=title, category="salon")
            await db.commit()
            print(f"  ✓ « {title} » → {getattr(entry, 'chunks_count', '?')} chunks vectorisés")

    print("\n" + "═" * 70)
    print("2) RECHERCHE SÉMANTIQUE — est-ce que les bons passages remontent ?")
    print("═" * 70)
    async with async_session_factory() as db:
        kb = KnowledgeBase(business_id=BID, session=db)
        for q in QUESTIONS:
            hits = await kb.search(q, top_k=2)
            print(f"\n  ❓ {q}")
            for h in hits:
                score = h.get("score")
                txt = (h.get("content") or "")[:90].replace("\n", " ")
                print(f"     • score={score:.3f} | {txt}…")

    print("\n" + "═" * 70)
    print("3) RÉPONSE GROUNDÉE — Jenny répond-elle EN SE BASANT sur les fichiers ?")
    print("═" * 70)
    from jenny.engine.conversation_engine import EngineRequest
    from jenny.engine.factory import get_engine

    engine = get_engine()
    for q in QUESTIONS:
        out = await engine.process(
            EngineRequest(
                conversation_id=uuid4(),
                business_id=BID,
                message_text=q,
                channel="form",
            )
        )
        print(f"\n  ❓ {q}")
        print(f"  🤖 {out.response_text}")


if __name__ == "__main__":
    asyncio.run(main())
