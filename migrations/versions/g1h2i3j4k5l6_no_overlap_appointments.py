"""Rend la double réservation impossible en base.

Avant : chaque chemin de réservation faisait un SELECT de chevauchement puis un
INSERT, séparés par plusieurs `await`. Deux demandes simultanées passaient donc
toutes les deux — le mono-worker n'y change rien, asyncio entrelace sur chaque
attente. Ici c'est Postgres qui refuse : la course n'existe plus.

Le créneau « blocked » bloque aussi (c'est son rôle) ; seul « cancelled » libère.
Quand les coiffeurs arriveront, la contrainte devra inclure `staff_id`.

Revision ID: jen_nooverlap_g1h2
Revises: jen_msgfeedback_a1b2
"""

from typing import Union

from alembic import op

revision: str = "jen_nooverlap_g1h2"
down_revision: Union[str, None] = "jen_msgfeedback_a1b2"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_NO_OVERLAP = "appointments_no_overlap"
_END_AFTER = "appointments_end_after_start"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # gist/exclude : Postgres uniquement

    # un RDV finit après avoir commencé
    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {_END_AFTER} "
        "CHECK (end_at > start_at) NOT VALID"
    )
    # pour mélanger égalité (uuid) et plage dans un même index gist
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {_NO_OVERLAP} "
        "EXCLUDE USING gist ("
        "  business_id WITH =, "
        "  tstzrange(start_at, end_at, '[)') WITH &&"
        ") WHERE (status <> 'cancelled')"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE appointments DROP CONSTRAINT IF EXISTS {_NO_OVERLAP}")
    op.execute(f"ALTER TABLE appointments DROP CONSTRAINT IF EXISTS {_END_AFTER}")
