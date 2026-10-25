"""Génère les réponses via LLM."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jenny.core.logging import get_logger
from jenny.llm.prompts import PromptBuilder

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from jenny.engine.state_manager import ConversationState
    from jenny.llm.providers import BaseLLMProvider

    TokenCallback = Callable[[str], Awaitable[None]]

logger = get_logger(__name__)

# tournures mécaniques : on les lisse, mais dire « assistante virtuelle »
# est OBLIGATOIRE (AI Act art. 50) donc ce terme n'est plus filtré.
_AI_TERMS_RE = re.compile(
    r"mod[èe]le de langage|mod[èe]le d['’]?ia|chatbot|programme informatique|"  # noqa: RUF001
    r"en tant qu['’]\s*(?:ia|intelligence artificielle)",  # noqa: RUF001
    re.IGNORECASE,
)
# la divulgation autorisée : une phrase qui la contient n'est jamais coupée
_DISCLOSURE_RE = re.compile(r"assistant(?:e)?\s+virtuel(?:le)?", re.IGNORECASE)
# auto-référence
_SELF_REF_RE = re.compile(
    r"\bje\b|\bj['’]|\bme\b|\bm['’]|\bmoi\b|\bmon\b|\bma\b|\bmes\b|\bsuis\b",  # noqa: RUF001
    re.IGNORECASE,
)
# sonde d'identité recopiée
_IDENTITY_PROBE_RE = re.compile(
    r"\b(t['’]es|tu\s+es|es[\s-]?tu|vous\s+[êe]tes|[êe]tes[\s-]?vous|"  # noqa: RUF001
    r"une\s+(?:vraie\s+)?personne|un\s+programme|une\s+machine|un\s+vrai\s+humain)\b",
    re.IGNORECASE,
)
# fuites méta interdites
_META_LEAK_RE = re.compile(
    r"informations? fournies?|base de connaissances|d['’]apr[èe]s (?:les? )?(?:documents?|informations?)|"  # noqa: RUF001
    r"selon (?:les? )?(?:documents?|informations?)|je n['’]ai pas (?:cette |d['’])?(?:information|acc[èe]s)|"  # noqa: RUF001
    r"je ne dispose pas|je n['’]ai pas (?:l['’])?acc[èe]s|le(?:s)? document(?:s)? (?:ne )?(?:fourni|mentionne|conten)|"  # noqa: RUF001
    r"contexte fourni|je n['’]ai aucune information|"  # noqa: RUF001
    # non-réponse explicite
    r"je\s+ne\s+fournis\s+pas\s+(?:d['’]|de\s+)?info",  # noqa: RUF001
    re.IGNORECASE,
)
# Aveux d'ignorance : à couper SEULEMENT quand c'est une non-réponse sèche.
# « Je ne sais pas si vous préférez le matin ou l'après-midi ? » est une vraie
# question de clarification — avant, elle était supprimée.
_IGNORANCE_RE = re.compile(
    r"je ne sais pas|j['’]ignore|je l['’]ignore|aucune id[ée]e|je n['’]en sais rien|"  # noqa: RUF001
    r"je ne peux pas (?:vous )?(?:dire|r[ée]pondre|aider)|je ne suis pas (?:s[ûu]re?|certaine?)",
    re.IGNORECASE,
)
# marques d'une phrase utile malgré l'aveu : on demande vraiment au client.
# (« ou » seul ne suffit pas : « je suis une IA ou un humain » est une esquive)
_UTILE_RE = re.compile(r"\?|dites[- ]moi|pr[ée]f[ée]rez|souhaitez|voulez", re.IGNORECASE)
_IDENTITY_FALLBACK = (
    "Je suis Jenny, l'assistante virtuelle du salon 🙂 Que puis-je faire pour vous ?"
)


def _a_couper(phrase: str) -> bool:
    """Phrase à retirer ? (mécanique ou fuite interne)"""
    # la divulgation légale passe toujours
    if _DISCLOSURE_RE.search(phrase):
        return False
    if _META_LEAK_RE.search(phrase):
        return True
    # tournure mécanique sur soi (« en tant qu'IA… »)
    if _AI_TERMS_RE.search(phrase) and (
        _SELF_REF_RE.search(phrase) or _IDENTITY_PROBE_RE.search(phrase)
    ):
        return True
    # aveu d'ignorance SEC : on garde s'il amène une question ou un choix
    return bool(_IGNORANCE_RE.search(phrase) and not _UTILE_RE.search(phrase))


def sanitize_identity(text: str) -> str:
    """Retire la mécanique interne, garde la divulgation."""
    if not text:
        return text
    if not (
        _AI_TERMS_RE.search(text) or _META_LEAK_RE.search(text) or _IGNORANCE_RE.search(text)
    ):
        return text  # chemin rapide

    phrases = re.split(r"(?<=[.!?…])\s+", text.strip())
    gardees = [ph for ph in phrases if not _a_couper(ph)]
    propre = " ".join(gardees).strip()
    if len(propre) < 15:
        return _IDENTITY_FALLBACK
    return propre


def ensure_ai_disclosure(text: str, *, already_spoke: bool) -> str:
    """Garantit la divulgation IA au 1er message (AI Act art. 50).

    Le prompt la demande déjà, mais on ne peut pas dépendre du bon vouloir du
    modèle pour une obligation légale : ici c'est déterministe.
    """
    if already_spoke or not text or _DISCLOSURE_RE.search(text):
        return text
    intro = "Je suis Jenny, l'assistante virtuelle du salon."
    # on se glisse après la salutation si elle existe, sinon en tête
    m = _OPENING_GREETING_RE.match(text)
    if m:
        salut = text[: m.end()].rstrip(" ,!.")
        reste = text[m.end() :].lstrip(" ,!.")
        return f"{salut} ! {intro} {reste}".strip()
    return f"{intro} {text}".strip()


# salutation d'ouverture
_OPENING_GREETING_RE = re.compile(
    r"^\s*(?:bonjour|bonsoir|coucou|salut|hello|hey|re[\s-]?bonjour)\b"
    r"[^.!?\n]*[.!?\n]?\s*",
    re.IGNORECASE,
)
# bouts de consignes fuités
_LEAKED_INSTRUCTION_RE = re.compile(
    r"à dire au client|ne recopie|reformule|avec tes mots|ne les change|"
    r"reprends? exactement|en gardant exactement|ne propose aucun|"
    r"=== |faits pour ta réponse|consigne|sans insister",
    re.IGNORECASE,
)


# format courrier à virer
_LETTER_OPENING_RE = re.compile(
    r"^\s*(?:ch[èe]re?s?\s+client(?:e|es|s)?|cher\s+client|"
    r"(?:bonjour\s+)?(?:madame|monsieur|mademoiselle))\s*,?\s*\n+",
    re.IGNORECASE,
)
_LETTER_SIGNATURE_RE = re.compile(
    r"\n+\s*(?:(?:bien\s+)?cordialement|sinc[èe]rement|bien\s+à\s+vous|"
    r"chaleureusement)\s*,?\s*(?:\n+\s*jenny\b[^\n]*)?\s*$",
    re.IGNORECASE,
)
_LETTER_NAME_RE = re.compile(r"\n+\s*jenny\s*[!.]*\s*$", re.IGNORECASE)


def strip_letter_format(text: str) -> str:
    """Vire appel et signature."""
    out = _LETTER_OPENING_RE.sub("", text, count=1)
    out = _LETTER_SIGNATURE_RE.sub("", out, count=1)
    out = _LETTER_NAME_RE.sub("", out, count=1)
    out = out.strip()
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    return out if len(out) >= 10 else text


def strip_repeated_greeting(text: str) -> str:
    """Vire une resalutation."""
    stripped = _OPENING_GREETING_RE.sub("", text, count=1).strip()
    if len(stripped) >= 15:
        # remet la majuscule
        return stripped[0].upper() + stripped[1:]
    return text


def drop_leaked_instructions(text: str) -> str:
    """Vire les consignes recopiées."""
    if not _LEAKED_INSTRUCTION_RE.search(text):
        return text
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    kept = [s for s in sentences if not _LEAKED_INSTRUCTION_RE.search(s)]
    cleaned = " ".join(kept).strip()
    return cleaned if len(cleaned) >= 15 else text


def strip_model_artifacts(text: str) -> str:
    """Vire les artefacts du modèle."""
    if not text:
        return text
    # 1) coupe au jeton
    m = re.search(r"<\|[^>]*\|>|<\|?(?:im_start|im_end|endoftext|assistant|user|system)\b", text)
    if m:
        text = text[: m.start()]
    # 2) vire le CJK
    text = re.sub(r"[　-〿㐀-鿿＀-￯가-힯]+", "", text)
    return text.strip()


# formules de clôture creuses
_FILLER_CLOSING_RE = re.compile(
    r"n['’]h[ée]sitez\s+pas\b"  # noqa: RUF001
    r"|je\s+(?:reste|suis|me\s+tiens)\s+(?:à\s+votre\s+disposition|(?:là|ici)\s+pour\s+"
    r"(?:vous\s+aider|r[ée]pondre|toute\s+question))"
    r"|nous\s+restons\s+à\s+votre\s+disposition"
    r"|au\s+plaisir\s+de\s+vous\s+(?:aider|lire|revoir)",
    re.IGNORECASE,
)


def trim_filler_closing(text: str) -> str:
    """Vire la clôture creuse finale."""
    if not text:
        return text
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    if len(sentences) < 2:
        return text
    last = sentences[-1].strip()
    # garde une vraie question
    if last.endswith("?") and not _FILLER_CLOSING_RE.search(last):
        return text
    if _FILLER_CLOSING_RE.search(last):
        trimmed = " ".join(sentences[:-1]).strip()
        if len(trimmed) >= 12:
            return trimmed
    return text


def cut_to_last_sentence(text: str) -> str:
    """Tronque à la dernière phrase."""
    t = (text or "").strip()
    if not t or t[-1] in ".!?…\"»)":
        return t
    # dernière ponctuation
    m = list(re.finditer(r"[.!?…]", t))
    if not m:
        return t  # aucune phrase complète
    cut = t[: m[-1].end()].strip()
    return cut if len(cut) >= 12 else t


# appel courrier en milieu
_INLINE_ADDRESS_RE = re.compile(
    r"\b(?:ch[èe]re?s?\s+client(?:e|es|s)?|cher\s+client|"
    r"madame(?:\s+ou\s+monsieur)?|monsieur(?:\s+ou\s+madame)?|mademoiselle)\b[\s,]*",
    re.IGNORECASE,
)


def strip_inline_address(text: str) -> str:
    """Vire les Madame/Monsieur."""
    out = _INLINE_ADDRESS_RE.sub("", text)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,")
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    return out if len(out) >= 10 else text


def trim_trailing_deflection(text: str, *, grounded: bool) -> str:
    """Vire la déflexion en trop."""
    if not grounded or not text:
        return text
    from jenny.engine.intelligence import looks_like_deflection

    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    if len(sentences) < 2:
        return text
    # On retire la/les dernière(s) phrase(s) qui sont des déflexions, tant qu'il
    # reste du contenu substantiel devant.
    while len(sentences) >= 2 and looks_like_deflection(sentences[-1]):
        candidate = " ".join(sentences[:-1]).strip()
        if len(candidate) < 20:
            break
        sentences = sentences[:-1]
    return " ".join(sentences).strip()


def cap_paragraphs(text: str, *, max_paragraphs: int = 2) -> str:
    """Limite le nombre de blocs."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    if len(blocks) <= max_paragraphs:
        return text
    kept = blocks[:max_paragraphs]
    # récupère la question finale
    tail_question = next(
        (b for b in reversed(blocks[max_paragraphs:]) if b.rstrip().endswith("?")),
        None,
    )
    if tail_question and not kept[-1].rstrip().endswith("?"):
        # garde juste la question
        q = re.split(r"(?<=[.!?…])\s+", tail_question)[-1].strip()
        kept.append(q)
    return "\n\n".join(kept)


