"""Le routeur sortant : Jenny parle au client, pas seulement au tableau de bord."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from jenny.notifications.outbound import notify_customer

BID = uuid4()


class _FauxClient:
    def __init__(self, business_id, phone=None, email=None):
        self.id = uuid4()
        self.business_id = business_id
        self.phone = phone
        self.email = email


class _FausseConv:
    def __init__(self, channel, ext):
        self.channel = channel
        self.external_conversation_id = ext


class _FausseDB:
    """db.get() renvoie ce qu'on lui a donné, selon le modèle demandé."""

    def __init__(self, conv=None, client=None):
        self._conv, self._client = conv, client

    async def get(self, modele, _id):
        return self._conv if modele.__name__ == "Conversation" else self._client


@pytest.mark.asyncio
async def test_repond_sur_le_canal_dorigine() -> None:
    db = _FausseDB(conv=_FausseConv("whatsapp", "wa:33612345678"))
    with patch("jenny.connectors.reply_dispatch.send_channel_reply", new=AsyncMock(return_value=True)):
        canal = await notify_customer(
            db, business_id=BID, text="coucou", conversation_id=uuid4()
        )
    assert canal == "whatsapp"


@pytest.mark.asyncio
async def test_repli_sms_quand_pas_de_canal() -> None:
    db = _FausseDB(client=_FauxClient(BID, phone="+33612345678"))
    faux = AsyncMock(return_value=type("R", (), {"success": True})())
    with patch("jenny.notifications.sms_sender.SmsSender.send_sms", new=faux):
        canal = await notify_customer(db, business_id=BID, text="coucou", customer_id=uuid4())
    assert canal == "sms"


@pytest.mark.asyncio
async def test_repli_email_quand_sms_echoue() -> None:
    db = _FausseDB(client=_FauxClient(BID, phone="+33600000000", email="c@x.com"))
    sms_ko = AsyncMock(return_value=type("R", (), {"success": False})())
    with (
        patch("jenny.notifications.sms_sender.SmsSender.send_sms", new=sms_ko),
        patch("jenny.notifications.email_sender.EmailSender.send", new=AsyncMock(return_value=True)),
    ):
        canal = await notify_customer(db, business_id=BID, text="coucou", customer_id=uuid4())
    assert canal == "email"


@pytest.mark.asyncio
async def test_client_injoignable_renvoie_none() -> None:
    db = _FausseDB(client=_FauxClient(BID))  # ni tel ni email
    assert await notify_customer(db, business_id=BID, text="coucou", customer_id=uuid4()) is None


@pytest.mark.asyncio
async def test_client_dun_autre_salon_refuse() -> None:
    """Cloisonnement : on n'écrit jamais au client d'un autre salon."""
    db = _FausseDB(client=_FauxClient(uuid4(), email="c@x.com"))
    assert await notify_customer(db, business_id=BID, text="coucou", customer_id=uuid4()) is None


@pytest.mark.asyncio
async def test_ne_leve_jamais() -> None:
    """Un rappel raté ne doit jamais casser la tâche qui l'appelle."""

    class _DBCassee:
        async def get(self, *_):
            raise RuntimeError("base morte")

    assert await notify_customer(_DBCassee(), business_id=BID, text="x", customer_id=uuid4()) is None
