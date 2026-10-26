"""Coiffeurs : tables staff + staff_skills, RDV posé sur un coiffeur.

La contrainte anti-chevauchement passe par ressource : deux RDV peuvent tomber
à la même heure s'ils sont chez deux coiffeurs différents. Un RDV sans coiffeur
compte comme le fauteuil unique d'avant (même comportement qu'avant).

Le downgrade remet la contrainte par salon : il échoue si des RDV de coiffeurs
différents se chevauchent déjà (normal, l'ancien modèle ne sait pas les tenir).

Revision ID: jen_staff_j3k4
Revises: jen_nooverlap_g1h2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "jen_staff_j3k4"
down_revision: Union[str, None] = "jen_nooverlap_g1h2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NO_OVERLAP = "appointments_no_overlap"
_IDX = "ix_appointments_business_staff_start"
_ZERO = "'00000000-0000-0000-0000-000000000000'::uuid"

# SQL Postgres, rejouable sans casse
UPGRADE_PG = [
    """CREATE TABLE IF NOT EXISTS staff (
        id uuid PRIMARY KEY,
        business_id uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
        display_name varchar(120) NOT NULL,
        color varchar(20),
        is_active boolean NOT NULL DEFAULT true,
        working_hours json,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_staff_business_id ON staff (business_id)",
    """CREATE TABLE IF NOT EXISTS staff_skills (
        staff_id uuid NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
        prestation_id uuid NOT NULL REFERENCES prestations(id) ON DELETE CASCADE,
        PRIMARY KEY (staff_id, prestation_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_staff_skills_prestation_id ON staff_skills (prestation_id)",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS staff_id uuid "
    "REFERENCES staff(id) ON DELETE SET NULL",
    f"CREATE INDEX IF NOT EXISTS {_IDX} ON appointments (business_id, staff_id, start_at)",
    "CREATE EXTENSION IF NOT EXISTS btree_gist",
    f"ALTER TABLE appointments DROP CONSTRAINT IF EXISTS {_NO_OVERLAP}",
    f"ALTER TABLE appointments ADD CONSTRAINT {_NO_OVERLAP} "
    "EXCLUDE USING gist ("
    "  business_id WITH =, "
    f"  (coalesce(staff_id, {_ZERO})) WITH =, "
    "  tstzrange(start_at, end_at, '[)') WITH &&"
    ") WHERE (status <> 'cancelled')",
]

DOWNGRADE_PG = [
    f"ALTER TABLE appointments DROP CONSTRAINT IF EXISTS {_NO_OVERLAP}",
    f"ALTER TABLE appointments ADD CONSTRAINT {_NO_OVERLAP} "
    "EXCLUDE USING gist ("
    "  business_id WITH =, "
    "  tstzrange(start_at, end_at, '[)') WITH &&"
    ") WHERE (status <> 'cancelled')",
    f"DROP INDEX IF EXISTS {_IDX}",
    "ALTER TABLE appointments DROP COLUMN IF EXISTS staff_id",
    "DROP TABLE IF EXISTS staff_skills",
    "DROP TABLE IF EXISTS staff",
]


def _upgrade_generic() -> None:
    """Même schéma hors Postgres (sans gist)."""
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("staff"):
        op.create_table(
            "staff",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "business_id",
                UUID(as_uuid=True),
                sa.ForeignKey("businesses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("display_name", sa.String(120), nullable=False),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("working_hours", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_staff_business_id", "staff", ["business_id"])
    if not insp.has_table("staff_skills"):
        op.create_table(
            "staff_skills",
            sa.Column(
                "staff_id",
                UUID(as_uuid=True),
                sa.ForeignKey("staff.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "prestation_id",
                UUID(as_uuid=True),
                sa.ForeignKey("prestations.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )
        op.create_index("ix_staff_skills_prestation_id", "staff_skills", ["prestation_id"])
    if "staff_id" not in {c["name"] for c in insp.get_columns("appointments")}:
        op.add_column("appointments", sa.Column("staff_id", UUID(as_uuid=True), nullable=True))
    if _IDX not in {i["name"] for i in insp.get_indexes("appointments")}:
        op.create_index(_IDX, "appointments", ["business_id", "staff_id", "start_at"])


def _downgrade_generic() -> None:
    """Défait le schéma hors Postgres."""
    insp = sa.inspect(op.get_bind())
    if _IDX in {i["name"] for i in insp.get_indexes("appointments")}:
        op.drop_index(_IDX, table_name="appointments")
    if "staff_id" in {c["name"] for c in insp.get_columns("appointments")}:
        with op.batch_alter_table("appointments") as batch:
            batch.drop_column("staff_id")
    if insp.has_table("staff_skills"):
        op.drop_table("staff_skills")
    if insp.has_table("staff"):
        op.drop_table("staff")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        _upgrade_generic()
        return
    for stmt in UPGRADE_PG:
        op.execute(stmt)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        _downgrade_generic()
        return
    for stmt in DOWNGRADE_PG:
        op.execute(stmt)
