"""Env de test hermétique : pas de .env, pas de réseau, base isolée."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import inspect, text

from jenny.core.config import Settings, get_settings
from jenny.llm.providers import GroqProvider, LlamaProvider, get_default_llm_provider
from tests.conftest import (
    TEST_DB_PATH,
    TEST_DB_URL,
    HashEmbedder,
    _sweep_stale_runs,
    reset_schema,
)

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parents[2]


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
    """Groq et Ollama jamais joints."""
    start = time.monotonic()
    groq = await GroqProvider(api_key="gsk_test").generate("Bonjour")
    ollama = await LlamaProvider(model="qwen2.5:7b-instruct").generate("Bonjour")
    assert groq.finish_reason == "error"
    assert ollama.finish_reason == "error"
    hosts = " ".join(blocked_llm_calls.urls)
    assert "api.groq.com" in hosts
    assert ":11434" in hosts
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
    (tmp_path / "test_lent.py").write_text(
        textwrap.dedent(
            """
            import time

            def test_lent():
                time.sleep(30)
            """
        )
    )
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}"}
    start = time.monotonic()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(tmp_path / "test_lent.py"),
            "-p",
            "tests.conftest",
            "-p",
            "no:cacheprovider",
            "-o",
            "timeout=1",
            "-q",
            "--rootdir",
            str(tmp_path),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "Timeout" in out
    assert "1 failed" in out
    # bien avant les 30 s
    assert time.monotonic() - start < 25
