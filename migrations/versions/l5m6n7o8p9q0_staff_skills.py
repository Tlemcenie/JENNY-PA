"""Coiffeurs : drapeau explicite « sait tout faire ».

Avant, aucune compétence = sait tout faire. Supprimer la dernière prestation
d'un coiffeur (CASCADE sur staff_skills) le rendait polyvalent en silence.
Rempli à true sans compétence, false sinon.

Revision ID: jen_staffsk_l5m6
Revises: jen_campaigns_k4l5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "jen_staffsk_l5m6"
down_revision: str | None = "jen_campaigns_k4l5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# rejouable : remplissage au 1er ajout seulement
UPGRADE_PG = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'staff' AND column_name = 'all_services'
    ) THEN
        ALTER TABLE staff ADD COLUMN all_services boolean NOT NULL DEFAULT true;
        UPDATE staff SET all_services = false
        WHERE EXISTS (SELECT 1 FROM staff_skills k WHERE k.staff_id = staff.id);
    END IF;
END
$$;
"""

DOWNGRADE_PG = "ALTER TABLE staff DROP COLUMN IF EXISTS all_services"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(UPGRADE_PG)
        return
    # hors Postgres : même chose
    insp = sa.inspect(bind)
    if "all_services" in {c["name"] for c in insp.get_columns("staff")}:
        return
    op.add_column(
        "staff",
        sa.Column("all_services", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.execute(
        "UPDATE staff SET all_services = 0 "
        "WHERE EXISTS (SELECT 1 FROM staff_skills k WHERE k.staff_id = staff.id)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(DOWNGRADE_PG)
        return
    insp = sa.inspect(bind)
    if "all_services" in {c["name"] for c in insp.get_columns("staff")}:
        with op.batch_alter_table("staff") as batch:
            batch.drop_column("all_services")
