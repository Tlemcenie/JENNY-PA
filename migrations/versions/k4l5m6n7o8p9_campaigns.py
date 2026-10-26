"""Relances : plafond anti-spam client, campagnes, offres de créneaux.

- customers : last_offer_at, offer_window_start/count, marketing_opt_out_at
- campaigns + campaign_recipients : envoi et attribution
- slot_offers : chaque créneau libre proposé (jamais 2 fois au même client)

Revision ID: jen_campaigns_k4l5
Revises: jen_staff_j3k4
"""

from typing import Union

from alembic import op

revision: str = "jen_campaigns_k4l5"
down_revision: Union[str, None] = "jen_staff_j3k4"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_UPGRADE = [
    # plafond anti-spam
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS last_offer_at TIMESTAMPTZ",
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS offer_window_start TIMESTAMPTZ",
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS offer_window_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS marketing_opt_out_at TIMESTAMPTZ",
    # campagnes
    """
    CREATE TABLE IF NOT EXISTS campaigns (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
        segment VARCHAR(40) NOT NULL,
        message TEXT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'sending',
        target_count INTEGER NOT NULL DEFAULT 0,
        sent_count INTEGER NOT NULL DEFAULT 0,
        skipped_count INTEGER NOT NULL DEFAULT 0,
        created_by VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_campaigns_business_id ON campaigns (business_id)",
    """
    CREATE TABLE IF NOT EXISTS campaign_recipients (
        campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
        sent_at TIMESTAMPTZ NOT NULL,
        channel VARCHAR(20),
        PRIMARY KEY (campaign_id, customer_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_campaign_recipients_customer_id "
    "ON campaign_recipients (customer_id)",
    # offres de créneaux
    """
    CREATE TABLE IF NOT EXISTS slot_offers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
        customer_id UUID REFERENCES customers(id) ON DELETE CASCADE,
        conversation_id UUID,
        waitlist_entry_id UUID,
        recipient_key VARCHAR(80) NOT NULL,
        slot_start TIMESTAMPTZ NOT NULL,
        duration_minutes INTEGER NOT NULL DEFAULT 30,
        service VARCHAR(120),
        source VARCHAR(20) NOT NULL,
        reason VARCHAR(20) NOT NULL DEFAULT 'matin',
        channel VARCHAR(20),
        sent_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_slot_offers_recipient_slot UNIQUE (business_id, recipient_key, slot_start)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_slot_offers_business_id ON slot_offers (business_id)",
    "CREATE INDEX IF NOT EXISTS ix_slot_offers_customer_id ON slot_offers (customer_id)",
    "CREATE INDEX IF NOT EXISTS ix_slot_offers_business_slot "
    "ON slot_offers (business_id, slot_start)",
]

_DOWNGRADE = [
    "DROP TABLE IF EXISTS slot_offers",
    "DROP TABLE IF EXISTS campaign_recipients",
    "DROP TABLE IF EXISTS campaigns",
    "ALTER TABLE customers DROP COLUMN IF EXISTS marketing_opt_out_at",
    "ALTER TABLE customers DROP COLUMN IF EXISTS offer_window_count",
    "ALTER TABLE customers DROP COLUMN IF EXISTS offer_window_start",
    "ALTER TABLE customers DROP COLUMN IF EXISTS last_offer_at",
]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQL Postgres (IF NOT EXISTS)
    for sql in _UPGRADE:
        op.execute(sql)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for sql in _DOWNGRADE:
        op.execute(sql)
