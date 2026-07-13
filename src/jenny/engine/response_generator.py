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
    from collections.abc import Awaitable, Callable

    from jenny.engine.state_manager import ConversationState
    from jenny.llm.providers import BaseLLMProvider

    TokenCallback = Callable[[str], Awaitable[None]]

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
# Sonde d'identité à la 2e personne, souvent RECOPIÉE par le petit modèle dans
# sa réponse (« Attends, t'es un robot ou une vraie personne ? »). Combinée à un
# terme « IA », c'est un écho de la question du client, pas une phrase utile → à
# retirer (le sanitizer ne l'attrapait pas car ce n'est pas auto-référentiel).
_IDENTITY_PROBE_RE = re.compile(
    r"\b(t['’]es|tu\s+es|es[\s-]?tu|vous\s+[êe]tes|[êe]tes[\s-]?vous|"  # noqa: RUF001
    r"une\s+(?:vraie\s+)?personne|un\s+programme|une\s+machine|un\s+vrai\s+humain)\b",
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
    "Je suis l'assistante de l'établissement, ravie de vous aider ! Que puis-je faire pour vous ?"
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
            (
                _AI_TERMS_RE.search(s)
                and (
                    _SELF_REF_RE.search(s)  # « je suis une IA »
                    or _IDENTITY_PROBE_RE.search(s)  # écho « t'es un robot ? »
                )
            )
            or _META_LEAK_RE.search(s)  # fuite RAG / « je n'ai pas l'info »
        )
    ]
    cleaned = " ".join(kept).strip()
    if len(cleaned) < 15:
        return _IDENTITY_FALLBACK
    return cleaned


# Salutation en ouverture (à retirer si Jenny a déjà parlé dans la conversation).
_OPENING_GREETING_RE = re.compile(
    r"^\s*(?:bonjour|bonsoir|coucou|salut|hello|hey|re[\s-]?bonjour)\b"
    r"[^.!?\n]*[.!?\n]?\s*",
    re.IGNORECASE,
)
# Fragments d'instructions internes parfois recopiés par les petits modèles.
_LEAKED_INSTRUCTION_RE = re.compile(
    r"à dire au client|ne recopie|reformule|avec tes mots|ne les change|"
    r"reprends? exactement|en gardant exactement|ne propose aucun|"
    r"=== |faits pour ta réponse|consigne|sans insister",
    re.IGNORECASE,
)


# Mise en forme « courrier » (formule d'appel + signature) que les petits modèles
# produisent parfois — déplacée pour garder un ton « message » conversationnel.
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
    """Retire la formule d'appel (« Chère cliente, ») et la signature (« Bien
    cordialement, Jenny ») : un message de chat n'est pas une lettre."""
    out = _LETTER_OPENING_RE.sub("", text, count=1)
    out = _LETTER_SIGNATURE_RE.sub("", out, count=1)
    out = _LETTER_NAME_RE.sub("", out, count=1)
    out = out.strip()
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    return out if len(out) >= 10 else text


def strip_repeated_greeting(text: str) -> str:
    """Retire une salutation d'ouverture (« Bonjour ! … ») quand Jenny a déjà parlé.

    Le petit modèle resalue souvent à chaque tour, ce qui fait « robotique ». On ne
    retire la salutation QUE si le reste du message tient debout (≥15 caractères).
    """
    stripped = _OPENING_GREETING_RE.sub("", text, count=1).strip()
    if len(stripped) >= 15:
        # Recapitalise la première lettre pour une phrase propre.
        return stripped[0].upper() + stripped[1:]
    return text


def drop_leaked_instructions(text: str) -> str:
    """Supprime les phrases qui recopient une consigne interne (méta-fuite)."""
    if not _LEAKED_INSTRUCTION_RE.search(text):
        return text
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    kept = [s for s in sentences if not _LEAKED_INSTRUCTION_RE.search(s)]
    cleaned = " ".join(kept).strip()
    return cleaned if len(cleaned) >= 15 else text