# gabarit de dialogue fuité
_ROLE_PREFIX_RE = re.compile(r"^\s*(?:client|utilisateur|user|assistant)\s*:\s*", re.I)
_JENNY_LABEL_RE = re.compile(r"\bjenny\s*:\s*", re.I)


def strip_dialogue_scaffold(text: str) -> str:
    """Vire l'échafaudage de dialogue."""
    labels = list(_JENNY_LABEL_RE.finditer(text))
    if labels:
        text = text[labels[-1].end() :]
    lines = [_ROLE_PREFIX_RE.sub("", ln) for ln in text.splitlines()]
    lines = [ln for ln in lines if not re.match(r"^\s*(?:client|utilisateur|user)\s*:", ln, re.I)]
    cleaned = "\n".join(lines).strip()
    return cleaned if cleaned else text


# clause « n'hésitez pas »
_FILLER_PHRASE_RE = re.compile(r"\s*\bn['’]?h[ée]sitez\s+pas\b[^.!?]*[.!?]?", re.I)  # noqa: RUF001


# la clause porte-t-elle une vraie info ? (horaire, jour, choix, question)
_CLAUSE_UTILE_RE = re.compile(
    r"\d{1,2}\s*h|\d{1,2}/\d{1,2}|\?|\bou\b|"
    r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|demain|aujourd)",
    re.I,
)


