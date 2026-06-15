"""Tests du bus d'événements temps réel (in-process)."""

import asyncio

import pytest

from jenny.core.events import EventBus, event_bus, publish_conversation_event


@pytest.mark.asyncio
async def test_event_bus_fanout_to_all_subscribers() -> None:
    """Un événement publié atteint toutes les files abonnées."""
    bus = EventBus()
    q1 = bus.register()
    q2 = bus.register()

    bus.publish({"n": 1})

    assert (await q1.get())["n"] == 1
    assert (await q2.get())["n"] == 1


@pytest.mark.asyncio
async def test_event_bus_unregister_stops_delivery() -> None:
    """Une file désabonnée ne reçoit plus rien."""
    bus = EventBus()
    q = bus.register()
    bus.unregister(q)
    assert bus.subscriber_count == 0

    bus.publish({"n": 1})
    assert q.empty()


def test_event_bus_overflow_drops_oldest() -> None:
    """Une file pleine jette les plus anciens événements, jamais le plus récent."""
    bus = EventBus()
    q = bus.register()

    for i in range(250):  # > _MAX_QUEUE (200)
        bus.publish({"n": i})

    assert q.qsize() == 200
    # Le plus ancien encore présent doit être > 0 (les premiers ont été jetés).
    first = q.get_nowait()
    assert first["n"] >= 49  # 250 publiés, 200 conservés → les 50 premiers jetés


@pytest.mark.asyncio
async def test_publish_conversation_event_shape() -> None:
    """``publish_conversation_event`` produit la bonne enveloppe."""
    q = event_bus.register()
    try:
        publish_conversation_event(
            "biz-123", conversation_id="conv-456", kind="inbound", channel="whatsapp"
        )
        event = await asyncio.wait_for(q.get(), timeout=1)
    finally:
        event_bus.unregister(q)

    assert event == {
        "event": "conversation.update",
        "business_id": "biz-123",
        "conversation_id": "conv-456",
        "kind": "inbound",
        "channel": "whatsapp",
    }


@pytest.mark.asyncio
async def test_publish_conversation_event_ignores_missing_business() -> None:
    """Sans business_id, rien n'est publié (garde-fou)."""
    q = event_bus.register()
    try:
        publish_conversation_event(None, conversation_id="conv-456", kind="inbound")
        await asyncio.sleep(0.01)
        assert q.empty()
    finally:
        event_bus.unregister(q)


@pytest.mark.asyncio
async def test_sse_stream_delivers_matching_event() -> None:
    """Le générateur SSE pousse un événement du bon business et s'arrête."""
    from jenny.api.routes.realtime import sse_event_stream

    async def never_disconnected() -> bool:
        return False

    frames: list[str] = []

    async def consume() -> None:
        async for frame in sse_event_stream(
            "biz-1", never_disconnected, heartbeat=0.05, max_events=1
        ):
            frames.append(frame)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)  # laisse le générateur s'abonner au bus
    # Événement d'un AUTRE business : doit être ignoré (filtre multi-tenant).
    publish_conversation_event("biz-2", conversation_id="x", kind="inbound", channel="form")
    # Événement du bon business : doit être livré puis clore le flux (max_events=1).
    publish_conversation_event("biz-1", conversation_id="c1", kind="inbound", channel="form")

    await asyncio.wait_for(task, timeout=2)

    data_frames = [f for f in frames if f.startswith("event:")]
    assert len(data_frames) == 1
    assert '"business_id": "biz-1"' in data_frames[0]
    assert '"conversation_id": "c1"' in data_frames[0]
    assert '"kind": "inbound"' in data_frames[0]
