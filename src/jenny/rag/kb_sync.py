"""KB réelle remise à jour après un changement du salon.

Après le commit (horaires, acompte, rappels, contact, équipe, prix),
nos fiches (tag kb_coiffeur_reel) sont resynchronisées en fond.
Fiches du gérant intactes. Rien hors Postgres ou sans seed.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from jenny.core.logging import get_logger
from jenny.domain.models.business import Business
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.staff import Staff

logger = get_logger(__name__)

# champs lus par les fiches
BUSINESS_FIELDS = (
    "business_hours",
    "deposit_enabled",
    "deposit_percent",
    "deposit_min_cents",
    "reminder_lead_minutes",
    "day_reminder_lead_hours",
    "loyalty_threshold",
    "email",
    "phone",
    "description",
)
STAFF_FIELDS = ("display_name", "is_active", "business_id")
PRESTATION_FIELDS = ("name", "price_cents", "duration_minutes", "is_active", "description")
# regroupe les commits proches
DELAY_S = 1.0

_KEY = "jenny_kb_refresh"
_pending: dict[UUID, asyncio.Task] = {}
# changement pendant une passe
_again: set[UUID] = set()


def _history(obj: Any, field: str):
    return inspect(obj).attrs[field].history


def _changed(obj: Any, fields: tuple[str, ...]) -> bool:
    return any(_history(obj, f).has_changes() for f in fields)


def _ids(values) -> set[UUID]:
    return {v for v in values if isinstance(v, UUID)}


def touched_businesses(session: Session) -> set[UUID]:
    """Salons dont un fait change."""
    out: set[UUID] = set()
    for obj in session.dirty:
        if isinstance(obj, Business) and _changed(obj, BUSINESS_FIELDS):
            out |= _ids([inspect(obj).dict.get("id")])
        elif isinstance(obj, Staff) and _changed(obj, STAFF_FIELDS):
            moved = _history(obj, "business_id")
            # ancien et nouveau salon
            out |= _ids([inspect(obj).dict.get("business_id"), *moved.deleted])
        elif isinstance(obj, Prestation) and _changed(obj, PRESTATION_FIELDS):
            out |= _ids([inspect(obj).dict.get("business_id")])
    for obj in [*session.new, *session.deleted]:
        if isinstance(obj, (Staff, Prestation)):
            out |= _ids([inspect(obj).dict.get("business_id")])
    return out


@event.listens_for(Session, "before_flush")
def _track(session: Session, _ctx: Any, _instances: Any) -> None:
    """Note les salons touchés."""
    found = touched_businesses(session)
    if found:
        session.info.setdefault(_KEY, set()).update(found)


@event.listens_for(Session, "after_soft_rollback")
def _forget(session: Session, previous: Any) -> None:
    """Rollback complet : on oublie."""
    if getattr(previous, "parent", None) is None:
        session.info.pop(_KEY, None)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    """Commit final : synchro en fond."""
    if session.in_nested_transaction():
        # savepoint : on attend
        return
    found = session.info.pop(_KEY, None)
    if not found or not _app_engine(session):
        return
    for business_id in found:
        _launch(business_id)


def _app_engine(session: Session) -> bool:
    """Postgres de l'appli ?"""
    try:
        bind = session.get_bind()
    except Exception:
        return False
    if bind.dialect.name != "postgresql":
        return False
    from jenny.db.session import engine

    # même base que la tâche
    return bind.url == engine.sync_engine.url


def _launch(business_id: UUID) -> bool:
    """Une tâche par salon."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    task = _pending.get(business_id)
    if task is not None and not task.done() and task.get_loop() is loop:
        # elle repassera
        _again.add(business_id)
        return True
    _pending[business_id] = loop.create_task(_run_soon(business_id))
    return True


async def _run_soon(business_id: UUID) -> None:
    try:
        await asyncio.sleep(DELAY_S)
        while True:
            _again.discard(business_id)
            await run_refresh(business_id)
            if business_id not in _again:
                break
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # jamais bloquant
        logger.warning("kb_sync.failed", business_id=str(business_id), error=str(exc))
    finally:
        if _pending.get(business_id) is asyncio.current_task():
            _pending.pop(business_id, None)
            _again.discard(business_id)


async def run_refresh(business_id: UUID) -> dict | None:
    """Remet à jour nos fiches du salon."""
    from jenny.db.session import async_session_factory
    from jenny.rag.kb_coiffeur import refresh_real_entries

    async with async_session_factory() as session:
        try:
            stats = await refresh_real_entries(session, business_id)
        except LookupError:
            # salon supprimé entre-temps
            return None
    if stats is not None:
        logger.info("kb_sync.refreshed", business_id=str(business_id), **stats)
    return stats


async def wait_idle() -> None:
    """Attend les synchros en cours."""
    loop = asyncio.get_running_loop()
    while True:
        tasks = [t for t in _pending.values() if t.get_loop() is loop and not t.done()]
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)


__all__ = ["run_refresh", "touched_businesses", "wait_idle"]
