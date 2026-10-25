"""Détection des conflits d'agenda remontés par Postgres.

La contrainte `appointments_no_overlap` (migration jen_nooverlap_g1h2) rend la
double réservation impossible. Quand deux demandes arrivent en même temps, la
seconde reçoit une IntegrityError : on la traduit en « créneau déjà pris »
plutôt qu'en erreur technique.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

_NOM_CONTRAINTE = "appointments_no_overlap"


def is_slot_taken(exc: BaseException) -> bool:
    """L'erreur vient-elle du chevauchement de créneaux ?"""
    if not isinstance(exc, IntegrityError):
        return False
    return _NOM_CONTRAINTE in str(getattr(exc, "orig", exc))
