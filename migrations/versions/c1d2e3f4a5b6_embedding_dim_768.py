"""embedding_dim_768 — Aligne la dimension des embeddings RAG sur 768.

Le backend d'embeddings par défaut est Ollama `nomic-embed-text` (768-dim).
La colonne `document_embeddings.embedding` était en vector(384) : on la
recrée en vector(768) et on reconstruit l'index ivfflat. La table ne
contient que des données de test (recréation de la colonne sans perte utile).

Revision ID: c1d2e3f4a5b6
Revises: a7f3b2d1e9c8
Create Date: 2026-06-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "a7f3b2d1e9c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_document_embeddings_embedding")
    op.execute("ALTER TABLE document_embeddings DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE document_embeddings ADD COLUMN embedding vector(768)")
    op.execute(
        "CREATE INDEX idx_document_embeddings_embedding "
        "ON document_embeddings USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_document_embeddings_embedding")
    op.execute("ALTER TABLE document_embeddings DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE document_embeddings ADD COLUMN embedding vector(384)")
    op.execute(
        "CREATE INDEX idx_document_embeddings_embedding "
        "ON document_embeddings USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )
