"""RAG : index HNSW + texte intégral français (idempotente).

Revision ID: jen_raghnsw_h1i2
Revises: jen_nooverlap_g1h2
"""

from typing import Union

from alembic import op

revision: str = "jen_raghnsw_h1i2"
down_revision: Union[str, None] = "jen_nooverlap_g1h2"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_TS_CONFIG = "jenny_fr"
_HNSW = "ix_document_embeddings_embedding_hnsw"
_IVFFLAT = "idx_document_embeddings_embedding"
_GIN = "ix_document_embeddings_content_tsv"


def _has_unaccent() -> bool:
    row = (
        op.get_bind()
        .exec_driver_sql("SELECT 1 FROM pg_available_extensions WHERE name = 'unaccent'")
        .first()
    )
    return row is not None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # pgvector + tsvector : Postgres seulement

    # config FR sans accents
    if _has_unaccent():
        op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
        op.execute(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = '{_TS_CONFIG}') THEN
                CREATE TEXT SEARCH CONFIGURATION {_TS_CONFIG} (COPY = french);
                ALTER TEXT SEARCH CONFIGURATION {_TS_CONFIG}
                  ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem;
              END IF;
            END
            $$
            """
        )
        config = _TS_CONFIG
    else:
        config = "french"

    # IVFFlat -> HNSW
    op.execute(f"DROP INDEX IF EXISTS {_IVFFLAT}")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_HNSW} ON document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    # texte intégral (titre + contenu)
    op.execute(
        "ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS content_tsv tsvector "
        f"GENERATED ALWAYS AS (to_tsvector('{config}', "
        "coalesce(metadata_->>'title', '') || ' ' || content)) STORED"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS {_GIN} ON document_embeddings USING gin (content_tsv)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {_GIN}")
    op.execute("ALTER TABLE document_embeddings DROP COLUMN IF EXISTS content_tsv")
    op.execute(f"DROP TEXT SEARCH CONFIGURATION IF EXISTS {_TS_CONFIG}")
    op.execute(f"DROP INDEX IF EXISTS {_HNSW}")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_IVFFLAT} ON document_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
