"""Générateur de réponses avec LLM.

Combine le contexte conversationnel, les documents RAG retrouvés
et l'intention détectée pour produire une réponse naturelle
via un LLM (Groq, OpenAI, Mistral, Llama, ou NanoGPT local).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jenny.core.logging import get_logger
from jenny.llm.prompts import PromptBuilder

if TYPE_CHECKING:
    from jenny.engine.state_manager import ConversationState
    from jenny.llm.providers import BaseLLMProvider

logger = get_logger(__name__)

# Termes qui trahissent une identité non-humaine quand Jenny parle d'elle-même.
_AI_TERMS_RE = re.compile(
    r"intelligence artificielle|mod[èe]le de langage|mod[èe]le d['’]?ia|"  # noqa: RUF001
    r"assistant(?:e)? virtuel(?:le)?|chatbot|programme informatique|"
    r"\bIA\b|\bA\.?I\.?\b|\bbot\b|\brobot\b",
    re.IGNORECASE,
)
# Auto-référence : la phrase parle de Jenny elle-même.
_SELF_REF_RE = re.compile(
    r"\bje\b|\bj['’]|\bme\b|\bm['’]|\bmoi\b|\bmon\b|\bma\b|\bmes\b|\bsuis\b",  # noqa: RUF001
    re.IGNORECASE,
)
# Fuites « méta » : la phrase trahit le fonctionnement interne (RAG, base de
# connaissances) ou avoue ne pas savoir/avoir accès — interdites par la persona.
_META_LEAK_RE = re.compile(
    r"informations? fournies?|base de connaissances|d['’]apr[èe]s (?:les? )?(?:documents?|informations?)|"  # noqa: RUF001
    r"selon (?:les? )?(?:documents?|informations?)|je n['’]ai pas (?:cette |d['’])?(?:information|acc[èe]s)|"  # noqa: RUF001
    r"je ne dispose pas|je n['’]ai pas (?:l['’])?acc[èe]s|le(?:s)? document(?:s)? (?:ne )?(?:fourni|mentionne|conten)|"  # noqa: RUF001
    r"contexte fourni|je n['’]ai aucune information|"  # noqa: RUF001
    # Aveux d'ignorance directs : la persona « membre de l'équipe » ne dit jamais
    # « je ne sais pas » — elle propose de vérifier (le prompt gère la déflexion).
    r"je ne sais pas|j['’]ignore|je l['’]ignore|aucune id[ée]e|je n['’]en sais rien|"  # noqa: RUF001
    r"je ne peux pas (?:vous )?(?:dire|r[ée]pondre|aider)|je ne suis pas (?:s[ûu]re?|certaine?)|"
    # Non-réponse explicite (« je ne fournis pas d'informations sur… ») → à déflechir.
    # NB : on NE strippe PAS « en tant que » ici (la phrase contient souvent une info
    # utile, ex. un prix) — c'est traité côté prompt à la place.
    r"je\s+ne\s+fournis\s+pas\s+(?:d['’]|de\s+)?info",  # noqa: RUF001
    re.IGNORECASE,
)
_IDENTITY_FALLBACK = (
    "Je suis l'assistante de l'établissement, ravie de vous aider ! "
    "Que puis-je faire pour vous ?"
)


def sanitize_identity(text: str) -> str:
    """Garantit que Jenny ne se présente jamais comme une IA.

    Les petits modèles locaux gardent un réflexe « je suis une IA » que le
    prompt ne suffit pas toujours à mater. On retire donc, en sortie, les
    phrases à la fois AUTO-RÉFÉRENTIELLES et qui mentionnent une identité
    non-humaine (IA, robot, modèle de langage…). On ne touche pas aux phrases
    où ces mots sont employés dans un autre contexte (ex. « nos robots de
    massage »), faute d'auto-référence.
    """
    if not text or not (_AI_TERMS_RE.search(text) or _META_LEAK_RE.search(text)):
        return text  # chemin rapide : aucune mention suspecte (cas le plus fréquent)

    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    kept = [
        s
        for s in sentences
        if not (
            (_AI_TERMS_RE.search(s) and _SELF_REF_RE.search(s))  # « je suis une IA »
            or _META_LEAK_RE.search(s)  # fuite RAG / « je n'ai pas l'info »
        )
    ]
    cleaned = " ".join(kept).strip()
    if len(cleaned) < 15:
        return _IDENTITY_FALLBACK
    return cleaned


class ResponseGenerator:
    """Génère des réponses contextuelles via un LLM.

    Utilise le contexte de la conversation (intention, entités,
    documents RAG, historique) pour construire un prompt
    et générer une réponse adaptée.
    """

    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        prompt_builder: PromptBuilder | None = None,
        temperature: float | None = None,
    ) -> None:
        self.llm = llm_provider
        self.prompt_builder = prompt_builder or PromptBuilder()
        if temperature is None:
            from jenny.core.config import get_settings

            temperature = get_settings().llm_temperature
        self.temperature = temperature

    async def generate(self, state: ConversationState) -> str:
        """Génère une réponse à partir de l'état conversationnel.

        Args:
            state: État complet de la conversation.

        Returns:
            Texte de la réponse générée.
        """
        # Si on a des documents RAG, utiliser le mode RAG
        if state.retrieved_documents:
            return await self.generate_with_rag(state, state.retrieved_documents)

        # Construire le prompt système
        system_prompt = self.prompt_builder.build_system_prompt(state)

        # Construire le prompt utilisateur avec contexte
        user_prompt = self.prompt_builder.build_user_prompt(state)

        logger.info(
            "generator.generate",
            intent=state.current_intent,
            agent=state.agent_used,
            turn=state.turn_count,
            model=self.llm.model_name,
        )

        # Appeler le LLM (ton/créativité réglable via JENNY_LLM_TEMPERATURE)
        response = await self.llm.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=self.temperature,
            max_tokens=300,
        )

        # Si erreur, fallback template
        if response.finish_reason == "error":
            logger.warning("generator.llm_error_fallback", content=response.content)
            return self._template_fallback(state)

        return sanitize_identity(response.content)

    async def generate_with_rag(
        self,
        state: ConversationState,
        documents: list[dict],
    ) -> str:
        """Génère une réponse enrichie avec des documents RAG.

        Args:
            state: État de la conversation.
            documents: Documents pertinents retrouvés.

        Returns:
            Réponse contextualisée avec les documents.
        """
        state.retrieved_documents = documents

        system_prompt = self.prompt_builder.build_rag_system_prompt(state)
        user_prompt = self.prompt_builder.build_rag_user_prompt(state, documents)

        logger.info(
            "generator.generate_with_rag",
            num_documents=len(documents),
            model=self.llm.model_name,
        )

        # En mode RAG on reste plus factuel (température plafonnée).
        response = await self.llm.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=min(self.temperature, 0.5),
            max_tokens=300,
        )

        if response.finish_reason == "error":
            return self._template_fallback(state)

        return sanitize_identity(response.content)

    def _template_fallback(self, state: ConversationState) -> str:
        """Réponses templates quand le LLM est indisponible."""
        templates: dict[str, str] = {
            "greeting": "Bonjour ! 😊 Comment puis-je vous aider ?",
            "small_talk": "Ça va bien merci ! Comment puis-je vous être utile ?",
            "closing": "Merci et à bientôt ! 👋",
            "appointment": "Je vais vérifier les créneaux disponibles pour vous.",
            "pricing": "Je vais vous communiquer nos tarifs.",
            "payment": "Je vais vous aider avec votre paiement.",
            "payment_question": "Nous acceptons la carte bancaire, les espèces et les virements.",
            "quote": "Je prépare votre demande de devis.",
            "planning": "Je consulte les disponibilités.",
            "complaint": "Je suis désolé pour ce désagrément. Je prends note.",
            "escalation": "Je vous transfère vers un conseiller.",
        }
        return templates.get(
            state.current_intent or "general",
            "Merci pour votre message. Je traite votre demande.",
        )
