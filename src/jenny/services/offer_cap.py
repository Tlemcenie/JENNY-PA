"""Plafond anti-spam des messages commerciaux.

Par défaut : une offre (créneau libre, campagne) par client et par
semaine. Les rappels de RDV et les confirmations n'y passent pas.
Un client qui répond STOP ne reçoit plus rien de commercial.

Règle STOP : tous les mots du message doivent venir du vocabulaire
STOP (mot d'arrêt, « ne ... plus recevoir », « plus de pub »,
politesse). Un autre mot, ou un « pas » qui nie le STOP lui-même
(« n'arrêtez pas »), et c'est ambigu : on laisse la conversation
répondre. « Stop, pas de pub » reste un STOP. Une plainte (« vous ne
m'envoyez jamais d'offres »), une question (« pas de promo ? ») ou
une envie d'en recevoir (« je veux recevoir les offres ») ne
désinscrit pas.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import case, or_, update
from sqlalchemy.orm.attributes import set_committed_value

from jenny.core.logging import get_logger
from jenny.domain.models.customer import Customer

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

WINDOW = timedelta(days=7)
DEFAULT_MAX_PER_WEEK = 1


def _aware(dt: datetime | None) -> datetime | None:
    """Datetime naïve -> UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def can_offer(
    customer: Customer | None,
    now: datetime | None = None,
    max_per_week: int = DEFAULT_MAX_PER_WEEK,
) -> bool:
    """Vrai si on peut lui envoyer une offre."""
    if customer is None or max_per_week <= 0:
        return False
    if customer.anonymized_at is not None or customer.marketing_opt_out_at is not None:
        return False
    now = _aware(now) or datetime.now(UTC)
    start = _aware(customer.offer_window_start)
    if start is None or now - start >= WINDOW:
        return True
    return int(customer.offer_window_count or 0) < max_per_week


@dataclass(slots=True)
class OfferClaim:
    """Place prise dans le plafond."""

    customer_id: UUID
    prev_last: datetime | None
    prev_start: datetime | None
    prev_count: int


def _sync(customer: Customer, last, start, count) -> None:
    """Recale l'objet sans le salir."""
    set_committed_value(customer, "last_offer_at", last)
    set_committed_value(customer, "offer_window_start", start)
    set_committed_value(customer, "offer_window_count", count)


async def claim_offer(
    db: AsyncSession,
    customer: Customer,
    *,
    now: datetime | None = None,
    max_per_week: int = DEFAULT_MAX_PER_WEEK,
) -> OfferClaim | None:
    """Prend une place, en une requête atomique."""
    now = _aware(now) or datetime.now(UTC)
    if not can_offer(customer, now, max_per_week):
        return None
    expired = or_(
        Customer.offer_window_start.is_(None),
        Customer.offer_window_start <= now - WINDOW,
    )
    stmt = (
        update(Customer)
        .where(
            Customer.id == customer.id,
            Customer.anonymized_at.is_(None),
            Customer.marketing_opt_out_at.is_(None),
            or_(expired, Customer.offer_window_count < max_per_week),
        )
        .values(
            last_offer_at=now,
            offer_window_start=case((expired, now), else_=Customer.offer_window_start),
            offer_window_count=case((expired, 1), else_=Customer.offer_window_count + 1),
        )
        .execution_options(synchronize_session=False)
    )
    res = await db.execute(stmt)
    if res.rowcount != 1:
        # un autre envoi est passé avant
        return None
    claim = OfferClaim(
        customer_id=customer.id,
        prev_last=customer.last_offer_at,
        prev_start=customer.offer_window_start,
        prev_count=int(customer.offer_window_count or 0),
    )
    start = _aware(customer.offer_window_start)
    if start is None or now - start >= WINDOW:
        _sync(customer, now, now, 1)
    else:
        _sync(customer, now, customer.offer_window_start, claim.prev_count + 1)
    return claim


async def release_offer(
    db: AsyncSession, claim: OfferClaim, customer: Customer | None = None
) -> None:
    """Rend la place si l'envoi a raté."""
    await db.execute(
        update(Customer)
        .where(Customer.id == claim.customer_id)
        .values(
            last_offer_at=claim.prev_last,
            offer_window_start=claim.prev_start,
            offer_window_count=claim.prev_count,
        )
        .execution_options(synchronize_session=False)
    )
    if customer is not None:
        _sync(customer, claim.prev_last, claim.prev_start, claim.prev_count)


# ── désinscription ──


