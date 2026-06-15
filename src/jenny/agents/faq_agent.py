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


class FAQAgent:
    """Agent de recherche documentaire (FAQ / RAG).

    Recherche dans la base de connaissances les documents
    pertinents pour répondre aux questions des clients.
    """

    name: str = "faq"

    def __init__(
        self,
        retriever: VectorRetriever | None = None,
        top_k: int = 3,
    ) -> None:
        self.retriever = retriever
        self.top_k = top_k

    async def handle(self, state: ConversationState) -> dict:
        """Traite une demande FAQ via RAG.

        1. Prend le dernier message utilisateur
        2. Recherche les documents similaires via pgvector
        3. Retourne les documents trouvés pour le générateur de réponse

        Args:
            state: État de la conversation.

        Returns:
            Documents pertinents et réponse de base.
        """
        # Récupérer le dernier message utilisateur
        user_messages = [m for m in state.message_history if m["role"] == "user"]
        if not user_messages:
            return {
                "response": "Comment puis-je vous aider ?",
                "documents": [],
                "action_result": None,
            }

        query = user_messages[-1]["content"]
        documents: list[dict] = []

        # Recherche RAG si le retriever est disponible (scopée au business)
        if self.retriever is not None:
            try:
                results = await self.retriever.search(
                    query, business_id=state.business_id, top_k=self.top_k
                )
                documents = [
                    {
                        "content": r.content,
                        "score": r.score,
                        "metadata": r.metadata,
                    }
                    for r in results
                ]
                logger.info(
                    "faq_agent.rag_search",
                    query_length=len(query),
                    results=len(documents),
                )
            except Exception as e:
                logger.error("faq_agent.rag_error", error=str(e))

        # Réponse "de base" : le générateur LLM la remplace presque toujours.
        # On la garde neutre et humaine, sans révéler le mécanisme interne ni
        # signaler une absence d'information (le client ne doit jamais le voir).
        if documents:
            response = "Bien sûr, je vous explique tout de suite."
        else:
            response = "Bien sûr, je m'occupe de ça pour vous."

        return {
            "response": response,
            "documents": documents,
            "action_result": None,
        }
