"""initial_schema — Schéma complet Jenny.

Crée toutes les tables de la base de données Jenny :
- businesses : comptes business (freelances, PME, commerces)
- customers : profils clients multicanaux
- conversations : fils de discussion
- messages : messages entrants/sortants avec champs ML
- message_events : audit trail du cycle de vie

Revision ID: 3d09b043955c
Revises:
Create Date: 2026-03-15 19:02:36.236665
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID, ARRAY

revision: str = "3d09b043955c"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extension pgvector ──
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── businesses ──
    op.create_table(
        "businesses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False, comment="Nom du business"),
        sa.Column("slug", sa.String(100), unique=True, nullable=False, comment="Identifiant URL-friendly"),
        sa.Column("email", sa.String(255), nullable=True, comment="Email principal"),
        sa.Column("is_active", sa.Boolean(), server_default="true", comment="Business actif"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── customers ──
    op.create_table(
        "customers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("business_id", UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True, index=True),
        sa.Column("phone", sa.String(50), nullable=True, index=True),
        sa.Column("instagram_handle", sa.String(100), nullable=True),
        sa.Column("messenger_id", sa.String(255), nullable=True),
        sa.Column("tags", ARRAY(sa.String), nullable=True, comment="Tags métier libres"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── conversations ──
    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("business_id", UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("channel", sa.String(50), nullable=False, comment="Canal de la conversation"),
        sa.Column("status", sa.String(30), server_default="open", nullable=False, comment="open, closed, archived, escalated"),
        sa.Column("current_intent", sa.String(100), nullable=True, comment="Dernière intention détectée"),
        sa.Column("message_count", sa.Integer(), server_default="0"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_escalated", sa.Boolean(), server_default="false"),
        sa.Column("assigned_to", sa.String(255), nullable=True, comment="Conseiller humain assigné"),
        sa.Column("summary", sa.Text(), nullable=True, comment="Résumé de la conversation (LLM)"),
        sa.Column("tags", JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── messages ──
    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("business_id", UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        # Identification
        sa.Column("external_message_id", sa.String(512), nullable=False, index=True, comment="ID côté canal source"),
        sa.Column("channel", sa.String(50), nullable=False, comment="instagram, whatsapp, messenger, email, form"),
        sa.Column("direction", sa.String(10), server_default="inbound", nullable=False, comment="inbound ou outbound"),
        # Expéditeur
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column("sender_email", sa.String(255), nullable=True),
        sa.Column("sender_phone", sa.String(50), nullable=True),
        sa.Column("sender_handle", sa.String(100), nullable=True),
        # Contenu
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=False, comment="Contenu texte brut"),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("cleaned_text", sa.Text(), nullable=True, comment="Texte nettoyé post-normalisation"),
        sa.Column("language", sa.String(10), nullable=True, comment="Langue ISO 639-1"),
        # Pièces jointes
        sa.Column("has_attachments", sa.Boolean(), server_default="false"),
        sa.Column("attachment_count", sa.Integer(), server_default="0"),
        sa.Column("attachments_meta", JSON(), nullable=True),
        # Statut
        sa.Column("status", sa.String(30), server_default="received", nullable=False),
        # ML signals
        sa.Column("priority", sa.Integer(), nullable=True, comment="Score priorité 1-10 (ML)"),
        sa.Column("category", sa.String(100), nullable=True, comment="Catégorie (ML)"),
        sa.Column("intent_label", sa.String(100), nullable=True, comment="Intent détecté (ML)"),
        sa.Column("sentiment_score", sa.Float(), nullable=True, comment="Sentiment -1.0 à 1.0"),
        sa.Column("urgency_flag", sa.Boolean(), server_default="false", comment="Urgence détectée"),
        # Timestamps source
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=True),
        # Metadata
        sa.Column("raw_metadata", JSON(), nullable=True, comment="Payload brut original"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── message_events (audit trail) ──
    op.create_table(
        "message_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("event_type", sa.String(50), nullable=False, comment="ingested, normalized, classified, etc."),
        sa.Column("status", sa.String(30), server_default="success", nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("payload", JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── Table RAG embeddings ──
    op.create_table(
        "document_embeddings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("business_id", UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("content", sa.Text(), nullable=False, comment="Texte du chunk"),
        sa.Column("source", sa.String(500), nullable=True, comment="Source du document"),
        sa.Column("chunk_index", sa.Integer(), nullable=True, comment="Index dans le document"),
        sa.Column("metadata_", JSON(), nullable=True, comment="Métadonnées additionnelles"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Colonne vector (pgvector) — ajoutée séparément car type custom
    op.execute(
        "ALTER TABLE document_embeddings ADD COLUMN embedding vector(384)"
    )

    # ── Index pour la recherche vectorielle ──
    op.execute(
        "CREATE INDEX idx_document_embeddings_embedding "
        "ON document_embeddings USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_table("message_events")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("customers")
    op.drop_table("businesses")
    op.drop_table("document_embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")
