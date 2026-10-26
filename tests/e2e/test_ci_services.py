"""Vrais services (CI) : Postgres pgvector et Redis, sans rien garder."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

PG_URL = os.environ.get("JENNY_TEST_POSTGRES_URL", "")
REDIS_URL = os.environ.get("JENNY_TEST_REDIS_URL", "")
ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.services
needs_pg = pytest.mark.skipif(not PG_URL, reason="JENNY_TEST_POSTGRES_URL absent")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="JENNY_TEST_REDIS_URL absent")
# gros modèle : CI ou demande
needs_hf = pytest.mark.skipif(
    os.environ.get("CI") != "true" and os.environ.get("JENNY_TEST_REAL_EMBEDDER") != "1",
    reason="modèle HF : CI seulement",
)


def _pg_engine():  # type: ignore[no-untyped-def]
    """Moteur Postgres sans pool."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    return create_async_engine(PG_URL, poolclass=NullPool)


@needs_pg
async def test_postgres_is_at_alembic_head() -> None:
    """Base migrée jusqu'au head."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    engine = _pg_engine()
    try:
        async with engine.connect() as conn:
            version = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            exts = set((await conn.execute(text("SELECT extname FROM pg_extension"))).scalars())
            tables = set(
                (
                    await conn.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
                    )
                ).scalars()
            )
    finally:
        await engine.dispose()
    # une seule tête
    assert heads == [version]
    assert {"vector", "btree_gist"} <= exts
    assert {"businesses", "appointments", "document_embeddings", "message_feedback"} <= tables


@needs_pg
async def test_vector_column_matches_embedder() -> None:
    """vector(N) = dimension du modèle."""
    from jenny.core.config import Settings
    from jenny.rag.embeddings import SentenceTransformerEmbedder

    model = Settings.model_fields["embeddings_model"].default
    dim = SentenceTransformerEmbedder(model_name=model).dimension
    engine = _pg_engine()
    try:
        async with engine.connect() as conn:
            col = (
                await conn.execute(
                    text(
                        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                        "WHERE attrelid = 'document_embeddings'::regclass AND attname = 'embedding'"
                    )
                )
            ).scalar_one()
            dist = (
                await conn.execute(text("SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector"))
            ).scalar_one()
    finally:
        await engine.dispose()
    assert col == f"vector({dim})"
    assert dist == pytest.approx(1.0)


@needs_pg
async def test_postgres_refuses_double_booking() -> None:
    """Double résa refusée par la base."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import AsyncSession

    from jenny.domain.models.appointment import Appointment
    from jenny.domain.models.business import Business

    engine = _pg_engine()
    try:
        async with engine.connect() as conn:
            outer = await conn.begin()
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
            try:
                biz = Business(name="Salon CI", slug=f"ci-{uuid4().hex[:12]}")
                session.add(biz)
                await session.flush()
                start = datetime(2031, 3, 4, 10, tzinfo=UTC)

                def rdv(minutes: int, status: str = "scheduled") -> Appointment:
                    begin = start + timedelta(minutes=minutes)
                    return Appointment(
                        business_id=biz.id,
                        title="Coupe",
                        start_at=begin,
                        end_at=begin + timedelta(hours=1),
                        status=status,
                    )

                session.add(rdv(0))
                await session.flush()
                # chevauchement : refusé
                with pytest.raises(IntegrityError, match="appointments_no_overlap"):
                    async with session.begin_nested():
                        session.add(rdv(30))
                        await session.flush()
                # annulé : ne bloque pas
                async with session.begin_nested():
                    session.add(rdv(30, status="cancelled"))
                    await session.flush()
                # bout à bout : ok
                async with session.begin_nested():
                    session.add(rdv(60))
                    await session.flush()
            finally:
                await session.close()
                # rien ne reste
                await outer.rollback()
    finally:
        await engine.dispose()


@needs_pg
@needs_hf
async def test_real_embedder_dimension() -> None:
    """Vrai modèle : 768 dimensions."""
    from jenny.core.config import Settings
    from jenny.rag.embeddings import SentenceTransformerEmbedder

    model = Settings.model_fields["embeddings_model"].default
    emb = SentenceTransformerEmbedder(model_name=model)
    vec = await emb.embed_text("Bonjour, vous faites des balayages ?")
    assert len(vec) == emb.dimension == 768


@needs_redis
def test_state_survives_new_manager() -> None:
    """État partagé entre deux process."""
    from jenny.engine.state_manager import StateManager

    first = StateManager(redis_url=REDIS_URL)
    assert first.backend == "redis"
    conv = uuid4()
    state = first.get_or_create(conv, business_id=uuid4(), channel="whatsapp")
    state.message_history.append({"role": "user", "content": "Bonjour"})
    first.save(state)
    try:
        again = StateManager(redis_url=REDIS_URL).get(conv)
        assert again is not None
        assert again.message_history[-1]["content"] == "Bonjour"
    finally:
        first.delete(conv)


@needs_redis
async def test_arq_job_lands_in_redis(arq_pool, monkeypatch: pytest.MonkeyPatch) -> None:
    """Vrai job arq dans Redis."""
    from arq.constants import default_queue_name, job_key_prefix

    from jenny.core.config import get_settings
    from jenny.workers import queue

    monkeypatch.setattr(get_settings(), "redis_url", REDIS_URL)
    monkeypatch.setattr(queue, "get_arq_pool", arq_pool.real_get_arq_pool)
    monkeypatch.setattr(queue, "_pool", None)
    msg_id = f"ci-{uuid4()}"
    jobs = []
    try:
        await queue.enqueue_normalize_message(msg_id)
        pool = queue._pool
        assert pool is not None
        jobs = [j for j in await pool.queued_jobs() if j.args == (msg_id,)]
        assert [j.function for j in jobs] == ["normalize_message"]
    finally:
        if queue._pool is not None:
            for job in jobs:
                await queue._pool.zrem(default_queue_name, job.job_id)
                await queue._pool.delete(job_key_prefix + job.job_id)
            await queue.close_arq_pool()
    # le faux pool n'a rien vu
    assert arq_pool.jobs == []
