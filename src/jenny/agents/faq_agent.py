"""Agent FAQ — Recherche de connaissances par RAG.

Gère les questions générales, les demandes d'information,
les réclamations qui nécessitent de la documentation.

Utilise le système RAG pour retrouver les documents pertinents
et générer une réponse contextualisée.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.engine.state_manager import ConversationState
    from jenny.rag.retriever import VectorRetriever

logger = get_logger(__name__)

# score mini pour injecter (mesuré)
FAQ_MIN_SCORE = 0.35
# docs max dans le prompt
FAQ_MAX_DOCS = 3
# écart max avec le meilleur
FAQ_MAX_GAP_TO_BEST = 0.20


def select_documents(
    documents: list[dict],
    *,
    min_score: float = FAQ_MIN_SCORE,
    max_docs: int = FAQ_MAX_DOCS,
    max_gap: float = FAQ_MAX_GAP_TO_BEST,
) -> list[dict]:
    """Garde 2-3 docs vraiment utiles."""
    kept = [d for d in documents if (d.get("score") or 0.0) >= min_score]
    if not kept:
        return []
    best = max(d.get("score") or 0.0 for d in kept)
    kept = [d for d in kept if best - (d.get("score") or 0.0) <= max_gap]
    return kept[:max_docs]


def to_documents(hits) -> list[dict]:
    """Résultats retriever en dicts."""
    return [{"content": h.content, "score": h.score, "metadata": h.metadata} for h in hits or []]


async def grounding_documents(retriever, query: str, business_id) -> list[dict]:
    """Grounding transverse du moteur."""
    # même seuil que la FAQ
    hits = await retriever.search(
        query,
        business_id=business_id,
        top_k=FAQ_MAX_DOCS,
        score_threshold=FAQ_MIN_SCORE,
    )
    return select_documents(to_documents(hits))


class FAQAgent:
    """Agent de recherche documentaire (FAQ / RAG).

    Recherche dans la base de connaissances les documents
    pertinents pour répondre aux questions des clients.
    """

    name: str = "faq"

    def __init__(
        self,
        retriever: VectorRetriever | None = None,
        top_k: int = FAQ_MAX_DOCS,
        min_score: float = FAQ_MIN_SCORE,
    ) -> None:
        self.retriever = retriever
        self.top_k = top_k
        self.min_score = min_score

    async def handle(self, state: ConversationState) -> dict:
        """Cherche les docs utiles au dernier message."""
        # dernier message client
        user_messages = [m for m in state.message_history if m["role"] == "user"]
        if not user_messages:
            return {
                "response": "Comment puis-je vous aider ?",
                "documents": [],
                "action_result": None,
            }

        query = user_messages[-1]["content"]
        documents: list[dict] = []

        # recherche scopée au business
        if self.retriever is not None:
            try:
                results = await self.retriever.search(
                    query,
                    business_id=state.business_id,
                    top_k=self.top_k,
                    score_threshold=self.min_score,
                )
                found = to_documents(results)
                documents = select_documents(found, min_score=self.min_score, max_docs=self.top_k)
                logger.info(
                    "faq_agent.rag_search",
                    query_length=len(query),
                    results=len(documents),
                    dropped=len(found) - len(documents),
                    top_score=round(documents[0]["score"], 3) if documents else None,
                )
            except Exception as e:
                logger.error("faq_agent.rag_error", error=str(e))

        # réponse de base, neutre
        # le LLM la remplace
        if documents:
            response = "Bien sûr, je vous explique tout de suite."
        else:
            response = "Bien sûr, je m'occupe de ça pour vous."

        return {
            "response": response,
            "documents": documents,
            "action_result": None,
        }