def strip_model_artifacts(text: str) -> str:
    """Retire les jetons de gabarit de chat et le texte hors-langue que les petits
    modèles laissent parfois fuir (« <|im_start|> », « 好的… », balises ChatML).

    Coupe tout à partir d'un jeton de gabarit (le modèle a « fini » et déraille
    au-delà), puis retire d'éventuels blocs CJK/idéogrammes résiduels — Jenny
    répond en langues latines uniquement, un bloc chinois est forcément du bruit.
    """
    if not text:
        return text
    # 1) Jeton de gabarit ChatML / spécial → on coupe net avant.
    m = re.search(r"<\|[^>]*\|>|<\|?(?:im_start|im_end|endoftext|assistant|user|system)\b", text)
    if m:
        text = text[: m.start()]
    # 2) Blocs de caractères CJK (chinois/japonais/coréen) → bruit, on retire.
    text = re.sub(r"[　-〿㐀-鿿＀-￯가-힯]+", "", text)
    return text.strip()


# Formules de clôture CREUSES que les petits modèles collent en fin de réponse,
# souvent à répétition — elles n'apportent rien et cassent le ton « message ».
# On retire UNIQUEMENT la phrase FINALE quand c'en est une (jamais une vraie
# question, ni une déflexion « je vérifie » qui, elle, sert à la détection de
# lacune). Le but : des réponses plus courtes, vivantes, moins robotiques.
# Une phrase de clôture est « creuse » si elle contient l'un de ces motifs de
# remplissage (recherche N'IMPORTE OÙ dans la phrase — « Si vous avez des
# préférences, n'hésitez pas à me le dire » doit sauter comme « N'hésitez pas… »).
_FILLER_CLOSING_RE = re.compile(
    r"n['’]h[ée]sitez\s+pas\b"  # noqa: RUF001
    r"|je\s+(?:reste|suis|me\s+tiens)\s+(?:à\s+votre\s+disposition|(?:là|ici)\s+pour\s+"
    r"(?:vous\s+aider|r[ée]pondre|toute\s+question))"
    r"|nous\s+restons\s+à\s+votre\s+disposition"
    r"|au\s+plaisir\s+de\s+vous\s+(?:aider|lire|revoir)",
    re.IGNORECASE,
)


def trim_filler_closing(text: str) -> str:
    """Retire une formule de clôture creuse en FIN de message (« N'hésitez pas… »,
    « Je reste à votre disposition »…) — mais jamais si c'est la seule phrase, ni
    si la dernière phrase est une vraie question (« Vous voulez que je réserve ? »)."""
    if not text:
        return text
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    if len(sentences) < 2:
        return text
    last = sentences[-1].strip()
    # On garde une VRAIE question/relance (elle engage le client, c'est bienvenu),
    # SAUF si elle contient quand même du remplissage (« … n'hésitez pas ? »).
    if last.endswith("?") and not _FILLER_CLOSING_RE.search(last):
        return text
    if _FILLER_CLOSING_RE.search(last):
        trimmed = " ".join(sentences[:-1]).strip()
        if len(trimmed) >= 12:
            return trimmed
    return text


def cut_to_last_sentence(text: str) -> str:
    """Si le message a été coupé net (plafond de tokens) — il ne finit pas par une
    ponctuation de fin — on tronque à la DERNIÈRE phrase complète, pour ne jamais
    laisser une phrase inachevée. Sans effet sur un message déjà bien terminé."""
    t = (text or "").strip()
    if not t or t[-1] in ".!?…\"»)":
        return t
    # Position de la dernière ponctuation de fin de phrase.
    m = list(re.finditer(r"[.!?…]", t))
    if not m:
        return t  # aucune phrase complète : on garde tel quel (mieux que vide)
    cut = t[: m[-1].end()].strip()
    return cut if len(cut) >= 12 else t


# Formule d'appel « courrier » (« Madame, », « Cher client ») que le petit modèle
# glisse parfois EN MILIEU de phrase (« Je vous remercie, madame ou monsieur, … »).
# On la retire n'importe où (pas seulement en tête).
_INLINE_ADDRESS_RE = re.compile(
    r"\b(?:ch[èe]re?s?\s+client(?:e|es|s)?|cher\s+client|"
    r"madame(?:\s+ou\s+monsieur)?|monsieur(?:\s+ou\s+madame)?|mademoiselle)\b[\s,]*",
    re.IGNORECASE,
)


