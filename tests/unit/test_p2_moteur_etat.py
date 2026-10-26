"""passe 2 moteur : cache mémoire borné."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jenny.engine.state_manager import (
    MEMORY_MAX_STATES,
    MEMORY_TTL_SECONDS,
    ConversationState,
    StateCache,
    StateManager,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _state() -> ConversationState:
    return ConversationState(conversation_id=uuid4())


class TestStateCache:
    def test_lru_garde_les_recents(self) -> None:
        cache = StateCache(max_items=3, ttl=0)
        states = [_state() for _ in range(4)]
        for i, st in enumerate(states[:3]):
            cache[f"k{i}"] = st
        # k0 relu : il reste
        assert cache.get("k0") is states[0]
        cache["k3"] = states[3]
        assert len(cache) == 3
        assert "k1" not in cache
        assert cache.get("k0") is states[0]
        assert cache.get("k3") is states[3]

    def test_ttl_glissant(self) -> None:
        clock = _Clock()
        cache = StateCache(max_items=10, ttl=60, clock=clock)
        cache["a"] = _state()
        cache["b"] = _state()
        clock.now += 50
        assert cache.get("a") is not None  # touché
        clock.now += 30
        assert cache.get("b") is None  # 80 s sans contact
        assert cache.get("a") is not None
        clock.now += 61
        assert "a" not in cache
        assert len(cache) == 0

    def test_purge_a_l_ecriture(self) -> None:
        clock = _Clock()
        cache = StateCache(max_items=10, ttl=60, clock=clock)
        for i in range(5):
            cache[f"old{i}"] = _state()
        clock.now += 120
        cache["new"] = _state()
        assert len(cache) == 1

    def test_pop_clear(self) -> None:
        cache = StateCache(max_items=5)
        st = _state()
        cache["a"] = st
        assert cache.pop("a") is st
        assert cache.pop("a") is None
        cache["b"] = _state()
        cache.clear()
        assert len(cache) == 0
        with pytest.raises(KeyError):
            cache["b"]


class TestStateManagerBorne:
    def test_defauts_raisonnables(self) -> None:
        assert MEMORY_MAX_STATES == 5000
        assert MEMORY_TTL_SECONDS == 48 * 3600
        sm = StateManager(redis_url="redis://localhost:1/0")
        assert sm._states.max_items == MEMORY_MAX_STATES

    @pytest.mark.asyncio
    async def test_widget_ne_grossit_pas(self) -> None:
        # un visiteur = une conversation
        sm = StateManager(redis_url="redis://localhost:1/0", max_memory_states=50)
        biz = uuid4()
        ids = [uuid4() for _ in range(200)]
        for cid in ids:
            st = await sm.aget_or_create(cid, business_id=biz)
            st.add_user_message("bonjour")
            await sm.asave(st)
        assert len(sm._states) == 50
        # les derniers restent
        assert await sm.aget(ids[-1]) is not None
        assert sm.get(ids[0]) is None

    @pytest.mark.asyncio
    async def test_conversation_active_gardee(self) -> None:
        sm = StateManager(redis_url="redis://localhost:1/0", max_memory_states=3)
        keep = uuid4()
        st = await sm.aget_or_create(keep)
        st.add_user_message("je veux un rdv")
        await sm.asave(st)
        for _ in range(5):
            await sm.aget_or_create(uuid4())
            # le client revient
            again = await sm.aget_or_create(keep)
            await sm.asave(again)
        assert (await sm.aget(keep)).message_history[0]["content"] == "je veux un rdv"
