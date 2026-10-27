"""Env de test hermétique : pas de .env, pas de réseau, base isolée."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text

from jenny.core.config import Settings, get_settings
from jenny.llm.providers import GroqProvider, OpenAIProvider, get_default_llm_provider
from jenny.rag import embeddings
from jenny.rag.embeddings import SentenceTransformerEmbedder
from tests.conftest import (
    _DEFAULT_TIMEOUT,
    TEST_DB_PATH,
    TEST_DB_URL,
    HashEmbedder,
    _fallback_timeout,
    _sweep_stale_runs,
    reset_schema,
)

ROOT = Path(__file__).resolve().parents[2]


def _run_pytest(tmp_path: Path, body: str, *args: str) -> tuple[int, str]:
    """Lance un mini pytest isolé."""
    (tmp_path / "test_mini.py").write_text(textwrap.dedent(body))
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}"}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(tmp_path / "test_mini.py"),
            "-p",
            "tests.conftest",
            "-p",
            "no:cacheprovider",
            "-q",
            "--rootdir",
            str(tmp_path),
            *args,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_dotenv_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un .env local ne fuit pas."""
    (tmp_path / ".env").write_text("JENNY_GROQ_API_KEY=gsk_fuite\nJENNY_LLM_MODEL=autre\n")
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert s.groq_api_key == ""
    assert s.llm_model == "openai/gpt-oss-120b"


def test_no_llm_by_default() -> None:
    """Sans faux LLM : templates."""
    assert get_settings().groq_api_key == ""
    assert get_default_llm_provider() is None


def test_db_is_per_run_file() -> None:
    """Base propre à ce process."""
    from jenny.db.session import engine

    assert get_settings().database_url == TEST_DB_URL
    assert engine.url.database == str(TEST_DB_PATH)
    assert TEST_DB_PATH.name.startswith(f"test-{os.getpid()}-")
    assert TEST_DB_PATH.parent != ROOT


async def test_llm_network_is_cut(blocked_llm_calls) -> None:
    """Groq et OpenAI jamais joints."""
    start = time.monotonic()
    groq = await GroqProvider(api_key="gsk_test").generate("Bonjour")
    oai = await OpenAIProvider(api_key="sk-test").generate("Bonjour")
    assert groq.finish_reason == "error"
    assert oai.finish_reason == "error"
    hosts = " ".join(blocked_llm_calls.urls)
    assert "api.groq.com" in hosts
    assert "api.openai.com" in hosts
    assert time.monotonic() - start < 5


async def test_arq_enqueue_is_instant(arq_pool) -> None:
    """Pas de Redis : zéro attente."""
    from jenny.workers.queue import enqueue_normalize_message

    start = time.monotonic()
    await enqueue_normalize_message("msg-1")
    assert time.monotonic() - start < 1
    assert arq_pool.jobs == [("normalize_message", ("msg-1",), {})]


def test_state_manager_falls_back_fast() -> None:
    """Redis mort : mémoire tout de suite."""
    from jenny.engine.state_manager import StateManager

    start = time.monotonic()
    sm = StateManager()
    assert sm.backend == "memory"
    assert time.monotonic() - start < 2


async def test_hash_embedder_is_stable() -> None:
    """Même texte, même vecteur."""
    from jenny.rag.embeddings import get_default_embedder

    emb = get_default_embedder()
    assert isinstance(emb, HashEmbedder)
    a = await emb.embed_text("Vous faites des balayages ?")
    assert a == await emb.embed_text("Vous faites des balayages ?")
    assert len(a) == emb.dimension == 768


def test_sweep_removes_dead_runs(tmp_path: Path) -> None:
    """Restes morts virés, vivants gardés."""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    live = os.getppid()
    for name in (
        f"test-{dead.pid}-main.db",
        f"test-{dead.pid}-main.db-wal",
        f"test-{os.getpid()}-gw9.db",
        f"test-{live}-main.db",
        "notes.txt",
    ):
        (tmp_path / name).write_text("x")
    (tmp_path / f"run-{dead.pid}-main" / "emails").mkdir(parents=True)
    (tmp_path / f"run-{dead.pid}-main" / "emails" / "a.eml").write_text("x")

    _sweep_stale_runs(tmp_path)

    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [f"test-{live}-main.db", "notes.txt"]
    )


