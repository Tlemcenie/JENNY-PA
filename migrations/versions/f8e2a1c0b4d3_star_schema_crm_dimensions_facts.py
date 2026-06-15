"""Schéma « étoile » CRM — dimensions + faits.

Ajoute des tables de dimension (référentiels) et de fait (commandes,
transactions financières, documents clients, adresses) pour tracer
clients, pièces jointes métier, et mouvements monétaires.

Revision ID: f8e2a1c0b4d3
Revises: 3d09b043955c
Create Date: 2026-04-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "f8e2a1c0b4d3"
down_revision: Union[str, None] = "3d09b043955c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Dimensions ──
    op.create_table(
        "document_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "transaction_types",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── Adresses (dimension client, cardinalité N) ──
    op.create_table(
        "customer_addresses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "business_id",
            UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("label", sa.String(100), nullable=True, comment="billing, shipping, home"),
        sa.Column("line1", sa.String(255), nullable=False),
        sa.Column("line2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(120), nullable=True),
        sa.Column("region", sa.String(120), nullable=True),
        sa.Column("postal_code", sa.String(32), nullable=True),
        sa.Column("country", sa.String(2), nullable=True, comment="ISO 3166-1 alpha-2"),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── Commandes (fait / en-tête commande) ──
    op.create_table(
        "orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "business_id",
            UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("reference", sa.String(120), nullable=True, comment="Référence métier unique par business"),
        sa.Column("status", sa.String(40), server_default="draft", nullable=False),
        sa.Column("currency", sa.String(3), server_default="EUR", nullable=False),
        sa.Column("total_amount_minor", sa.BigInteger(), nullable=True, comment="Montant total en plus petite unité"),
        sa.Column("tax_amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("metadata_", JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_orders_business_reference",
        "orders",
        ["business_id", "reference"],
        unique=True,
        postgresql_where=sa.text("reference IS NOT NULL"),
    )

    # ── Transactions financières (fait) ──
    op.create_table(
        "customer_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "business_id",
            UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "order_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "transaction_type_id",
            sa.Integer(),
            sa.ForeignKey("transaction_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="EUR", nullable=False),
        sa.Column("status", sa.String(40), server_default="pending", nullable=False),
        sa.Column("provider", sa.String(40), nullable=True, comment="stripe, paypal, manual, …"),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata_", JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_customer_transactions_provider_external",
        "customer_transactions",
        ["provider", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL AND provider IS NOT NULL"),
    )
    op.create_index(
        "ix_customer_transactions_business_occurred",
        "customer_transactions",
        ["business_id", "occurred_at"],
    )

    # ── Documents clients (fait document + lien dimension catégorie) ──
    op.create_table(
        "customer_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "business_id",
            UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("document_categories.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("storage_uri", sa.Text(), nullable=False, comment="S3, chemin local, ou URL signée"),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("metadata_", JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── Tickets support (fait léger) ──
    op.create_table(
        "support_tickets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "business_id",
            UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("status", sa.String(40), server_default="open", nullable=False),
        sa.Column("priority", sa.String(20), server_default="normal", nullable=False),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("metadata_", JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_support_tickets_business_reference",
        "support_tickets",
        ["business_id", "reference"],
        unique=True,
        postgresql_where=sa.text("reference IS NOT NULL"),
    )

    # ── Graines dimensions ──
    op.execute(
        """
        INSERT INTO document_categories (code, label) VALUES
            ('invoice', 'Facture'),
            ('contract', 'Contrat'),
            ('identity', 'Pièce d''identité'),
            ('quote', 'Devis'),
            ('other', 'Autre')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO transaction_types (code, label) VALUES
            ('payment', 'Paiement'),
            ('refund', 'Remboursement'),
            ('chargeback', 'Rétrofacturation'),
            ('adjustment', 'Ajustement'),
            ('fee', 'Frais')
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("support_tickets")
    op.drop_table("customer_documents")
    op.drop_index("ix_customer_transactions_business_occurred", table_name="customer_transactions")
    op.drop_index("ix_customer_transactions_provider_external", table_name="customer_transactions")
    op.drop_table("customer_transactions")
    op.drop_index("ix_orders_business_reference", table_name="orders")
    op.drop_table("orders")
    op.drop_table("customer_addresses")
    op.drop_table("transaction_types")
    op.drop_table("document_categories")
