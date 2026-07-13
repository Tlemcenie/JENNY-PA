"""Assistant du coiffeur : Jenny côté GÉRANT (pas côté client).

Ici Jenny est l'assistante du commerçant, en toute transparence (le gérant sait
qu'il parle à son outil). Elle fait des comptes rendus, répond à ses questions,
et exécute des actions de gestion par chat :
- compte rendu / métriques des rendez-vous,
- blocage de créneaux dans l'agenda,
- ajout d'informations à la base de connaissances.

Tout est en français. Les réponses d'action sont déterministes (chiffres fiables) ;
seule la question ouverte passe par le LLM, avec le contexte du salon.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from jenny.core.logging import get_logger
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time

# Extraction du nom de client dans « annule le rdv de Marie ».
_CLIENT_NAME_RE = re.compile(
    r"(?:de|pour|du|rdv\s+de|rendez[\s-]vous\s+de)\s+([A-Za-zÀ-ÿ][\wÀ-ÿ'’-]{1,40})",  # noqa: RUF001
    re.I,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# ── Détection d'intention propriétaire (règles robustes, français) ──

_BLOCK_RE = re.compile(
    r"\b(bloqu|indisponible|je\s+ne\s+suis\s+pas\s+l[àa]|ferme|cong[ée]|pas\s+dispo|r[ée]serve\s+moi)",
    re.I,
)
_ADD_KB_RE = re.compile(
    r"\b(note\s+(?:que|bien)|ajoute(?:r)?\s+(?:que|dans|à\s+la\s+base)|retiens\s+que|"
    r"enregistre\s+que|m[ée]morise|souviens[\s-]toi)",
    re.I,
)
_CANCEL_RE = re.compile(r"\b(annul|supprim|d[ée]command|enl[èe]ve\s+le\s+rdv)", re.I)
_MOVE_RE = re.compile(r"\b(d[ée]plac|d[ée]cal|report|repouss|chang.*(?:heure|jour)|avanc.*rdv)", re.I)
_REVENUE_RE = re.compile(
    r"\b(chiffre\s+d['’]affaires|\bca\b|recette|combien\s+(?:je|tu)\s+|gagn|"  # noqa: RUF001
    r"rapporte|encaiss|revenu)",
    re.I,
)
_AGENDA_RE = re.compile(
    r"\b(qui\s+(?:vient|j['’]ai|est\s+pr[ée]vu)|clients?\s+du\s+jour|liste\s+(?:des?\s+)?"  # noqa: RUF001
    r"(?:rdv|rendez|clients)|qui\s+[àa]\s+\d|programme\s+du\s+jour|planning\s+du\s+jour)",
    re.I,
)
_REPORT_RE = re.compile(
    r"\b(combien|r[ée]sum[ée]|compte[\s-]rendu|bilan|[çc]a\s+donne\s+quoi|"
    r"mes\s+(?:rdv|rendez)|rendez[\s-]vous|agenda|aujourd|cette\s+semaine|à\s+venir|confirm)",
    re.I,
)
_HISTORY_RE = re.compile(
    r"\b(historique|fiche\s+(?:de|du|client)|dossier\s+de|infos?\s+sur|"
    r"combien\s+de\s+fois|d[ée]j[àa]\s+venu|fid[ée]lit[ée]\s+de)",
    re.I,
)
_PHONE_RE = re.compile(r"(?:\+?\d[\s.\-]?){8,}")
_TOP_PRESTATIONS_RE = re.compile(
    r"\b(?:presta(?:tion)?s?|services?)\b.{0,25}\b(?:plus\s+demand|populair|"
    r"r[ée]serv|pris|vendu|marche|cartonne|succ[èe]s)"
    r"|\b(?:plus\s+demand[ée]e?|qui\s+(?:marche|cartonne)\s+le\s+mieux"
    r"|top\s+(?:des\s+)?(?:presta|service)|meilleure?s?\s+ventes?)",
    re.I,
)


def detect_owner_intent(message: str) -> str:
    """Classe le message du gérant : cancel | agenda | block | add_knowledge |
    report | revenue | top_prestations | client_history | general."""
    m = message or ""
    if _ADD_KB_RE.search(m):
        return "add_knowledge"
    if _CANCEL_RE.search(m):
        return "cancel"
    if _MOVE_RE.search(m):
        return "move"
    if _BLOCK_RE.search(m):
        return "block_slot"
    if _HISTORY_RE.search(m):
        return "client_history"
    if _TOP_PRESTATIONS_RE.search(m):
        return "top_prestations"
    if _REVENUE_RE.search(m):
        return "revenue"
    if _AGENDA_RE.search(m):
        return "agenda"
    if _REPORT_RE.search(m):
        return "report"
    return "general"


def _parse_time_range(message: str) -> tuple[time, time] | None:
    """Extrait un intervalle « de 14h à 16h » / « 14h-16h » → (début, fin)."""
    m = re.search(
        r"(\d{1,2})\s*(?:h|:|heures?)\s*(\d{2})?\s*(?:[-àa]|jusqu['’ ]?[àa]?|au?)\s*"  # noqa: RUF001
        r"(\d{1,2})\s*(?:h|:|heures?)\s*(\d{2})?",
        message,
        re.I,
    )
    if not m:
        return None
    h1, m1, h2, m2 = m.group(1), m.group(2), m.group(3), m.group(4)
    try:
        return time(int(h1), int(m1 or 0)), time(int(h2), int(m2 or 0))
    except ValueError:
        return None


async def _business_tz(db: AsyncSession, business: Business | None) -> ZoneInfo:
    try:
        return ZoneInfo((business.timezone if business else None) or "Europe/Paris")
    except Exception:
        return ZoneInfo("Europe/Paris")


# ── Compte rendu / métriques ──────────────────────────────────────────────────


async def _handle_report(db: AsyncSession, bid: UUID) -> dict:
    now = datetime.now(UTC)
    today = now.date()
    today_start = datetime(today.year, today.month, today.day, tzinfo=UTC)
    today_end = today_start + timedelta(days=1)
    week_end = today_start + timedelta(days=7)

    async def _count(*conds) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(Appointment.id)).where(
                        Appointment.business_id == bid, *conds
                    )
                )
            ).scalar_one()
            or 0
        )

    not_cancelled = Appointment.status.notin_(["cancelled", "blocked"])
    upcoming = await _count(not_cancelled, Appointment.start_at >= now)
    today_n = await _count(
        not_cancelled, Appointment.start_at >= today_start, Appointment.start_at < today_end
    )
    week_n = await _count(
        not_cancelled, Appointment.start_at >= today_start, Appointment.start_at < week_end
    )
    confirmed = await _count(Appointment.status == "confirmed", Appointment.start_at >= now)
    scheduled = await _count(Appointment.status == "scheduled", Appointment.start_at >= now)

    parts = [
        "Voici le point sur ton agenda 💇 :",
        f"• {today_n} rendez-vous aujourd'hui",
        f"• {week_n} sur les 7 prochains jours ({upcoming} à venir au total)",
        f"• {confirmed} confirmé(s), {scheduled} en attente de confirmation",
    ]
    msg = "\n".join(parts)
    if upcoming == 0:
        msg = "Ton agenda est vide pour le moment — aucun rendez-vous à venir."

    # Acomptes anti-no-show : le VRAI suivi des paiements (PaymentRecord).
    from jenny.domain.models.payment_record import PaymentRecord

    async def _dep(status: str) -> tuple[int, int]:
        row = (
            await db.execute(
                select(
                    func.count(PaymentRecord.id),
                    func.coalesce(func.sum(PaymentRecord.amount_minor), 0),
                ).where(
                    PaymentRecord.business_id == bid,
                    PaymentRecord.status == status,
                    PaymentRecord.order_reference.like("acompte:%"),
                )
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    dep_pending_n, dep_pending_cents = await _dep("pending")
    dep_paid_n, dep_paid_cents = await _dep("paid")
    if dep_pending_n or dep_paid_n:
        msg += (
            f"\n• Acomptes : {dep_paid_n} encaissé(s) ({dep_paid_cents / 100:.0f}€), "
            f"{dep_pending_n} en attente ({dep_pending_cents / 100:.0f}€)"
        )
    return {
        "response": msg,
        "action": "report",
        "data": {
            "today": today_n,
            "week": week_n,
            "upcoming": upcoming,
            "confirmed": confirmed,
            "scheduled": scheduled,
            "deposits_paid": dep_paid_n,
            "deposits_paid_eur": dep_paid_cents / 100,
            "deposits_pending": dep_pending_n,
            "deposits_pending_eur": dep_pending_cents / 100,
        },
    }


# ── Bloquer un créneau ────────────────────────────────────────────────────────


async def _handle_block(db: AsyncSession, bid: UUID, actor: str, message: str) -> dict:
    business = await db.get(Business, bid)
    tz = await _business_tz(db, business)
    day = parse_fr_date(message, today=datetime.now(tz).date())
    if day is None:
        return {
            "response": "Bien sûr — quel jour veux-tu bloquer ? (ex. « bloque mardi de 14h à 16h »)",
            "action": "block_slot",
            "data": {"missing": "date"},
        }
    rng = _parse_time_range(message)
    if rng is None:
        single = parse_fr_time(message)
        if single is None:
            # Jour entier bloqué (09h-20h par défaut).
            start_t, end_t = time(9, 0), time(20, 0)
            label = "toute la journée"
        else:
            start_t = single
            end_t = time(min(single.hour + 1, 23), single.minute)
            label = f"à {single.strftime('%Hh%M')}"
    else:
        start_t, end_t = rng
        label = f"de {start_t.strftime('%Hh%M')} à {end_t.strftime('%Hh%M')}"

    start_local = datetime(day.year, day.month, day.day, start_t.hour, start_t.minute, tzinfo=tz)
    end_local = datetime(day.year, day.month, day.day, end_t.hour, end_t.minute, tzinfo=tz)
    if end_local <= start_local:
        end_local = start_local + timedelta(hours=1)

    appt = Appointment(
        business_id=bid,
        title="🚫 Indisponible",
        description="Créneau bloqué par le gérant via Jenny.",
        channel="block",
        start_at=start_local.astimezone(UTC),
        end_at=end_local.astimezone(UTC),
        status="blocked",
        created_by=actor or "Jenny",
    )
    db.add(appt)
    await db.commit()
    day_label = f"{day.day:02d}/{day.month:02d}"
    return {
        "response": f"C'est bloqué ✅ — le {day_label} {label}, tu n'es pas disponible. "
        "Je ne proposerai pas ce créneau aux clients.",
        "action": "block_slot",
        "data": {"appointment_id": str(appt.id)},
    }


# ── Ajouter à la base de connaissances ────────────────────────────────────────


def _extract_knowledge(message: str) -> str:
    m = re.sub(
        r"^.*?(?:note\s+(?:que|bien)|ajoute(?:r)?\s+(?:que|à\s+la\s+base|dans\s+la\s+base)|"
        r"retiens\s+que|enregistre\s+que|m[ée]morise|souviens[\s-]toi(?:\s+que)?)\s*[:\-]?\s*",
        "",
        message,
        count=1,
        flags=re.I,
    )
    return m.strip()


async def _handle_add_knowledge(db: AsyncSession, bid: UUID, message: str) -> dict:
    content = _extract_knowledge(message)
    if len(content) < 4:
        return {
            "response": "Dis-moi quoi retenir et je l'ajoute à ta base (ex. « note que le parking est gratuit »).",
            "action": "add_knowledge",
            "data": {"missing": "content"},
        }
    saved = False
    try:
        from jenny.rag.knowledge_base import KnowledgeBase

        kb = KnowledgeBase(business_id=bid, session=db)
        await kb.add_text(content=content, title=content[:80], category="info")
        saved = True
    except Exception as exc:  # pragma: no cover - dépend de pgvector
        logger.warning("owner.add_knowledge.failed", error=str(exc))
    resp = (
        f"C'est noté ✅ — je retiens : « {content} ». Je m'en servirai pour répondre aux clients."
        if saved
        else f"J'ai bien noté « {content} ». Je l'intégrerai à ta base dès que possible."
    )
    return {"response": resp, "action": "add_knowledge", "data": {"saved": saved}}


# ── Question ouverte (LLM avec contexte salon) ────────────────────────────────


async def _gather_owner_context(db: AsyncSession, bid: UUID) -> str:
    """Instantané RÉEL du salon, injecté au LLM pour des réponses fondées
    (sinon l'assistant répond « à côté » → effet « bête »)."""
    business = await db.get(Business, bid)
    tz = await _business_tz(db, business)
    now = datetime.now(UTC)
    today = datetime.now(tz).date()
    today_start = datetime(today.year, today.month, today.day, tzinfo=tz).astimezone(UTC)
    today_end = today_start + timedelta(days=1)
    week_end = today_start + timedelta(days=7)

    lines: list[str] = [f"Salon : {business.name if business else 'salon'}."]

    try:
        from jenny.services.prestation_service import load_active_prestations

        prestations = await load_active_prestations(db, bid)
        cat = "; ".join(
            f"{p.name} {p.price_cents / 100:.0f}€"
            f"{f'/{p.duration_minutes}min' if p.duration_minutes else ''}"
            for p in prestations[:25]
            if p.price_cents
        )
        if cat:
            lines.append(f"Prestations & tarifs : {cat}.")
    except Exception:  # pragma: no cover
        prestations = []

    async def _count(*conds) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(Appointment.id)).where(
                        Appointment.business_id == bid, *conds
                    )
                )
            ).scalar_one()
            or 0
        )

    nc = Appointment.status.notin_(["cancelled", "blocked"])
    today_n = await _count(nc, Appointment.start_at >= today_start, Appointment.start_at < today_end)
    week_n = await _count(nc, Appointment.start_at >= today_start, Appointment.start_at < week_end)
    upcoming = await _count(nc, Appointment.start_at >= now)
    lines.append(
        f"Rendez-vous : {today_n} aujourd'hui, {week_n} sur 7 jours, {upcoming} à venir au total."
    )

    n_clients = int(
        (
            await db.execute(
                select(func.count(Customer.id)).where(Customer.business_id == bid)
            )
        ).scalar_one()
        or 0
    )
    lines.append(f"Clients enregistrés : {n_clients}.")
    return "\n".join(lines)


