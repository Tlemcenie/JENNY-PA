"""tests de l'état conversationnel."""

import asyncio
import json
from uuid import uuid4

import pytest

from jenny.engine.state_manager import (
    ConversationState,
    ExtractedSlot,
    StateManager,
)


class _FakeAsyncRedis:
    """redis async en mémoire"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value
        self.ttl[key] = ttl

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


def _full_state() -> ConversationState:
    st = ConversationState(business_id=uuid4(), customer_id=uuid4())
    st.add_user_message("bonjour")
    st.business_persona = {"ton": "chaleureux"}
    st.business_name = "Salon Léa"
    st.business_hours_text = "lundi fermé"
    st.business_timezone = "Europe/Paris"
    st.detected_language = "fr"
    st.customer_facts = ["aime les balayages"]
    st.clarification_instruction = "demande le jour"
    st.knowledge_gap = True
    st.business_catalog = "Coupe 30€"
    st.set_slot("date", "2026-10-29", entity_type="DATE")
    st.arm_latch("awaiting_name")
    st.reset_booking_slots()
    st.set_slot("appointment_id", "abc")
    return st


class TestSerialisation:
    def test_aller_retour_complet(self) -> None:
        st = _full_state()
        back = ConversationState.from_dict(json.loads(json.dumps(st.to_dict())))
        assert back.business_hours_text == "lundi fermé"
        assert back.business_timezone == "Europe/Paris"
        assert back.business_persona == {"ton": "chaleureux"}
        assert back.business_name == "Salon Léa"
        assert back.detected_language == "fr"
        assert back.customer_facts == ["aime les balayages"]
        assert back.clarification_instruction == "demande le jour"
        assert back.knowledge_gap is True
        assert back.business_catalog == "Coupe 30€"
        assert back.awaiting_name is True
        assert back.latch_turns == {"awaiting_name": 1}
        assert back.slots_reset_at == st.slots_reset_at
        assert back.slots["appointment_id"].value == "abc"
        assert back.customer_id == st.customer_id

    def test_vieux_dict_sans_champs(self) -> None:
        old = {"conversation_id": str(uuid4()), "slots": {}}
        st = ConversationState.from_dict(old)
        assert st.business_hours_text is None
        assert st.latch_turns == {}
        assert st.customer_facts == []


class TestVerrous:
    def test_arme_puis_expire(self) -> None:
        st = ConversationState()
        st.add_user_message("rdv")
        st.arm_latch("awaiting_name")
        for _ in range(3):
            st.add_user_message("...")
            assert st.expire_latches(3) == []
            assert st.awaiting_name is True
        st.add_user_message("...")
        assert st.expire_latches(3) == ["awaiting_name"]
        assert st.awaiting_name is False
        assert "awaiting_name" not in st.latch_turns

    def test_desarme(self) -> None:
        st = ConversationState()
        st.arm_latch("awaiting_phone")
        st.disarm_latch("awaiting_phone")
        assert st.awaiting_phone is False
        assert st.latch_turns == {}

    def test_booleen_pose_a_la_main(self) -> None:
        # compte à partir de maintenant
        st = ConversationState(turn_count=5)
        st.awaiting_waitlist = True
        st.expire_latches(3)
        assert st.latch_turns["awaiting_waitlist"] == 5
        assert st.awaiting_waitlist is True


class TestPurgeSlots:
    def test_garde_id_et_contact(self) -> None:
        st = ConversationState()
        for k, v in {
            "date": "2026-10-29",
            "time": "14:00",
            "service": "Coupe",
            "duration": "30",
            "operation": "reschedule",
            "appointment_id": "rdv-1",
            "name": "Marie",
            "phone": "0612345678",
        }.items():
            st.set_slot(k, v)
        st.slots["order_number"] = ExtractedSlot(name="order_number", required=True)
        st.reset_booking_slots()
        assert set(st.slots) == {"appointment_id", "name", "phone"}
        assert st.slots_reset_at is not None

    def test_placeholders_seuls(self) -> None:
        st = ConversationState()
        st.slots["date"] = ExtractedSlot(name="date", required=True)
        st.set_slot("service", "Coupe")
        st.drop_missing_placeholders()
        assert set(st.slots) == {"service"}

    def test_messages_depuis_purge(self) -> None:
        st = ConversationState()
        st.add_user_message("une coupe femme demain")
        st.reset_booking_slots()
        st.add_user_message("je voudrais aussi un truc")
        assert st.user_messages_since_reset() == ["je voudrais aussi un truc"]

    def test_sans_purge_tout(self) -> None:
        st = ConversationState()
        st.add_user_message("a")
        st.add_assistant_message("b")
        st.add_user_message("c")
        assert st.user_messages_since_reset() == ["a", "c"]


class TestStateManagerAsync:
    def _manager(self) -> tuple[StateManager, _FakeAsyncRedis]:
        sm = StateManager(redis_url="redis://localhost:1/0")  # force mémoire
        fake = _FakeAsyncRedis()
        sm._async_client = lambda: fake  # type: ignore[method-assign]
        return sm, fake

    @pytest.mark.asyncio
    async def test_memoire_sans_redis(self) -> None:
        sm = StateManager(redis_url="redis://localhost:1/0")
        cid = uuid4()
        st = await sm.aget_or_create(cid)
        st.turn_count = 4
        await sm.asave(st)
        assert (await sm.aget(cid)).turn_count == 4
        assert sm.get(cid).turn_count == 4
        await sm.adelete(cid)
        assert await sm.aget(cid) is None

    @pytest.mark.asyncio
    async def test_redis_async_ecrit_et_relit(self) -> None:
        sm, fake = self._manager()
        cid = uuid4()
        st = await sm.aget_or_create(cid)
        st.business_hours_text = "mardi 9h-19h"
        st.set_slot("date", "2026-10-29")
        await sm.asave(st)
        key = f"{StateManager.REDIS_PREFIX}{cid}"
        assert fake.ttl[key] == StateManager.REDIS_TTL
        # autre process : cache vide
        sm._states.clear()
        back = await sm.aget_or_create(cid)
        assert back.business_hours_text == "mardi 9h-19h"
        assert back.slots["date"].value == "2026-10-29"
        await sm.adelete(cid)
        assert key not in fake.data

    @pytest.mark.asyncio
    async def test_json_tolere_uuid(self) -> None:
        sm, fake = self._manager()
        st = await sm.aget_or_create(uuid4())
        st.retrieved_documents = [{"content": "x", "metadata": {"id": uuid4()}}]
        await sm.asave(st)
        assert len(fake.data) == 1

    @pytest.mark.asyncio
    async def test_redis_en_panne_pas_de_crash(self) -> None:
        sm = StateManager(redis_url="redis://localhost:1/0")

        class _Broken:
            async def get(self, key: str) -> str:
                raise ConnectionError("down")

            async def setex(self, *a: object) -> None:
                raise ConnectionError("down")

        sm._async_client = lambda: _Broken()  # type: ignore[method-assign]
        st = await sm.aget_or_create(uuid4())
        await sm.asave(st)
        assert sm.get(st.conversation_id) is st

    def test_client_par_boucle(self) -> None:
        sm = StateManager(redis_url="redis://localhost:1/0")
        sm._redis_url = "redis://localhost:1/0"  # pas de connexion

        async def grab() -> object:
            return sm._async_client()

        c1 = asyncio.run(grab())
        c2 = asyncio.run(grab())
        assert c1 is not None and c2 is not None and c1 is not c2
