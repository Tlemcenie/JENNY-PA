"""Perf : index composites sur appointments (requêtes chaudes à l'échelle).

Revision ID: jen_perfidx_c9d0
Revises: jen_salon2_b8c9
Create Date: 2026-06-15 14:30:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "jen_perfidx_c9d0"
down_revision: Union[str, None] = "jen_salon2_b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_appointments_business_start", "appointments", ["business_id", "start_at"]
    )
    op.create_index(
        "ix_appointments_business_customer", "appointments", ["business_id", "customer_id"]
    )
    op.create_index(
        "ix_appointments_business_status", "appointments", ["business_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_appointments_business_status", table_name="appointments")
    op.drop_index("ix_appointments_business_customer", table_name="appointments")
    op.drop_index("ix_appointments_business_start", table_name="appointments")