async def _handle_general(db: AsyncSession, bid: UUID, message: str) -> dict:
    provider = None
    try:
        from jenny.llm.providers import get_default_llm_provider

        provider = get_default_llm_provider()
    except Exception:
        provider = None

    context = await _gather_owner_context(db, bid)

    if provider is None:
        return {
            "response": "Je suis là pour piloter le salon avec toi : agenda du jour, point sur tes "
            "rendez-vous, chiffre d'affaires estimé, blocage de créneau, fiche client, ajout d'infos "
            "à ta base. Que veux-tu ?",
            "action": "general",
            "data": {},
        }

    # Jenny côté gérant : transparente, proactive, et SURTOUT fondée sur les vraies
    # données du salon (injectées) → elle répond précisément au lieu de botter en touche.
    system = (
        "Tu es Jenny, le bras droit du gérant de ce salon de coiffure (son assistante de "
        "gestion, en toute transparence). Tu es vive, concrète et tu tutoies le gérant.\n"
        "Tu connais l'état RÉEL du salon ci-dessous : appuie-toi dessus pour répondre "
        "précisément (tarifs, nombre de RDV, charge, clients). Tu peux faire des calculs simples "
        "à partir de ces données et donner des conseils de gestion actionnables (remplir les "
        "créneaux creux, réduire les no-shows, fidéliser, mettre en avant une prestation rentable).\n"
        "Tu peux AGIR via ces commandes — propose-les quand c'est pertinent : « agenda du jour », "
        "« mon chiffre d'affaires », « bloque mardi de 14h à 16h », « annule/déplace le rdv de <nom> », "
        "« historique de <nom> », « note que <info> » (ajout à la base).\n"
        "N'invente JAMAIS un chiffre absent des données ; si une donnée manque, dis-le et propose "
        "la commande pour l'obtenir. Réponds en français, 2 à 5 phrases, sans bla-bla.\n\n"
        f"=== ÉTAT DU SALON (données réelles) ===\n{context}"
    )
    try:
        out = await provider.generate(
            prompt=f"Message du gérant : {message}",
            system_prompt=system,
            temperature=0.4,
            max_tokens=320,
        )
        text = out.content if out.finish_reason != "error" else None
    except Exception as exc:  # pragma: no cover
        logger.warning("owner.general.llm_error", error=str(exc))
        text = None
    return {
        "response": text
        or "Je peux te sortir un point sur tes rendez-vous, ton CA estimé, l'agenda du jour, ou "
        "gérer un créneau. Dis-moi ce qu'il te faut.",
        "action": "general",
        "data": {},
    }