def _words(text: str) -> frozenset[str]:
    """Liste de mots -> ensemble."""
    return frozenset(text.split())


# mots qui veulent dire STOP
_STOP_WORDS = _words(
    "stop stopp stopper stoppez arret arrete arreter arretez desinscription desinscrire"
    " desinscris desinscrivez desinscrit desinscrite desabonner desabonnez"
    " desabonnement desabonne unsubscribe optout"
)
# « ne ... plus recevoir »
_STOP_VERBS = _words("recevoir envoyer envoyez contacter contactez ecrire ecrivez")
# ce qu'on refuse
_STOP_TARGETS = _words(
    "pub pubs publicite publicites sms offre offres message messages relance"
    " relances promo promos mail mails email emails notification notifications"
    " newsletter"
)
# politesse et petits mots
_STOP_FILLERS = _words(
    "svp stp svpl s il vous plait merci please pls beaucoup bcp ok oui non bon"
    " bonjour bonsoir hello salut coucou je j veux voudrais souhaite pouvez"
    " pourriez me moi m ne n plus jamais rien pas de d des du le la les l a au"
    " aux vos votre tout tous toutes pour et maintenant definitivement liste"
    " diffusion cette ce ces en y"
)
_STOP_ALLOWED = _STOP_WORDS | _STOP_VERBS | _STOP_TARGETS | _STOP_FILLERS
_MAX_STOP_WORDS = 14
# verbes d'arrêt conjugués
_STOP_ACTIONS = _words(
    "arrete arreter arretez stopper stoppez desinscrire desinscris desinscrivez"
    " desabonne desabonner desabonnez"
)
# négations franches
_NEG = _words("pas jamais")
# toutes les négations
_NOT = _NEG | _words("plus rien")
# petits mots entre deux
_GLUE = _words("de d des du me m moi vous nous les le la l vos votre")
# verbes d'envoi, infinitif
_SEND_INF = _words("recevoir envoyer contacter ecrire")
# « je ne veux pas recevoir »
_MODALS = _words("veux voudrais souhaite")
# entre « de » et la cible
_DETS = _words("vos votre ces ce cette les la le l")
# devant « pas de pub »
_POLITE = _words(
    "non oui ok bon merci svp stp svpl please pls beaucoup bcp bonjour bonsoir"
    " hello salut coucou et maintenant definitivement"
)

STOP_ACK = (
    "C'est noté, vous ne recevrez plus d'offres de notre part. "
    "Vos rappels de rendez-vous continuent normalement."
)


def _plain(text: str) -> str:
    """Minuscules, sans accents."""
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def _stop_tokens(text: str) -> list[str]:
    """Minuscules, sans accents, mots seuls."""
    return re.findall(r"[a-z0-9]+", _plain(text))


def _stop_clauses(text: str) -> list[tuple[list[str], bool]]:
    """Mots par morceau, et si question."""
    out = []
    for m in re.finditer(r"([^,.;:!?\n]+)([,.;:!?\n]*)", _plain(text)):
        words = re.findall(r"[a-z0-9]+", m.group(1))
        if words:
            out.append((words, "?" in m.group(2)))
    return out


def _denies_stop(words: list[str], i: int) -> bool:
    """Ce « pas » nie-t-il le STOP ?"""
    prev = words[i - 1] if i else ""
    if prev in _STOP_ACTIONS:
        # « n'arrêtez pas »
        return True
    j = i + 1
    while j < len(words) and words[j] in _GLUE:
        j += 1
    nxt = words[j] if j < len(words) else ""
    if nxt in _STOP_WORDS:
        # « pas arrêter », « pas me désinscrire »
        return True
    # « stop pas » tout seul
    return prev in _STOP_WORDS and nxt not in _STOP_TARGETS | _STOP_VERBS


def _after_stop(words: list[str], i: int) -> bool:
    """« arrêtez de m'envoyer »."""
    j = i - 1
    while j >= 0 and words[j] in _GLUE:
        j -= 1
    return j >= 0 and words[j] in _STOP_WORDS


def _no_before(words: list[str], i: int) -> bool:
    """« ne pas recevoir », « je veux plus recevoir »."""
    j = i - 1
    while j >= 0 and words[j] in _GLUE:
        j -= 1
    if j < 0 or words[j] not in _NOT:
        return False
    while j >= 0 and words[j] in _NOT:
        j -= 1
    # pas « vous ne pouvez pas »
    return j < 0 or words[j] in {"ne", "n"} | _MODALS