def strip_inline_address(text: str) -> str:
    """Retire les « Madame/Monsieur/Cher client » où qu'ils soient (ton message)."""
    out = _INLINE_ADDRESS_RE.sub("", text)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,")
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    return out if len(out) >= 10 else text


def trim_trailing_deflection(text: str, *, grounded: bool) -> str:
    """Retire une DÉFLEXION (« je vérifie et je reviens ») collée en fin de message
    APRÈS une vraie réponse — mais UNIQUEMENT si la récupération a fondé la réponse
    (``grounded``). Ainsi on ne touche jamais à une déflexion qui EST la réponse
    (vraie lacune) : elle reste intacte pour la détection de lacune.
    """
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
    """Limite un pavé à ``max_paragraphs`` blocs — un message, pas un essai.

    Garde les premiers blocs (l'info est en tête) ; si le DERNIER bloc retiré est
    une vraie question/relance, on la rattache (elle engage le client). Sans effet
    si le texte tient déjà en peu de blocs."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    if len(blocks) <= max_paragraphs:
        return text
    kept = blocks[:max_paragraphs]
    # Récupère une éventuelle question finale dans les blocs coupés.
    tail_question = next(
        (b for b in reversed(blocks[max_paragraphs:]) if b.rstrip().endswith("?")),
        None,
    )
    if tail_question and not kept[-1].rstrip().endswith("?"):
        # Ne garde que la dernière phrase-question du bloc (concise).
        q = re.split(r"(?<=[.!?…])\s+", tail_question)[-1].strip()
        kept.append(q)
    return "\n\n".join(kept)


# Gabarit de dialogue fuité (« Client : … Jenny : … ») rejoué par les petits
# modèles, surtout sur des entrées dégénérées (« ... », ponctuation seule).
_ROLE_PREFIX_RE = re.compile(r"^\s*(?:client|utilisateur|user|assistant)\s*:\s*", re.I)
_JENNY_LABEL_RE = re.compile(r"\bjenny\s*:\s*", re.I)


def strip_dialogue_scaffold(text: str) -> str:
    """Retire l'échafaudage de dialogue fuité (« Client : … Jenny : … »).

    Si le modèle a rejoué « Jenny : », la vraie réponse est ce qui suit le dernier
    label ; on retire aussi les préfixes de rôle (« Client : ») en tête de ligne."""
    labels = list(_JENNY_LABEL_RE.finditer(text))
    if labels:
        text = text[labels[-1].end() :]
    lines = [_ROLE_PREFIX_RE.sub("", ln) for ln in text.splitlines()]
    lines = [ln for ln in lines if not re.match(r"^\s*(?:client|utilisateur|user)\s*:", ln, re.I)]
    cleaned = "\n".join(lines).strip()
    return cleaned if cleaned else text


# Clause creuse « n'hésitez pas … » — à retirer OÙ QU'ELLE SOIT (le petit modèle
# la répète parfois en milieu de message, pas seulement en clôture).
_FILLER_PHRASE_RE = re.compile(r"\s*\bn['’]?h[ée]sitez\s+pas\b[^.!?]*[.!?]?", re.I)  # noqa: RUF001


def strip_filler_phrases(text: str) -> str:
    """Retire les clauses « n'hésitez pas … » n'importe où dans le message."""
    if not _FILLER_PHRASE_RE.search(text):
        return text
    out = _FILLER_PHRASE_RE.sub(" ", text)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return out if len(out) >= 12 else text


# ── Anti-hallucination de confirmation de RDV ──
# Tournures AFFIRMATIVES qui annoncent un rendez-vous pris (pas une question :
# « voulez-vous un rendez-vous demain ? » ne doit PAS matcher — d'où l'exigence
# d'un verbe/formule de confirmation, jamais le simple mot « rendez-vous »).
_BOOKING_CONFIRM_PHRASE_RE = re.compile(
    r"(on se (?:voit|retrouve)"
    r"|je vous (?:attends|note|r[ée]serve|inscris|cale|bloque|re[çc]ois|accueille)"
    r"|(?:rendez-vous|rdv)\s+(?:est\s+)?(?:bien\s+)?"
    r"(?:confirm[ée]s?|not[ée]s?|r[ée]serv[ée]s?|pris|enregistr[ée]s?|valid[ée]s?|bloqu[ée]s?)"
    r"|c'est (?:not[ée]|bon|r[ée]serv[ée]|valid[ée]|confirm[ée]))",
    re.I,
)
# Jour ou heure explicite (une confirmation dangereuse épingle un créneau précis).
_BOOKING_WHEN_RE = re.compile(
    r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche"
    r"|demain|apr[eè]s-demain|\d{1,2}\s*h(?:\d{2})?|\d{1,2}:\d{2}|midi)\b",
    re.I,
)


def strip_false_booking_confirmation(text: str, *, booking_confirmed: bool) -> str:
    """Filet anti-hallucination : sans réservation RÉELLEMENT aboutie
    (``action_result.success``), Jenny ne doit JAMAIS annoncer un RDV avec un
    jour/une heure — sinon le client se croit réservé (no-show garanti). On retire
    ces phrases ; si tout saute, on retombe sur une relance sûre (faire confirmer
    le créneau). N'intervient jamais quand la réservation est réellement confirmée."""
    if booking_confirmed or not text.strip():
        return text
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    kept = [
        s
        for s in sentences
        if not (_BOOKING_CONFIRM_PHRASE_RE.search(s) and _BOOKING_WHEN_RE.search(s))
    ]
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
    """Nettoyage final : artefacts modèle + identité + format courrier (y compris
    en milieu de phrase) + fuites de consignes + confirmation de RDV hallucinée +
    déflexion post-réponse (si fondée) + formule de clôture creuse + phrase
    inachevée + cap de longueur + salutation."""
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
    return out.strip()


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

    async def generate(
        self, state: ConversationState, on_token: TokenCallback | None = None
    ) -> str:
        """Génère une réponse à partir de l'état conversationnel.

        Si ``on_token`` est fourni, la réponse est diffusée token par token via ce
        callback (premier token rapide → le chat « répond » tout de suite). Le
        texte retourné reste la version NETTOYÉE (garde-fou persona) : l'appelant
        l'utilise comme version de référence après le flux brut.
        """
        # Si on a des documents RAG, utiliser le mode RAG
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
        """Génère une réponse enrichie avec des documents RAG (streaming optionnel)."""
        state.retrieved_documents = documents

        system_prompt = self.prompt_builder.build_rag_system_prompt(state)
        user_prompt = self.prompt_builder.build_rag_user_prompt(state, documents)

        logger.info(
            "generator.generate_with_rag",
            num_documents=len(documents),
            model=self.llm.model_name,
            streaming=on_token is not None,
        )

        # En mode RAG on reste plus factuel (température plafonnée).
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
        """Appelle le LLM (streamé si ``on_token``), puis nettoie la sortie.

        En streaming : on relaie chaque token BRUT au client pour la réactivité,
        on accumule, et on renvoie la version nettoyée (le client remplacera par
        cette version finale à la fin du flux). Repli automatique sur l'appel
        non-streamé si le flux échoue ou revient vide.
        """
        already_spoke = any(m.get("role") == "assistant" for m in state.message_history[:-1])
        # La récupération a-t-elle fondé la réponse ? Si oui, une déflexion collée
        # en fin (« je vérifie et je reviens ») est du bruit à retirer ; sinon on
        # la garde (elle EST la réponse à une vraie lacune).
        grounded = self._grounded(state)
        # Un RDV n'est « confirmable » en texte que si l'action l'a réellement acté.
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
                    try:  # noqa: SIM105 - le commentaire documente le silence volontaire
                        await on_token(token)
                    except Exception:  # le client a coupé : on continue d'accumuler
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
            # Flux vide/échoué → on retombe sur l'appel classique ci-dessous.

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
        """Vrai si une action de RDV a RÉELLEMENT abouti (réservation, confirmation
        ou déplacement) — seul cas où Jenny peut annoncer un créneau au client."""
        ar = getattr(state, "action_result", None) or {}
        if not ar.get("success"):
            return False
        return bool(ar.get("appointment_id") or ar.get("operation") in {"confirm", "reschedule"})

    @staticmethod
    def _grounded(state: ConversationState) -> bool:
        """Vrai si les documents récupérés fondent une réponse à la question courante."""
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