def strip_filler_phrases(text: str) -> str:
    """Vire les « n'hésitez pas » vides de sens."""
    if not _FILLER_PHRASE_RE.search(text):
        return text

    def _remplace(m: re.Match) -> str:
        # « n'hésitez pas à me dire si 14h ou 16h vous arrange » : on GARDE,
        # la proposition de créneau est dedans.
        return m.group(0) if _CLAUSE_UTILE_RE.search(m.group(0)) else " "

    out = _FILLER_PHRASE_RE.sub(_remplace, text)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return out if len(out) >= 12 else text


# anti-hallucination RDV
# tournures « RDV pris »
_BOOKING_CONFIRM_PHRASE_RE = re.compile(
    r"(on se (?:voit|retrouve)"
    r"|je vous (?:attends|note|r[ée]serve|inscris|cale|bloque|re[çc]ois|accueille)"
    r"|(?:rendez-vous|rdv)\s+(?:est\s+)?(?:bien\s+)?"
    r"(?:confirm[ée]s?|not[ée]s?|r[ée]serv[ée]s?|pris|enregistr[ée]s?|valid[ée]s?|bloqu[ée]s?)"
    r"|c'est (?:not[ée]|bon|r[ée]serv[ée]|valid[ée]|confirm[ée]))",
    re.I,
)
# jour ou heure explicite
_BOOKING_WHEN_RE = re.compile(
    r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche"
    r"|demain|apr[eè]s-demain|\d{1,2}\s*h(?:\d{2})?|\d{1,2}:\d{2}|midi)\b",
    re.I,
)


