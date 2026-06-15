"""Fidélité client : points = rendez-vous honorés, récompense au seuil configuré."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from jenny.domain.models.appointment import Appointment

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from jenny.domain.models.business import Business


async def compute_loyalty(
    db: AsyncSession, business: Business, customer_id: UUID
) -> dict:
    """Points de fidélité d'un client + état de la récompense.

    Points = nombre de RDV honorés (confirmés/terminés, passés). Récompense
    débloquée quand points ≥ ``business.loyalty_threshold`` (0 = fidélité désactivée).
    """
    points = int(
        (
            await db.execute(
                select(func.count(Appointment.id)).where(
                    Appointment.business_id == business.id,
                    Appointment.customer_id == customer_id,
                    Appointment.status.in_(["completed", "confirmed"]),
                    Appointment.start_at < datetime.now(UTC),
                )
            )
        ).scalar_one()
        or 0
    )
    threshold = int(getattr(business, "loyalty_threshold", 0) or 0)
    reward_ready = bool(threshold and points >= threshold)
    return {
        "points": points,
        "threshold": threshold,
        "reward_ready": reward_ready,
        "remaining": max(0, threshold - points) if threshold else None,
    }