def _verb_stop(words: list[str], i: int, question: bool) -> bool | None:
    """Ce verbe : refus, envie, ou flou."""
    if _after_stop(words, i):
        return True
    if words[i] in _SEND_INF:
        if _no_before(words, i):
            return True
        # « vous ne pouvez pas m'envoyer »
        return None if set(words[:i]) & _NOT else False
    j = i - 1
    while j >= 0 and words[j] in {"me", "m", "nous", "en", "y", "les", "le", "la", "l"}:
        j -= 1
    after = set(words[i + 1 :]) & _NOT
    if j >= 0 and words[j] in {"ne", "n"}:
        if not after:
            return None
        if j and words[j - 1] == "vous":
            # « vous ne m'envoyez jamais » : plainte
            return True if "plus" in after and not after & _NEG and not question else None
        # « ne m'envoyez plus »
        return True
    if (j >= 0 and words[j] == "vous") or j < i - 1 or after & _NEG:
        # « vous m'envoyez », « m'envoyez plus »
        return None
    # « envoyez-moi des offres »
    return False


def _clause_stop(words: list[str], question: bool) -> bool | None:
    """Refus, envie, ou rien."""
    verbs = [i for i, w in enumerate(words) if w in _STOP_VERBS]
    if verbs:
        said = [_verb_stop(words, i, question) for i in verbs]
        if False in said:
            return False
        return True if all(said) else None
    for i, w in enumerate(words):
        if w not in _NEG and w != "plus":
            continue
        if i and words[i - 1] not in _MODALS | _POLITE:
            # « il n'y a pas d'offres »
            continue
        j = i + 1
        while j < len(words) and words[j] in _NOT:
            j += 1
        if j < len(words) and words[j] in {"de", "d", "des", "du"}:
            j += 1
            while j < len(words) and words[j] in _DETS:
                j += 1
            if j < len(words) and words[j] in _STOP_TARGETS:
                # « pas de pub ? » : question
                return None if question else True
    return None


def is_stop_reply(text: str | None) -> bool:
    """STOP seul ou poli ; la négation doit viser le STOP."""
    if not text:
        return False
    words = _stop_tokens(text)
    if not words or len(words) > _MAX_STOP_WORDS:
        return False
    if any(w not in _STOP_ALLOWED for w in words):
        # « stop je voulais dire jeudi »
        return False
    clauses = _stop_clauses(text)
    for clause, _q in clauses:
        if " pas du tout " in f" {' '.join(clause)} ":
            return False
        if any(w in _NEG and _denies_stop(clause, i) for i, w in enumerate(clause)):
            return False
    said = [_clause_stop(c, q) for c, q in clauses]
    if False in said:
        # « je veux recevoir les offres »
        return False
    return bool(set(words) & _STOP_WORDS) or True in said


def set_opt_out(customer: Customer, opt_out: bool, now: datetime | None = None) -> None:
    """Coche ou décoche la désinscription."""
    customer.marketing_opt_out_at = (_aware(now) or datetime.now(UTC)) if opt_out else None


async def apply_stop_reply(
    db: AsyncSession,
    *,
    business_id: UUID,
    customer_id: UUID | None,
    text: str | None,
    conversation_id: UUID | None = None,
) -> bool:
    """Désinscrit si c'est un STOP (sans commit)."""
    if not is_stop_reply(text):
        return False
    from jenny.domain.models.conversation import Conversation
    from jenny.domain.models.waitlist_entry import WaitlistEntry

    conv = None
    if conversation_id is not None:
        conv = await db.get(Conversation, conversation_id)
        if conv is not None and conv.business_id != business_id:
            conv = None
    cid = customer_id or (conv.customer_id if conv is not None else None)
    if cid is not None:
        cust = await db.get(Customer, cid)
        if cust is None or cust.business_id != business_id:
            return False
        if cust.marketing_opt_out_at is None:
            set_opt_out(cust, True)
            await db.flush()
            logger.info("offer_cap.opt_out", customer_id=str(cid))
        return True
    if conv is None:
        return False
    # anonyme : on vide son attente
    res = await db.execute(
        update(WaitlistEntry)
        .where(
            WaitlistEntry.business_id == business_id,
            WaitlistEntry.conversation_id == conv.id,
            WaitlistEntry.customer_id.is_(None),
            WaitlistEntry.status == "waiting",
        )
        .values(status="cancelled")
        .execution_options(synchronize_session=False)
    )
    logger.info("offer_cap.opt_out_anonyme", conversation_id=str(conv.id), entries=res.rowcount)
    return True