# ── Agenda du jour ────────────────────────────────────────────────────────────


async def _handle_agenda(db: AsyncSession, bid: UUID) -> dict:
    business = await db.get(Business, bid)
    tz = await _business_tz(db, business)
    today = datetime.now(tz).date()
    day_start = datetime(today.year, today.month, today.day, tzinfo=tz).astimezone(UTC)
    day_end = day_start + timedelta(days=1)
    rows = (
        await db.execute(
            select(Appointment, Customer.full_name)
            .outerjoin(Customer, Appointment.customer_id == Customer.id)
            .where(
                Appointment.business_id == bid,
                Appointment.status != "cancelled",
                Appointment.start_at >= day_start,
                Appointment.start_at < day_end,
            )
            .order_by(Appointment.start_at.asc())
        )
    ).all()
    if not rows:
        return {
            "response": "Aucun rendez-vous aujourd'hui — journée tranquille ! 🌿",
            "action": "agenda",
            "data": {"count": 0},
        }
    lines = ["Voici tes rendez-vous d'aujourd'hui 💇 :"]
    for a, name in rows:
        t = a.start_at.astimezone(tz).strftime("%Hh%M")
        label = "🚫 créneau bloqué" if a.status == "blocked" else f"{a.title} — {name or 'client'}"
        lines.append(f"• {t} : {label}")
    return {"response": "\n".join(lines), "action": "agenda", "data": {"count": len(rows)}}


