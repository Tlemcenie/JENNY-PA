"""Réglages du pool lus depuis .env."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.pool import NullPool

from jenny.core.config import Settings
from jenny.db.session import engine_options

PG = "postgresql+asyncpg://u:p@db.example:5432/jenny"
_VARS = ("JENNY_SQL_ECHO", "JENNY_DB_POOLER", "JENNY_DB_POOL_SIZE", "JENNY_DB_MAX_OVERFLOW")


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    # même fichier que Settings
    monkeypatch.setitem(Settings.model_config, "env_file", str(path))
    return path


def test_pool_size_from_dotenv(env_file: Path) -> None:
    env_file.write_text("JENNY_DB_POOL_SIZE=4\njenny_db_max_overflow=2\n", encoding="utf-8")
    opts = engine_options(PG)
    assert opts["pool_size"] == 4 and opts["max_overflow"] == 2


def test_pooler_from_dotenv(env_file: Path) -> None:
    env_file.write_text("JENNY_DB_POOLER=transaction\n", encoding="utf-8")
    opts = engine_options(PG)
    assert opts["poolclass"] is NullPool
    assert opts["connect_args"]["statement_cache_size"] == 0


def test_echo_from_dotenv(env_file: Path) -> None:
    env_file.write_text("JENNY_SQL_ECHO=1\n", encoding="utf-8")
    assert engine_options(PG)["echo"] is True


def test_real_env_wins(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file.write_text("JENNY_DB_POOL_SIZE=4\n", encoding="utf-8")
    monkeypatch.setenv("JENNY_DB_POOL_SIZE", "7")
    assert engine_options(PG)["pool_size"] == 7


def test_bad_values_fall_back(env_file: Path) -> None:
    env_file.write_text("JENNY_DB_POOL_SIZE=beaucoup\nJENNY_DB_MAX_OVERFLOW=-3\n", encoding="utf-8")
    opts = engine_options(PG)
    assert opts["pool_size"] == 10 and opts["max_overflow"] == 0


def test_no_env_file_in_tests() -> None:
    """Le conftest coupe le .env."""
    assert Settings.model_config.get("env_file") is None