async def test_reset_schema_repairs_dirty_db(db_tables) -> None:
    """Schéma à moitié cassé réparé."""
    from jenny.db.base import Base
    from jenny.db.session import engine

    # run coupé : tables en vrac
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE users"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS ghost (id INTEGER)"))
        await conn.execute(text("DELETE FROM appointments"))
    await reset_schema()
    async with engine.connect() as conn:
        tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        n_users = (await conn.execute(text("SELECT count(*) FROM users"))).scalar_one()
    assert set(Base.metadata.tables) <= tables
    assert n_users == 0


def test_timeout_guard_stops_slow_test(tmp_path: Path) -> None:
    """Test bloqué : stoppé net."""
    start = time.monotonic()
    code, out = _run_pytest(
        tmp_path,
        """
        import time

        def test_lent():
            time.sleep(30)
        """,
        "-o",
        "timeout=1",
    )
    assert code == 1, out
    assert "Timeout" in out
    assert "1 failed" in out
    # bien avant les 30 s
    assert time.monotonic() - start < 25


def test_timeout_sans_option_ini() -> None:
    """Option ini absente : pas de crash."""

    def _no_ini(name: str) -> object:
        raise ValueError(f"unknown configuration value: {name!r}")

    config = SimpleNamespace(
        pluginmanager=SimpleNamespace(hasplugin=lambda name: False),
        getoption=lambda name, default=None: False,
        getini=_no_ini,
    )
    item = SimpleNamespace(config=config, get_closest_marker=lambda name: None)
    assert _fallback_timeout(item) == _DEFAULT_TIMEOUT  # type: ignore[arg-type]


def test_timeout_plugin_coupe(tmp_path: Path) -> None:
    """-p no:timeout : le secours prend le relais."""
    start = time.monotonic()
    code, out = _run_pytest(
        tmp_path,
        """
        import time

        def test_lent():
            time.sleep(30)
        """,
        "-p",
        "no:timeout",
        "-o",
        "timeout=1",
    )
    assert code == 1, out
    assert "INTERNALERROR" not in out
    assert "secours conftest" in out
    assert "1 failed" in out
    assert time.monotonic() - start < 25


# ── embedder : vraie fonction ──


def test_singleton_jamais_remplace() -> None:
    """Personne ne patche la fonction."""
    real = embeddings.get_default_embedder
    assert real.__module__ == "jenny.rag.embeddings"
    patched = [
        name
        for name, mod in list(sys.modules.items())
        if mod is not None
        and name.split(".")[0] in ("jenny", "ml")
        and getattr(mod, "get_default_embedder", real) is not real
    ]
    assert patched == []


def test_hash_dans_le_vrai_cache() -> None:
    """Le cache de prod sert le hash."""
    from jenny.engine import factory

    emb = embeddings.get_default_embedder()
    assert isinstance(emb, HashEmbedder)
    assert any(v is emb for v in embeddings._DEFAULT_EMBEDDERS.values())
    # retriever du moteur aussi
    assert factory.build_retriever().embedder is emb


@pytest.mark.real_embedder
def test_marqueur_vrai_embedder() -> None:
    """Marqueur : vrai embedder, paresseux."""
    emb = embeddings.get_default_embedder()
    assert type(emb) is SentenceTransformerEmbedder
    assert emb is embeddings.get_default_embedder()
    assert emb.dimension == 768


# ── sqlite comme postgres ──


async def test_sqlite_refuse_fk_orpheline(db_tables) -> None:
    """Clé étrangère vérifiée en test."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from sqlalchemy.exc import IntegrityError

    from jenny.db.session import async_session_factory
    from jenny.domain.models.appointment import Appointment

    start = datetime(2031, 3, 4, 10, tzinfo=UTC)
    async with async_session_factory() as session:
        # salon inexistant
        session.add(
            Appointment(
                business_id=uuid4(),
                title="Coupe",
                start_at=start,
                end_at=start + timedelta(hours=1),
            )
        )
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            await session.flush()