# ── Annuler un rendez-vous ────────────────────────────────────────────────────


async def _handle_cancel(db: AsyncSession, bid: UUID, message: str) -> dict:
    now = datetime.now(UTC)
    appt = None
    m = _CLIENT_NAME_RE.search(message)
    if m:
        name = m.group(1).strip()
        appt = (
            await db.execute(
                select(Appointment)
                .join(Customer, Appointment.customer_id == Customer.id)
                .where(
                    Appointment.business_id == bid,
                    Appointment.status != "cancelled",
                    Appointment.start_at >= now,
                    Customer.full_name.ilike(f"%{name}%"),
                )
                .order_by(Appointment.start_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if appt is None:
        return {
            "response": "De quel rendez-vous parles-tu ? Donne-moi le nom du client "
            "(ex. « annule le rdv de Marie »).",
            "action": "cancel",
            "data": {"found": False},
        }
    appt.status = "cancelled"
    tz = await _business_tz(db, await db.get(Business, bid))
    when = appt.start_at.astimezone(tz).strftime("%d/%m à %Hh%M")
    # Créneau libéré → on prévient le 1er client en liste d'attente.
    from jenny.services.waitlist_service import notify_waitlist_for_freed_slot

    notified = await notify_waitlist_for_freed_slot(
        db, business_id=bid, service=appt.title, when_label=when
    )
    await db.commit()
    extra = (
        f" 📋 {notified.customer_name or 'Un client'} attendait ce créneau en liste "
        "d'attente — je te l'ai mis en notification pour le rappeler."
        if notified
        else " Le créneau est de nouveau libre pour d'autres clients."
    )
    return {
        "response": f"C'est annulé ✅ — le RDV « {appt.title} » du {when}.{extra}",
        "action": "cancel",
        "data": {
            "appointment_id": str(appt.id),
            "waitlist_notified": bool(notified),
        },
    }


# ── Déplacer un rendez-vous ───────────────────────────────────────────────────


async def _handle_move(db: AsyncSession, bid: UUID, message: str) -> dict:
    now = datetime.now(UTC)
    business = await db.get(Business, bid)
    tz = await _business_tz(db, business)
    appt = None
    m = _CLIENT_NAME_RE.search(message)
    if m:
        name = m.group(1).strip()
        appt = (
            await db.execute(
                select(Appointment)
                .join(Customer, Appointment.customer_id == Customer.id)
                .where(
                    Appointment.business_id == bid,
                    Appointment.status != "cancelled",
                    Appointment.start_at >= now,
                    Customer.full_name.ilike(f"%{name}%"),
                )
                .order_by(Appointment.start_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if appt is None:
        return {
            "response": "Quel rendez-vous veux-tu déplacer ? Donne-moi le nom du client "
            "(ex. « déplace le rdv de Marie à 16h »).",
            "action": "move",
            "data": {"found": False},
        }
    new_time = parse_fr_time(message)
    new_date = parse_fr_date(message, today=datetime.now(tz).date())
    if new_time is None and new_date is None:
        return {
            "response": "Vers quand veux-tu le déplacer ? (ex. « ...à 16h » ou « ...à jeudi »)",
            "action": "move",
            "data": {"need": "when"},
        }
    cur = appt.start_at.astimezone(tz)
    old_when = cur.strftime("%d/%m à %Hh%M")
    duration = appt.end_at - appt.start_at
    day = new_date or cur.date()
    hh = new_time.hour if new_time else cur.hour
    mm = new_time.minute if new_time else cur.minute
    new_local = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
    appt.start_at = new_local.astimezone(UTC)
    appt.end_at = appt.start_at + duration
    # L'ancien créneau se libère → on prévient la liste d'attente.
    from jenny.services.waitlist_service import notify_waitlist_for_freed_slot

    notified = await notify_waitlist_for_freed_slot(
        db, business_id=bid, service=appt.title, when_label=old_when
    )
    await db.commit()
    when = new_local.strftime("%d/%m à %Hh%M")
    extra = (
        f" 📋 J'ai prévenu {notified.customer_name or 'un client'} en liste d'attente "
        f"pour l'ancien créneau ({old_when})."
        if notified
        else ""
    )
    return {
        "response": f"C'est déplacé ✅ — le RDV « {appt.title} » est maintenant le {when}.{extra}",
        "action": "move",
        "data": {"appointment_id": str(appt.id), "waitlist_notified": bool(notified)},
    }


# ── Chiffre d'affaires estimé ─────────────────────────────────────────────────


async def _handle_revenue(db: AsyncSession, bid: UUID) -> dict:
    from jenny.services.prestation_service import _norm, load_active_prestations

    now = datetime.now(UTC)
    prestations = await load_active_prestations(db, bid)
    price_map = {_norm(p.name): p.price_cents for p in prestations if p.price_cents}
    titles = (
        await db.execute(
            select(Appointment.title).where(
                Appointment.business_id == bid,
                Appointment.status.in_(["scheduled", "confirmed"]),
                Appointment.start_at >= now,
            )
        )
    ).all()
    total_cents, matched = 0, 0
    for (title,) in titles:
        nt = _norm(title or "")
        cents = next((c for n, c in price_map.items() if n and (n in nt or nt in n)), None)
        if cents:
            total_cents += cents
            matched += 1
    eur = total_cents / 100
    if not titles:
        msg = "Aucun rendez-vous à venir pour l'instant — donc rien à estimer."
    else:
        msg = (
            f"Sur tes {len(titles)} rendez-vous à venir, j'estime environ {eur:.0f}€ "
            f"({matched} prestations reconnues dans ton catalogue). "
            "C'est une estimation basée sur tes tarifs."
        )
    return {
        "response": msg,
        "action": "revenue",
        "data": {"estimate_eur": eur, "appointments": len(titles), "matched": matched},
    }


async def _handle_top_prestations(db: AsyncSession, bid: UUID) -> dict:
    """Prestation la plus demandée : agrégation RÉELLE de l'historique des RDV
    (rapprochés du catalogue), au lieu d'une réponse LLM vague."""
    from collections import Counter

    from jenny.services.prestation_service import _norm, load_active_prestations

    prestations = await load_active_prestations(db, bid)
    norm_names = {_norm(p.name): p.name for p in prestations}
    rows = (
        await db.execute(
            select(Appointment.title).where(
                Appointment.business_id == bid,
                Appointment.status.notin_(["cancelled", "blocked"]),
            )
        )
    ).all()
    counts: Counter[str] = Counter()
    for (title,) in rows:
        nt = _norm(title or "")
        match = next((orig for n, orig in norm_names.items() if n and (n in nt or nt in n)), None)
        if match:
            counts[match] += 1

    if not counts:
        return {
            "response": (
                "Pas encore assez de rendez-vous rattachés à une prestation pour "
                "dégager une tendance — reviens me voir quand l'agenda se remplit !"
            ),
            "action": "top_prestations",
            "data": {"top": []},
        }
    top = counts.most_common(3)
    lead_name, lead_n = top[0]
    detail = ", ".join(f"{name} ({n})" for name, n in top)
    msg = (
        f"Ta prestation la plus demandée, c'est {lead_name} — {lead_n} rendez-vous. "
        f"Ton trio de tête : {detail}."
    )
    return {
        "response": msg,
        "action": "top_prestations",
        "data": {"top": [{"name": n, "count": c} for n, c in top]},
    }


# ── Recherche client + historique (#95) ──────────────────────────────────────


async def _handle_client_history(db: AsyncSession, bid: UUID, message: str) -> dict:
    from jenny.services.learning_service import load_customer_facts
    from jenny.services.loyalty_service import compute_loyalty

    business = await db.get(Business, bid)
    tz = await _business_tz(db, business)
    now = datetime.now(UTC)

    # Recherche par téléphone, sinon par nom.
    cust = None
    pm = _PHONE_RE.search(message)
    if pm:
        digits = re.sub(r"\D", "", pm.group())
        if len(digits) >= 8:
            cust = (
                await db.execute(
                    select(Customer)
                    .where(Customer.business_id == bid, Customer.phone.ilike(f"%{digits[-8:]}%"))
                    .limit(1)
                )
            ).scalar_one_or_none()
    if cust is None:
        nm = _CLIENT_NAME_RE.search(message)
        if nm:
            name = nm.group(1).strip()
            cust = (
                await db.execute(
                    select(Customer)
                    .where(Customer.business_id == bid, Customer.full_name.ilike(f"%{name}%"))
                    .order_by(Customer.last_seen_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
    if cust is None:
        return {
            "response": "De quel client veux-tu l'historique ? Donne-moi son nom "
            "(ex. « historique de Marie ») ou son numéro.",
            "action": "client_history",
            "data": {"found": False},
        }

    appts = (
        await db.execute(
            select(Appointment)
            .where(
                Appointment.business_id == bid,
                Appointment.customer_id == cust.id,
                Appointment.status != "blocked",
            )
            .order_by(Appointment.start_at.desc())
            .limit(20)
        )
    ).scalars().all()
    loyalty = await compute_loyalty(db, business, cust.id)
    facts = await load_customer_facts(db, bid, cust.id)

    def _aw(dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    upcoming = [a for a in appts if _aw(a.start_at) >= now and a.status != "cancelled"]
    past = [a for a in appts if _aw(a.start_at) < now]

    lines = [f"📇 {cust.full_name or cust.phone or 'Client'} :"]
    reward = " — récompense fidélité débloquée 🎁" if loyalty["reward_ready"] else ""
    lines.append(f"• {loyalty['points']} RDV honorés{reward}")
    if upcoming:
        a = upcoming[-1]
        loc = _aw(a.start_at).astimezone(tz)
        lines.append(f"• Prochain : {a.title} le {loc:%d/%m à %Hh%M}")
    if past:
        a = past[0]
        loc = _aw(a.start_at).astimezone(tz)
        lines.append(f"• Dernier : {a.title} le {loc:%d/%m}")
    if facts:
        lines.append("• À retenir : " + " ; ".join(facts[:3]))
    return {
        "response": "\n".join(lines),
        "action": "client_history",
        "data": {"found": True, "customer_id": str(cust.id), "points": loyalty["points"]},
    }


async def handle_owner_message(
    db: AsyncSession, *, business_id: UUID, actor: str, message: str
) -> dict:
    """Point d'entrée : route le message du gérant vers la bonne action."""
    intent = detect_owner_intent(message)
    logger.info("owner.message", business_id=str(business_id), intent=intent)
    handlers = {
        "add_knowledge": lambda: _handle_add_knowledge(db, business_id, message),
        "cancel": lambda: _handle_cancel(db, business_id, message),
        "move": lambda: _handle_move(db, business_id, message),
        "block_slot": lambda: _handle_block(db, business_id, actor, message),
        "revenue": lambda: _handle_revenue(db, business_id),
        "top_prestations": lambda: _handle_top_prestations(db, business_id),
        "agenda": lambda: _handle_agenda(db, business_id),
        "report": lambda: _handle_report(db, business_id),
        "client_history": lambda: _handle_client_history(db, business_id, message),
    }
    return await handlers.get(intent, lambda: _handle_general(db, business_id, message))()
