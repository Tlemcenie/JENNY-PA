"""Créneaux libérés dans une session (annulation, déplacement, suppression).

Les crochets liste d'attente ne reçoivent qu'un texte « mardi à 14h00 ».
Pour tracer l'offre, il faut l'heure exacte : on la lit dans la session,
avant le flush (l'historique SQLAlchemy y est encore complet).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from jenny.domain.models.appointment import Appointment

if TYPE_CHECKING:
    from uuid import UUID

_KEY = "jenny_freed_slots"
# n'occupe pas l'agenda
_FREE = ("cancelled",)


def _value(state: Any, key: str, *, old: bool) -> Any:
    """Valeur avant/après, sans recharger."""
    h = state.attrs[key].history
    if old and h.deleted:
        return h.deleted[0]
    if not old and h.added:
        return h.added[0]
    return h.unchanged[0] if h.unchanged else None


def freed_slot(obj: Appointment, *, deleted: bool = False) -> tuple[datetime, int] | None:
    """(début, minutes) libéré par ce RDV."""
    st = inspect(obj)
    old_status = _value(st, "status", old=True)
    if old_status in _FREE:
        return None
    start = _value(st, "start_at", old=True)
    end = _value(st, "end_at", old=True)
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None
    new_status = _value(st, "status", old=False)
    moved = bool(st.attrs.start_at.history.deleted)
    if not (deleted or moved or new_status in _FREE):
        return None
    minutes = max(5, int((end - start).total_seconds() // 60))
    return start, minutes


def _sync(db: Any) -> Session:
    """Session synchrone sous-jacente."""
    return getattr(db, "sync_session", db)


def _scan(session: Session) -> list[tuple[UUID, datetime, int]]:
    """RDV libérés pas encore flushés."""
    out = []
    for obj in list(session.dirty) + list(session.deleted):
        if not isinstance(obj, Appointment):
            continue
        slot = freed_slot(obj, deleted=obj in session.deleted)
        if slot is not None:
            out.append((obj.business_id, *slot))
    return out


@event.listens_for(Session, "before_flush")
def _track(session: Session, _ctx: Any, _instances: Any) -> None:
    """Garde la trace avant le flush."""
    found = _scan(session)
    if found:
        session.info.setdefault(_KEY, []).extend(found)


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_soft_rollback")
def _reset(session: Session, *_args: Any) -> None:
    """Fin de transaction : on oublie."""
    session.info.pop(_KEY, None)


def take_freed_slot(db: Any, business_id: UUID) -> tuple[datetime, int] | None:
    """Dernier créneau libéré du salon."""
    session = _sync(db)
    pending = [s for s in _scan(session) if s[0] == business_id]
    if pending:
        _bid, start, minutes = pending[-1]
        return start, minutes
    seen = session.info.get(_KEY) or []
    for i in range(len(seen) - 1, -1, -1):
        if seen[i][0] == business_id:
            _bid, start, minutes = seen.pop(i)
            return start, minutes
    return None


__all__ = ["freed_slot", "take_freed_slot"]
