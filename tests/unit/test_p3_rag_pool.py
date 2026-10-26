"""Pool hybride : 30 par défaut, comme au calibrage."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.core.config import Settings, get_settings
from jenny.rag import vector_store as vs
from jenny.rag.vector_store import PgVectorStore


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._bind = SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"), url=f"pg://p3-{id(self)}"
        )

    def get_bind(self):
        return self._bind

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params or {}))
        if "information_schema" in sql:
            caps = SimpleNamespace(fts=True, cfg=True, vver="0.8.2")
            return SimpleNamespace(one=lambda: caps)
        return SimpleNamespace(fetchall=lambda: [])


@pytest.fixture(autouse=True)
def _reset_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vs, "_CAPS", {})


def test_defaut_du_reglage_garde_30(monkeypatch: pytest.MonkeyPatch) -> None:
    # le défaut de config (12) ne réduit plus le pool
    default = Settings.model_fields["rag_rerank_candidates"].default
    monkeypatch.setattr(get_settings(), "rag_rerank_candidates", default)
    assert vs.default_pool() == vs.POOL_SIZE == 30


@pytest.mark.parametrize(("value", "pool"), [(12, 30), (29, 30), (30, 30), (64, 64)])
def test_reglage_ne_fait_que_monter(monkeypatch: pytest.MonkeyPatch, value: int, pool: int) -> None:
    monkeypatch.setattr(get_settings(), "rag_rerank_candidates", value)
    assert vs.default_pool() == pool


@pytest.mark.asyncio
async def test_recherche_chat_prend_30_par_voie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rag_rerank_candidates", 12)
    s = _Session()
    await PgVectorStore().search(s, uuid4(), [0.1] * 4, top_k=3, query_text="prix coupe")
    params = next(p for sql, p in s.calls if "embedding <=>" in sql)
    assert params["pool"] == 30