def strip_false_booking_confirmation(text: str, *, booking_confirmed: bool) -> str:
    """Bloque les faux RDV confirmés."""
    if booking_confirmed or not text.strip():
        return text
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    # Avant on exigeait aussi un horaire dans LA MÊME phrase : « Je vous bloque
    # ce créneau » passait donc, alors que la réservation avait échoué.
    kept = [s for s in sentences if not _BOOKING_CONFIRM_PHRASE_RE.search(s)]
    result = " ".join(kept).strip()
    if len(result) < 15:
        return (
            "Je m'en occupe ! Confirmez-moi le jour et l'heure qui vous arrangent "
            "et je vous cale ça tout de suite 🙂"
        )
    return result


def polish_response(
    text: str, *, already_spoke: bool, grounded: bool = False, booking_confirmed: bool = False
) -> str:
    """Nettoyage final de la réponse."""
    out = strip_model_artifacts(text)
    out = strip_dialogue_scaffold(out)
    out = sanitize_identity(out)
    out = strip_letter_format(out)
    out = strip_inline_address(out)
    out = drop_leaked_instructions(out)
    out = strip_false_booking_confirmation(out, booking_confirmed=booking_confirmed)
    out = trim_trailing_deflection(out, grounded=grounded)
    out = strip_filler_phrases(out)
    out = trim_filler_closing(out)
    out = cut_to_last_sentence(out)
    out = cap_paragraphs(out)
    if already_spoke:
        out = strip_repeated_greeting(out)
    # en dernier : aucun filtre ne doit pouvoir retirer la divulgation
    out = ensure_ai_disclosure(out, already_spoke=already_spoke)
    return out.strip()


class ResponseGenerator:
    """Génère les réponses via LLM."""

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

    async def generate(
        self, state: ConversationState, on_token: TokenCallback | None = None
    ) -> str:
        """Répond depuis l'état conversationnel."""
        # des docs RAG → mode RAG
        if state.retrieved_documents:
            return await self.generate_with_rag(state, state.retrieved_documents, on_token=on_token)

        system_prompt = self.prompt_builder.build_system_prompt(state)
        user_prompt = self.prompt_builder.build_user_prompt(state)

        logger.info(
            "generator.generate",
            intent=state.current_intent,
            agent=state.agent_used,
            turn=state.turn_count,
            model=self.llm.model_name,
            streaming=on_token is not None,
        )

        return await self._run_llm(
            state=state,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=self.temperature,
            on_token=on_token,
        )

    async def generate_with_rag(
        self,
        state: ConversationState,
        documents: list[dict],
        on_token: TokenCallback | None = None,
    ) -> str:
        """Réponse enrichie via RAG."""
        state.retrieved_documents = documents

        system_prompt = self.prompt_builder.build_rag_system_prompt(state)
        user_prompt = self.prompt_builder.build_rag_user_prompt(state, documents)

        logger.info(
            "generator.generate_with_rag",
            num_documents=len(documents),
            model=self.llm.model_name,
            streaming=on_token is not None,
        )

        # RAG : plus factuel
        return await self._run_llm(
            state=state,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=min(self.temperature, 0.5),
            on_token=on_token,
        )

    async def _run_llm(
        self,
        *,
        state: ConversationState,
        user_prompt: str,
        system_prompt: str,
        temperature: float,
        on_token: TokenCallback | None,
    ) -> str:
        """Appelle le LLM puis nettoie."""
        already_spoke = any(m.get("role") == "assistant" for m in state.message_history[:-1])
        # réponse fondée ?
        grounded = self._grounded(state)
        # RDV confirmable seulement si acté
        booking_confirmed = self._booking_confirmed(state)

        if on_token is not None:
            acc: list[str] = []
            try:
                async for token in self.llm.generate_stream(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=220,
                ):
                    acc.append(token)
                    try:  # noqa: SIM105
                        await on_token(token)
                    except Exception:  # client coupé, on continue
                        pass
            except Exception as e:
                logger.warning("generator.stream_error", error=str(e))
            raw = "".join(acc).strip()
            if raw:
                return polish_response(
                    raw,
                    already_spoke=already_spoke,
                    grounded=grounded,
                    booking_confirmed=booking_confirmed,
                )
            # flux vide → appel classique

        response = await self.llm.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=220,
        )
        if response.finish_reason == "error":
            logger.warning("generator.llm_error_fallback", content=response.content)
            return self._template_fallback(state)
        return polish_response(
            response.content,
            already_spoke=already_spoke,
            grounded=grounded,
            booking_confirmed=booking_confirmed,
        )

    @staticmethod
    def _booking_confirmed(state: ConversationState) -> bool:
        """Vrai si le RDV a abouti."""
        ar = getattr(state, "action_result", None) or {}
        if not ar.get("success"):
            return False
        return bool(ar.get("appointment_id") or ar.get("operation") in {"confirm", "reschedule"})

    @staticmethod
    def _grounded(state: ConversationState) -> bool:
        """Vrai si les docs répondent."""
        docs = getattr(state, "retrieved_documents", None)
        if not docs:
            return False
        last_user = next(
            (m.get("content", "") for m in reversed(state.message_history) if m.get("role") == "user"),
            "",
        )
        from jenny.engine.intelligence import _retrieval_has_answer

        return _retrieval_has_answer(docs, last_user)

    def _template_fallback(self, state: ConversationState) -> str:
        """Réponses de secours sans LLM."""
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
