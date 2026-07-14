"""Pipelines e2e Jenny."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401 — enregistre tous les modèles dans Base.metadata
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.user import User

# mot de passe valide
_E2E_PASSWORD = "Strong#1234"


# ARRAY postgres rendu en JSON
@compiles(ARRAY, "sqlite")
def _render_array_as_json_on_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def client():
    """Client HTTP async."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://e2e",
    ) as c:
        yield c


@pytest.fixture
async def db_tables():
    """Crée puis nettoie le schéma."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ═══════════════════════════════════════════════════════════════════
#  1) pipeline auth
# ═══════════════════════════════════════════════════════════════════


async def _register_and_verify(
    client: AsyncClient, email: str, full_name: str = "E2E User"
) -> str:
    """Inscrit, vérifie, renvoie le JWT."""
    r_reg = await client.post(
        "/api/v1/auth/register",
        json={"full_name": full_name, "email": email, "password": _E2E_PASSWORD},
    )
    assert r_reg.status_code == 202, r_reg.text
    code = r_reg.json()["debug_code"]
    r_verify = await client.post(
        "/api/v1/auth/verify-email",
        json={"email": email, "code": code},
    )
    assert r_verify.status_code == 200, r_verify.text
    token = r_verify.json()["access_token"]
    assert token
    return token


class TestAuthPipeline:
    """Inscription, vérif, login, profil."""

    @pytest.mark.asyncio
    async def test_register_verify_login_me(self, client: AsyncClient, db_tables: None) -> None:
        email = f"alice+{uuid4().hex[:6]}@e2e.jenny.ai"

        # register : 202
        r_reg = await client.post(
            "/api/v1/auth/register",
            json={"full_name": "Alice E2E", "email": email, "password": _E2E_PASSWORD},
        )
        assert r_reg.status_code == 202, r_reg.text
        reg = r_reg.json()
        assert reg["status"] == "verification_required"
        assert reg["email"] == email
        assert "access_token" not in reg
        code = reg["debug_code"]

        # login avant vérif : bloqué
        r_blocked = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _E2E_PASSWORD},
        )
        assert r_blocked.status_code == 403, r_blocked.text
        assert r_blocked.json()["detail"] == "email_not_verified"

        # vérif du code
        r_verify = await client.post(
            "/api/v1/auth/verify-email",
            json={"email": email, "code": code},
        )
        assert r_verify.status_code == 200, r_verify.text
        assert r_verify.json()["token_type"] == "bearer"
        assert r_verify.json()["access_token"]

        # login après vérif
        r_log = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _E2E_PASSWORD},
        )
        assert r_log.status_code == 200, r_log.text
        token = r_log.json()["access_token"]
        assert token

        # /me expose le business
        r_me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_me.status_code == 200, r_me.text
        me = r_me.json()
        assert me["email"] == email
        assert me["business_id"]


class TestEmailVerification:
    """Cas limites du flux confirmation."""

    @pytest.mark.asyncio
    async def test_wrong_code_rejected(self, client: AsyncClient, db_tables: None) -> None:
        email = f"wrong+{uuid4().hex[:6]}@e2e.jenny.ai"
        r_reg = await client.post(
            "/api/v1/auth/register",
            json={"full_name": "Wrong Code", "email": email, "password": _E2E_PASSWORD},
        )
        assert r_reg.status_code == 202
        r = await client.post(
            "/api/v1/auth/verify-email",
            json={"email": email, "code": "000000"},
        )
        assert r.status_code == 400, r.text

    @pytest.mark.asyncio
    async def test_too_many_attempts_locks(self, client: AsyncClient, db_tables: None) -> None:
        email = f"brute+{uuid4().hex[:6]}@e2e.jenny.ai"
        r_reg = await client.post(
            "/api/v1/auth/register",
            json={"full_name": "Brute Force", "email": email, "password": _E2E_PASSWORD},
        )
        good_code = r_reg.json()["debug_code"]
        # 5 tentatives → saturé
        for _ in range(5):
            r_bad = await client.post(
                "/api/v1/auth/verify-email",
                json={"email": email, "code": "000000"},
            )
            assert r_bad.status_code == 400, r_bad.text
        # 6e essai : verrouillé
        r_locked = await client.post(
            "/api/v1/auth/verify-email",
            json={"email": email, "code": good_code},
        )
        assert r_locked.status_code == 429, r_locked.text

    @pytest.mark.asyncio
    async def test_expired_code_rejected(self, client: AsyncClient, db_tables: None) -> None:
        email = f"expired+{uuid4().hex[:6]}@e2e.jenny.ai"
        r_reg = await client.post(
            "/api/v1/auth/register",
            json={"full_name": "Expired", "email": email, "password": _E2E_PASSWORD},
        )
        code = r_reg.json()["debug_code"]
        # on force l'expiration
        async with async_session_factory() as s:
            await s.execute(
                update(User)
                .where(User.email == email)
                .values(email_verification_expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await s.commit()
        r = await client.post(
            "/api/v1/auth/verify-email",
            json={"email": email, "code": code},
        )
        assert r.status_code == 400, r.text

    @pytest.mark.asyncio
    async def test_resend_cooldown_then_new_code(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        email = f"resend+{uuid4().hex[:6]}@e2e.jenny.ai"
        r_reg = await client.post(
            "/api/v1/auth/register",
            json={"full_name": "Resend", "email": email, "password": _E2E_PASSWORD},
        )
        first_code = r_reg.json()["debug_code"]

        # renvoi immédiat : refusé
        r_cooldown = await client.post("/api/v1/auth/resend-code", json={"email": email})
        assert r_cooldown.status_code == 429, r_cooldown.text

        # on antidate l'envoi
        async with async_session_factory() as s:
            await s.execute(
                update(User)
                .where(User.email == email)
                .values(email_verification_sent_at=datetime.now(UTC) - timedelta(minutes=5))
            )
            await s.commit()

        r_resend = await client.post("/api/v1/auth/resend-code", json={"email": email})
        assert r_resend.status_code == 200, r_resend.text
        new_code = r_resend.json()["debug_code"]

        # ancien code KO, nouveau OK
        r_old = await client.post(
            "/api/v1/auth/verify-email", json={"email": email, "code": first_code}
        )
        assert r_old.status_code == 400, r_old.text
        r_new = await client.post(
            "/api/v1/auth/verify-email", json={"email": email, "code": new_code}
        )
        assert r_new.status_code == 200, r_new.text
        assert r_new.json()["access_token"]

    @pytest.mark.asyncio
    async def test_resend_unknown_email_is_generic(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        # pas d'énumération de compte
        r = await client.post(
            "/api/v1/auth/resend-code",
            json={"email": f"nobody+{uuid4().hex[:6]}@e2e.jenny.ai"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "sent"


# ═══════════════════════════════════════════════════════════════════
#  2) pipeline chat
# ═══════════════════════════════════════════════════════════════════


class TestChatPipeline:
    """Chat avec Jenny."""

    @pytest.mark.asyncio
    async def test_simple_greeting(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": str(uuid4()),
                "message": "Bonjour Jenny !",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["intent"] == "greeting"
        assert data["response"]
        assert data["requires_human"] is False

    @pytest.mark.asyncio
    async def test_multiturn_keeps_context(self, client: AsyncClient) -> None:
        conv_id = str(uuid4())
        biz_id = str(uuid4())

        r1 = await client.post(
            "/api/v1/conversation/chat",
            json={"conversation_id": conv_id, "business_id": biz_id, "message": "Bonjour !"},
        )
        assert r1.status_code == 200

        r2 = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": conv_id,
                "business_id": biz_id,
                "message": "Où en est ma commande CMD-555 ?",
            },
        )
        assert r2.status_code == 200
        assert r2.json()["intent"] == "order_status"

        r_status = await client.get(f"/api/v1/conversation/status/{conv_id}")
        assert r_status.status_code == 200
        body = r_status.json()
        assert body["turn_count"] >= 2


# ═══════════════════════════════════════════════════════════════════
#  3) pipeline RDV
# ═══════════════════════════════════════════════════════════════════


class TestAppointmentPipeline:
    """Créneau puis réservation."""

    @pytest.mark.asyncio
    async def test_chat_books_an_appointment(self, client: AsyncClient) -> None:
        conv_id = str(uuid4())
        biz_id = str(uuid4())

        r = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": conv_id,
                "business_id": biz_id,
                "message": "Je voudrais prendre rendez-vous samedi matin pour une coupe",
                "channel": "whatsapp",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["intent"] in ("appointment", "planning")
        assert data["response"]

    @pytest.mark.asyncio
    async def test_planning_agent_returns_slots(self) -> None:
        from jenny.agents.planning_agent import PlanningAgent
        from jenny.engine.state_manager import ConversationState
        from jenny.integrations.google_calendar import GoogleCalendarService

        agent = PlanningAgent(calendar_service=GoogleCalendarService())
        state = ConversationState()
        state.set_intent("planning", 0.9)
        state.add_user_message("Quelles sont vos disponibilités cette semaine ?")

        result = await agent.handle(state)
        assert result["response"]
        action = result["action_result"]
        assert action["type"] == "planning_info"
        assert action.get("available_slots_count", 0) >= 0

    @pytest.mark.asyncio
    async def test_book_appointment_action(self) -> None:
        from jenny.actions.handlers.book_appointment import BookAppointmentAction

        action = BookAppointmentAction()
        result = await action.execute(
            {
                "date": "12/05/2026",
                "time": "10:00",
                "service": "Coupe + Brushing",
                "customer_name": "Alice E2E",
                "customer_email": "alice@e2e.jenny.ai",
            }
        )
        assert result["success"] is True
        assert "message" in result


# ═══════════════════════════════════════════════════════════════════
#  4) pipeline devis
# ═══════════════════════════════════════════════════════════════════


class TestQuotePipeline:
    """Devis depuis le chat."""

    @pytest.mark.asyncio
    async def test_chat_quote_intent(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": str(uuid4()),
                "message": "Bonjour, pouvez-vous me faire un devis pour un site vitrine ?",
                "channel": "form",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["response"]

    @pytest.mark.asyncio
    async def test_generate_quote_no_business(self) -> None:
        """Sans business : échec propre."""
        from jenny.actions.handlers.generate_quote import GenerateQuoteAction

        result = await GenerateQuoteAction().execute(
            {"service": "Coupe femme", "email": "alice@e2e.jenny.ai", "name": "Alice E2E"}
        )
        assert result["success"] is False
        assert result.get("message")

    @pytest.mark.asyncio
    async def test_generate_quote_action(self, db_tables: None) -> None:
        """Devis réel avec TVA."""
        from sqlalchemy import select

        from jenny.actions.handlers.generate_quote import GenerateQuoteAction
        from jenny.domain.models.business import Business
        from jenny.domain.models.prestation import Prestation
        from jenny.domain.models.quote import Quote

        bid = uuid4()
        async with async_session_factory() as db:
            db.add(Business(id=bid, name="Salon Test", slug=f"salon-{bid.hex[:8]}", email="salon@test.fr"))
            db.add(
                Prestation(
                    business_id=bid,
                    name="Coupe femme",
                    price_cents=3900,
                    duration_minutes=45,
                    is_active=True,
                )
            )
            await db.commit()

        result = await GenerateQuoteAction().execute(
            {"business_id": str(bid), "service": "Coupe femme", "name": "Alice E2E"}
        )
        assert result["success"] is True, result
        assert result["reference"].startswith("DEV-")
        assert result["total_eur"] == 39.0
        assert result["validity_days"] == 30
        assert result["status"] in {"draft", "sent"}

        # devis persisté + TVA cohérente
        async with async_session_factory() as db:
            quote = (
                await db.execute(select(Quote).where(Quote.reference == result["reference"]))
            ).scalars().first()
            assert quote is not None
            assert quote.total_cents == 3900
            assert quote.total_ht_cents + quote.total_tva_cents == quote.total_cents
            assert quote.vat_rate == pytest.approx(0.20)


# ═══════════════════════════════════════════════════════════════════
#  5) pipeline services
# ═══════════════════════════════════════════════════════════════════


class TestServicesPipeline:
    """FAQ, ticket, escalade."""

    @pytest.mark.asyncio
    async def test_faq_request(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": str(uuid4()),
                "message": "Quels services proposez-vous ?",
                "channel": "form",
            },
        )
        assert r.status_code == 200
        assert r.json()["response"]

    @pytest.mark.asyncio
    async def test_complaint_creates_ticket(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from jenny.actions.handlers.create_ticket import CreateTicketAction
        from jenny.db.repositories.support_ticket_repo import SupportTicketRepository

        fake_ticket = MagicMock()
        fake_ticket.id = uuid4()
        fake_ticket.reference = "TKT-E2E-001"
        fake_ticket.status = "open"

        with patch.object(
            SupportTicketRepository,
            "create_ticket",
            new_callable=AsyncMock,
            return_value=fake_ticket,
        ):
            action = CreateTicketAction()
            result = await action.execute(
                {
                    "email": "alice@e2e.jenny.ai",
                    "business_id": str(uuid4()),
                    "subject": "Problème de livraison",
                }
            )
        assert result["success"] is True
        assert "TKT-E2E-001" in str(result)

    @pytest.mark.asyncio
    async def test_human_escalation(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": str(uuid4()),
                "message": "Je veux parler à un vrai humain s'il vous plaît",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["requires_human"] is True
        assert data["intent"] == "escalation"


# ═══════════════════════════════════════════════════════════════════
#  6) pipeline complet
# ═══════════════════════════════════════════════════════════════════


class TestFullJourney:
    """Parcours complet du client."""

    @pytest.mark.asyncio
    async def test_full_journey(self, client: AsyncClient, db_tables: None) -> None:
        email = f"journey+{uuid4().hex[:6]}@e2e.jenny.ai"
        token = await _register_and_verify(client, email, full_name="Journey User")
        assert token

        conv_id = str(uuid4())
        biz_id = str(uuid4())

        for message, must_have_response in [
            ("Bonjour !", True),
            ("Je voudrais prendre rendez-vous mardi à 14h", True),
            ("Pouvez-vous m'envoyer un devis pour la prestation ?", True),
            ("Quels services proposez-vous ?", True),
            ("Merci, à bientôt !", True),
        ]:
            r = await client.post(
                "/api/v1/conversation/chat",
                json={
                    "conversation_id": conv_id,
                    "business_id": biz_id,
                    "message": message,
                },
            )
            assert r.status_code == 200
            data = r.json()
            if must_have_response:
                assert data["response"]
                assert isinstance(data["response"], str)

        r_status = await client.get(f"/api/v1/conversation/status/{conv_id}")
        assert r_status.status_code == 200
        body = r_status.json()
        assert body["turn_count"] == 5


# ═══════════════════════════════════════════════════════════════════
#  6) pipeline ingestion
# ═══════════════════════════════════════════════════════════════════


class TestIngestionPipeline:
    """Ingestion : conversation + message."""

    @pytest.mark.asyncio
    async def test_form_submission_creates_conversation(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        token = await _register_and_verify(client, "form-ingest@example.com")
        auth = {"Authorization": f"Bearer {token}"}
        bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

        r = await client.post(
            f"/api/v1/ingest/form?business_id={bid}",
            json={
                "form_id": "contact",
                "submitted_at": "2026-06-13T10:00:00Z",
                "full_name": "Claire Martin",
                "email": "claire@example.com",
                "subject": "Devis",
                "message": "Je voudrais un devis pour une prestation.",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["id"] and body["conversation_id"]
        assert body["status"] == "received"

        # conversation persistée et listable
        convs = (await client.get("/api/v1/conversations", headers=auth)).json()
        assert convs["total"] == 1
        assert convs["conversations"][0]["channel"] == "form"

    @pytest.mark.asyncio
    async def test_email_thread_groups_into_one_conversation(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        token = await _register_and_verify(client, "email-ingest@example.com")
        auth = {"Authorization": f"Bearer {token}"}
        bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

        def email(msg_id: str, in_reply_to: str | None) -> dict:
            return {
                "message_id": msg_id,
                "in_reply_to": in_reply_to,
                "from_email": "client@example.com",
                "from_name": "Jean Client",
                "to_email": "contact@business.fr",
                "subject": "Question",
                "text_body": "Bonjour, une question sur vos services.",
                "sent_at": "2026-06-13T10:00:00Z",
            }

        r1 = await client.post(f"/api/v1/ingest/email?business_id={bid}", json=email("<m1@x>", None))
        assert r1.status_code == 201, r1.text
        # même thread
        r2 = await client.post(
            f"/api/v1/ingest/email?business_id={bid}", json=email("<m2@x>", "<m1@x>")
        )
        assert r2.status_code == 201, r2.text

        convs = (await client.get("/api/v1/conversations", headers=auth)).json()
        assert convs["total"] == 1, convs
        conv_id = convs["conversations"][0]["id"]
        detail = (await client.get(f"/api/v1/conversations/{conv_id}", headers=auth)).json()
        assert len(detail["messages"]) == 2


# ═══════════════════════════════════════════════════════════════════
#  7) webhook whatsapp
# ═══════════════════════════════════════════════════════════════════

_WA_META = {"display_phone_number": "1", "phone_number_id": "PNID"}


def _wa_payload(value: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "W", "changes": [{"field": "messages", "value": value}]}],
    }


class TestWhatsAppWebhookTolerance:
    """WhatsApp acquitte tout webhook Meta."""

    @pytest.mark.asyncio
    async def test_status_callback_without_metadata(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.post(
            "/api/v1/webhooks/whatsapp",
            json=_wa_payload(
                {"messaging_product": "whatsapp", "statuses": [{"id": "x", "status": "read"}]}
            ),
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_status_callback_with_metadata(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.post(
            "/api/v1/webhooks/whatsapp",
            json=_wa_payload(
                {
                    "messaging_product": "whatsapp",
                    "metadata": _WA_META,
                    "statuses": [{"id": "x", "status": "delivered"}],
                }
            ),
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_message_with_nameless_contact(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.post(
            "/api/v1/webhooks/whatsapp",
            json=_wa_payload(
                {
                    "messaging_product": "whatsapp",
                    "metadata": _WA_META,
                    "contacts": [{"wa_id": "336"}],
                    "messages": [
                        {
                            "from": "336",
                            "id": "wamid.N",
                            "timestamp": "1",
                            "type": "text",
                            "text": {"body": "bonjour"},
                        }
                    ],
                }
            ),
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_non_json_body_is_rejected(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.post("/api/v1/webhooks/whatsapp", content="pas du json {{{")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_created_at_default_is_portable(db_tables: None) -> None:
    """created_at portable postgres/sqlite."""
    from sqlalchemy import select

    from jenny.domain.models.webhook_delivery import WebhookDelivery

    async with async_session_factory() as s, s.begin():
        s.add(WebhookDelivery(dedup_key="portable:1", provider="whatsapp"))
    async with async_session_factory() as s:
        row = (
            await s.execute(
                select(WebhookDelivery).where(WebhookDelivery.dedup_key == "portable:1")
            )
        ).scalar_one()
        assert row.created_at is not None


# ═══════════════════════════════════════════════════════════════════
#  8) webhook instagram
# ═══════════════════════════════════════════════════════════════════


def _ig_payload(messaging: dict) -> dict:
    return {
        "object": "instagram",
        "entry": [{"id": "PAGE", "time": 1, "messaging": [messaging]}],
    }


class TestInstagramWebhookTolerance:
    """Instagram acquitte tout webhook Meta."""

    @pytest.mark.asyncio
    async def test_event_without_message(self, client: AsyncClient, db_tables: None) -> None:
        # accusé read/delivery
        r = await client.post(
            "/api/v1/webhooks/instagram",
            json=_ig_payload({"sender": {"id": "U1"}, "recipient": {"id": "PAGE"}, "timestamp": 1}),
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_dm_without_business_mapping(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.post(
            "/api/v1/webhooks/instagram",
            json=_ig_payload(
                {
                    "sender": {"id": "U1"},
                    "recipient": {"id": "PAGE"},
                    "timestamp": 1,
                    "message": {"mid": "M1", "text": "Bonjour"},
                }
            ),
        )
        assert r.status_code == 200, r.text  # pas de business → ignoré

    @pytest.mark.asyncio
    async def test_non_json_body_is_rejected(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.post("/api/v1/webhooks/instagram", content="pas du json {{{")
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════
#  9) webhooks twitter/snapchat
# ═══════════════════════════════════════════════════════════════════


class TestTwitterSnapchatWebhookTolerance:
    """Twitter/Snapchat acquittent tout JSON."""

    @pytest.mark.asyncio
    async def test_twitter_dm_acknowledged(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.post(
            "/api/v1/webhooks/twitter",
            json={
                "for_user_id": "BIZ",
                "direct_message_events": [
                    {
                        "type": "message_create",
                        "id": "ev1",
                        "created_timestamp": "1",
                        "message_create": {
                            "message_data": {"id": "m1", "text": "Bonjour", "sender_id": "U9"},
                            "created_timestamp": "1",
                        },
                    }
                ],
                "users": {},
            },
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_twitter_non_json_rejected(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.post("/api/v1/webhooks/twitter", content="nope {{{")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_snapchat_message_acknowledged(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.post(
            "/api/v1/webhooks/snapchat",
            json={
                "event_type": "message",
                "messages": [
                    {"id": "s1", "sender_id": "snapuser", "text": "Bonjour", "timestamp": "1"}
                ],
            },
        )
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_snapchat_non_json_rejected(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.post("/api/v1/webhooks/snapchat", content="nope {{{")
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════
#  10) reprise humaine
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_human_reply_persists_and_takes_over(
    client: AsyncClient, db_tables: None
) -> None:
    """Réponse humaine persistée + reprise."""
    token = await _register_and_verify(client, "reply-agent@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    # message entrant crée une conv
    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "c",
            "submitted_at": "2026-06-13T10:00:00Z",
            "email": "client@example.com",
            "message": "Bonjour, j'ai une question",
        },
    )
    conv_id = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0][
        "id"
    ]

    # l'agent répond
    r = await client.post(
        f"/api/v1/conversations/{conv_id}/reply",
        headers=auth,
        json={"text": "Bonjour, je vous réponds personnellement."},
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["message"]["direction"] == "outbound"
    assert res["assigned_to"]  # reprise → Jenny en pause

    # détail reflète la reprise
    detail = (await client.get(f"/api/v1/conversations/{conv_id}", headers=auth)).json()
    assert detail["assigned_to"]
    assert any(
        m["content"].startswith("Bonjour, je vous réponds") for m in detail["messages"]
    )

    # l'agent rend la main
    r_resume = await client.post(f"/api/v1/conversations/{conv_id}/resume", headers=auth)
    assert r_resume.status_code == 200, r_resume.text
    assert r_resume.json()["assigned_to"] is None
    detail2 = (await client.get(f"/api/v1/conversations/{conv_id}", headers=auth)).json()
    assert detail2["assigned_to"] is None


@pytest.mark.asyncio
async def test_awaiting_reply_flag(client: AsyncClient, db_tables: None) -> None:
    """Dernier msg entrant = à traiter."""
    token = await _register_and_verify(client, "awaiting@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "c",
            "submitted_at": "2026-06-13T10:00:00Z",
            "email": "c@example.com",
            "message": "Bonjour, une question",
        },
    )
    convs = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"]
    assert convs[0]["awaiting_reply"] is True  # dernier msg = entrant

    # l'agent répond
    cid = convs[0]["id"]
    await client.post(
        f"/api/v1/conversations/{cid}/reply", headers=auth, json={"text": "Bonjour !"}
    )
    convs2 = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"]
    assert convs2[0]["awaiting_reply"] is False  # dernier msg = sortant


@pytest.mark.asyncio
async def test_conversation_status_lifecycle(client: AsyncClient, db_tables: None) -> None:
    """Cycle de vie d'une conv."""
    token = await _register_and_verify(client, "lifecycle@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "c",
            "submitted_at": "2026-06-13T10:00:00Z",
            "email": "c@example.com",
            "message": "Bonjour, une question",
        },
    )
    cid = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0]["id"]

    # résoudre la conv
    r = await client.patch(
        f"/api/v1/conversations/{cid}/status", headers=auth, json={"status": "closed"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed"
    assert (await client.get(f"/api/v1/conversations/{cid}", headers=auth)).json()["status"] == "closed"

    # filtre par statut
    open_convs = (
        await client.get("/api/v1/conversations?status=open", headers=auth)
    ).json()["conversations"]
    assert all(c["id"] != cid for c in open_convs)
    closed_convs = (
        await client.get("/api/v1/conversations?status=closed", headers=auth)
    ).json()["conversations"]
    assert any(c["id"] == cid for c in closed_convs)

    # archiver : masquée de « Tous »
    # visible via status=archived
    await client.patch(
        f"/api/v1/conversations/{cid}/status", headers=auth, json={"status": "archived"}
    )
    assert (await client.get(f"/api/v1/conversations/{cid}", headers=auth)).json()["status"] == "archived"
    all_convs = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"]
    assert all(c["id"] != cid for c in all_convs)  # masquée de « Tous »
    archived_convs = (
        await client.get("/api/v1/conversations?status=archived", headers=auth)
    ).json()["conversations"]
    assert any(c["id"] == cid for c in archived_convs)  # visible via le filtre

    # rouvrir : réapparaît
    r_reopen = await client.patch(
        f"/api/v1/conversations/{cid}/status", headers=auth, json={"status": "open"}
    )
    assert r_reopen.json()["status"] == "open"
    reopened = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"]
    assert any(c["id"] == cid for c in reopened)

    # invalide → 422, inconnu → 404
    bad = await client.patch(
        f"/api/v1/conversations/{cid}/status", headers=auth, json={"status": "wat"}
    )
    assert bad.status_code == 422
    missing = await client.patch(
        f"/api/v1/conversations/{uuid4()}/status", headers=auth, json={"status": "closed"}
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_customer_360_view_and_annotation(client: AsyncClient, db_tables: None) -> None:
    """Fiche client : historique + notes."""
    token = await _register_and_verify(client, "fiche@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "contact",
            "submitted_at": "2026-06-13T10:00:00Z",
            "full_name": "Claire Martin",
            "email": "claire360@example.com",
            "message": "Bonjour, une question sur mes commandes.",
        },
    )
    conv = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0]
    customer_id = conv["customer_id"]
    assert customer_id, "l'ingestion d'un formulaire avec email doit créer un client"

    # vue 360°
    r = await client.get(f"/api/v1/customers/{customer_id}", headers=auth)
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["full_name"] == "Claire Martin"
    assert view["email"] == "claire360@example.com"
    assert view["stats"]["conversations"] >= 1
    assert view["stats"]["total_spent_minor"] == 0  # aucune transaction
    assert len(view["conversations"]) >= 1
    assert view["orders"] == [] and view["transactions"] == []

    # annotation : notes + tags
    patched = await client.patch(
        f"/api/v1/customers/{customer_id}",
        headers=auth,
        json={"notes": "Cliente fidèle.", "tags": ["VIP", "matin"]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["notes"] == "Cliente fidèle."
    assert patched.json()["tags"] == ["VIP", "matin"]

    # persistance
    again = (await client.get(f"/api/v1/customers/{customer_id}", headers=auth)).json()
    assert again["notes"] == "Cliente fidèle."
    assert again["tags"] == ["VIP", "matin"]

    # inconnu → 404, autre business → 404
    missing = await client.get(f"/api/v1/customers/{uuid4()}", headers=auth)
    assert missing.status_code == 404

    other_token = await _register_and_verify(client, "autre-business@example.com")
    other_auth = {"Authorization": f"Bearer {other_token}"}
    cross = await client.get(f"/api/v1/customers/{customer_id}", headers=other_auth)
    assert cross.status_code == 404  # cloisonnement multi-tenant


@pytest.mark.asyncio
async def test_csv_exports(client: AsyncClient, db_tables: None) -> None:
    """Exports CSV conv/clients."""
    token = await _register_and_verify(client, "export@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "c",
            "submitted_at": "2026-06-13T10:00:00Z",
            "full_name": "Claire Export",
            "email": "claire-export@x.com",
            "message": "Bonjour",
        },
    )

    conv_csv = await client.get("/api/v1/conversations/export.csv", headers=auth)
    assert conv_csv.status_code == 200
    assert conv_csv.headers["content-type"].startswith("text/csv")
    assert "attachment" in conv_csv.headers.get("content-disposition", "")
    assert "client,canal,statut" in conv_csv.text  # en-tête présent

    cust_csv = await client.get("/api/v1/customers/export.csv", headers=auth)
    assert cust_csv.status_code == 200
    assert "Claire Export" in cust_csv.text


@pytest.mark.asyncio
async def test_customers_list_and_search(client: AsyncClient, db_tables: None) -> None:
    """Liste clients + recherche."""
    token = await _register_and_verify(client, "cust-list@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    submissions = [
        ("Claire Martin", "claire@x.com", "2026-06-13T10:00:00Z"),
        ("Bruno Petit", "bruno@x.com", "2026-06-13T11:00:00Z"),
    ]
    for i, (name, email, ts) in enumerate(submissions):
        await client.post(
            f"/api/v1/ingest/form?business_id={bid}",
            json={
                "form_id": f"c{i}",
                "submitted_at": ts,
                "full_name": name,
                "email": email,
                "message": "Bonjour",
            },
        )

    # liste complète : 2 clients
    full = (await client.get("/api/v1/customers", headers=auth)).json()
    assert full["total"] == 2
    assert {c["full_name"] for c in full["customers"]} == {"Claire Martin", "Bruno Petit"}
    assert all(c["conversation_count"] == 1 for c in full["customers"])

    # recherche par nom
    res = (await client.get("/api/v1/customers?search=claire", headers=auth)).json()
    assert res["total"] == 1
    assert res["customers"][0]["full_name"] == "Claire Martin"

    # recherche par email
    by_email = (await client.get("/api/v1/customers?search=bruno@x", headers=auth)).json()
    assert by_email["total"] == 1
    assert by_email["customers"][0]["email"] == "bruno@x.com"

    # cloisonnement multi-tenant
    other = await _register_and_verify(client, "cust-list-other@example.com")
    other_auth = {"Authorization": f"Bearer {other}"}
    assert (await client.get("/api/v1/customers", headers=other_auth)).json()["total"] == 0


@pytest.mark.asyncio
async def test_conversation_stats_awaiting(client: AsyncClient, db_tables: None) -> None:
    """Compteur /stats des à-traiter."""
    token = await _register_and_verify(client, "stats@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    assert (await client.get("/api/v1/conversations/stats", headers=auth)).json()["awaiting"] == 0

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={"form_id": "c", "submitted_at": "2026-06-13T10:00:00Z", "email": "c@x.com", "message": "Salut"},
    )
    assert (await client.get("/api/v1/conversations/stats", headers=auth)).json()["awaiting"] == 1

    # après réponse : plus d'attente
    cid = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0]["id"]
    await client.post(f"/api/v1/conversations/{cid}/reply", headers=auth, json={"text": "Bonjour !"})
    assert (await client.get("/api/v1/conversations/stats", headers=auth)).json()["awaiting"] == 0


@pytest.mark.asyncio
async def test_sentiment_snooze_summary(client: AsyncClient, db_tables: None) -> None:
    """Sentiment, snooze, résumé."""
    token = await _register_and_verify(client, "senti@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "c",
            "submitted_at": "2026-06-13T10:00:00Z",
            "email": "c@example.com",
            "message": "C'est scandaleux et inadmissible, je veux un remboursement, arnaque !",
        },
    )
    conv = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0]
    assert conv["sentiment"] == "negative"
    assert "mécontent" in conv["tags"]

    cid = conv["id"]
    # snooze 60 min → masqué
    await client.post(f"/api/v1/conversations/{cid}/snooze", headers=auth, json={"minutes": 60})
    assert (await client.get("/api/v1/conversations", headers=auth)).json()["total"] == 0
    # annulation snooze → réapparaît
    await client.post(f"/api/v1/conversations/{cid}/snooze", headers=auth, json={"minutes": None})
    assert (await client.get("/api/v1/conversations", headers=auth)).json()["total"] == 1
    # résumé
    r = await client.post(f"/api/v1/conversations/{cid}/summarize", headers=auth)
    assert r.status_code == 200 and r.json()["summary"].strip()


@pytest.mark.asyncio
async def test_business_config_and_members(client: AsyncClient, db_tables: None) -> None:
    """Config business + membres."""
    token = await _register_and_verify(client, "cfg@example.com")
    auth = {"Authorization": f"Bearer {token}"}

    upd = await client.patch(
        "/api/v1/business/me",
        headers=auth,
        json={
            "business_hours": {"mon": ["09:00", "18:00"], "sun": None},
            "auto_reply_message": "Fermé, on revient vite.",
            "sla_minutes": 15,
        },
    )
    assert upd.status_code == 200
    body = upd.json()
    assert body["sla_minutes"] == 15
    assert body["auto_reply_message"] == "Fermé, on revient vite."

    # ajout d'un membre
    add = await client.post(
        "/api/v1/business/members",
        headers=auth,
        json={"email": "teammate@example.com", "full_name": "Co Équipier", "password": "Pass!123", "role": "agent"},
    )
    assert add.status_code == 201
    members = (await client.get("/api/v1/business/members", headers=auth)).json()
    assert any(m["email"] == "teammate@example.com" for m in members)


@pytest.mark.asyncio
async def test_channels_and_customer_import(client: AsyncClient, db_tables: None) -> None:
    """Canaux + import CSV clients."""
    token = await _register_and_verify(client, "chan@example.com")
    auth = {"Authorization": f"Bearer {token}"}

    channels = (await client.get("/api/v1/channels", headers=auth)).json()
    by_ch = {c["channel"]: c for c in channels}
    assert by_ch["form"]["connected"] is True  # intégré nativement
    # canal listé mais non raccordé
    assert by_ch["messenger"]["connected"] is False

    csv_bytes = b"nom,email,telephone\nZoe Test,zoe-imp@x.com,0600000000\nLou Test,lou-imp@x.com,\n"
    res = await client.post(
        "/api/v1/customers/import",
        headers=auth,
        files={"file": ("clients.csv", csv_bytes, "text/csv")},
    )
    assert res.status_code == 200 and res.json()["created"] == 2
    listed = (await client.get("/api/v1/customers?search=Test", headers=auth)).json()
    assert listed["total"] == 2


@pytest.mark.asyncio
async def test_insights_by_agent_and_days(client: AsyncClient, db_tables: None) -> None:
    """Insights : by_agent, KPI, days."""
    token = await _register_and_verify(client, "kpi@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={"form_id": "c", "submitted_at": "2026-06-13T10:00:00Z", "email": "c@x.com", "message": "Salut"},
    )
    cid = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0]["id"]
    await client.post(f"/api/v1/conversations/{cid}/reply", headers=auth, json={"text": "Bonjour !"})

    data = (await client.get("/api/v1/insights?days=30", headers=auth)).json()
    assert len(data["messages_last_7_days"]) == 30
    assert "by_agent" in data and "avg_first_response_minutes" in data
    assert any("cfg" in (a["agent"] or "") or a["count"] >= 1 for a in data["by_agent"])


@pytest.mark.asyncio
async def test_suggest_reply_for_conversation(client: AsyncClient, db_tables: None) -> None:
    """Brouillon de réponse suggéré."""
    token = await _register_and_verify(client, "suggest@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "c",
            "submitted_at": "2026-06-13T10:00:00Z",
            "email": "c@example.com",
            "message": "Bonjour, quels sont vos horaires ?",
        },
    )
    cid = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0]["id"]

    r = await client.post(f"/api/v1/conversations/{cid}/suggest", headers=auth)
    assert r.status_code == 200, r.text
    suggestion = r.json()["suggestion"]
    assert isinstance(suggestion, str) and suggestion.strip()  # brouillon non vide

    # inconnu → 404
    missing = await client.post(f"/api/v1/conversations/{uuid4()}/suggest", headers=auth)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_conversation_overdue_sla(client: AsyncClient, db_tables: None) -> None:
    """Attente > 30 min = en retard."""
    from jenny.domain.models.conversation import Conversation

    token = await _register_and_verify(client, "sla@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "c",
            "submitted_at": "2026-06-13T10:00:00Z",
            "email": "c@example.com",
            "message": "Bonjour",
        },
    )
    conv = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0]
    # en attente, pas en retard
    assert conv["awaiting_reply"] is True
    assert conv["overdue"] is False

    # recule d'une heure → en retard
    cid = conv["id"]
    async with async_session_factory() as s:
        await s.execute(
            update(Conversation)
            .where(Conversation.id == UUID(cid))
            .values(last_message_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await s.commit()

    conv2 = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0]
    assert conv2["overdue"] is True
    assert conv2["waiting_minutes"] is not None and conv2["waiting_minutes"] >= 60


@pytest.mark.asyncio
async def test_conversation_tags_and_filter(client: AsyncClient, db_tables: None) -> None:
    """Étiquettes : pose + filtre."""
    token = await _register_and_verify(client, "tags@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "c",
            "submitted_at": "2026-06-13T10:00:00Z",
            "email": "c@example.com",
            "message": "Bonjour",
        },
    )
    cid = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0]["id"]

    # pose avec doublons → dédoublonnées
    r = await client.patch(
        f"/api/v1/conversations/{cid}/tags",
        headers=auth,
        json={"tags": ["Urgent", "urgent", "  à relancer  ", ""]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == ["Urgent", "à relancer"]

    # détail + liste exposent
    detail = (await client.get(f"/api/v1/conversations/{cid}", headers=auth)).json()
    assert detail["tags"] == ["Urgent", "à relancer"]

    # filtre par étiquette
    tagged = (await client.get("/api/v1/conversations?tag=Urgent", headers=auth)).json()
    assert tagged["total"] == 1 and tagged["conversations"][0]["id"] == cid
    none = (await client.get("/api/v1/conversations?tag=inconnu", headers=auth)).json()
    assert none["total"] == 0


@pytest.mark.asyncio
async def test_assign_conversation_and_my_filter(client: AsyncClient, db_tables: None) -> None:
    """Attribution + filtre « à moi »."""
    token = await _register_and_verify(client, "assign@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=auth)).json()["business_id"]

    # au moins le propriétaire
    members = (await client.get("/api/v1/business/members", headers=auth)).json()
    assert any(m["email"] == "assign@example.com" for m in members)

    await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "c",
            "submitted_at": "2026-06-13T10:00:00Z",
            "email": "c@example.com",
            "message": "Bonjour",
        },
    )
    cid = (await client.get("/api/v1/conversations", headers=auth)).json()["conversations"][0]["id"]

    # pas encore à moi
    mine = (await client.get("/api/v1/conversations?assigned_to=me", headers=auth)).json()
    assert mine["total"] == 0

    # attribution à moi
    r = await client.post(
        f"/api/v1/conversations/{cid}/assign",
        headers=auth,
        json={"assignee": "assign@example.com"},
    )
    assert r.status_code == 200 and r.json()["assigned_to"] == "assign@example.com"
    mine2 = (await client.get("/api/v1/conversations?assigned_to=me", headers=auth)).json()
    assert mine2["total"] == 1 and mine2["conversations"][0]["id"] == cid

    # libération
    r2 = await client.post(
        f"/api/v1/conversations/{cid}/assign", headers=auth, json={"assignee": None}
    )
    assert r2.json()["assigned_to"] is None
    mine3 = (await client.get("/api/v1/conversations?assigned_to=me", headers=auth)).json()
    assert mine3["total"] == 0


@pytest.mark.asyncio
async def test_canned_responses_crud(client: AsyncClient, db_tables: None) -> None:
    """CRUD des réponses enregistrées."""
    token = await _register_and_verify(client, "canned@example.com")
    auth = {"Authorization": f"Bearer {token}"}

    # création
    r = await client.post(
        "/api/v1/canned-responses",
        headers=auth,
        json={"title": "Horaires", "content": "Ouvert 9h-19h.", "shortcut": "horaires"},
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["shortcut"] == "horaires"

    # liste
    items = (await client.get("/api/v1/canned-responses", headers=auth)).json()
    assert len(items) == 1 and items[0]["title"] == "Horaires"

    # mise à jour
    upd = await client.patch(
        f"/api/v1/canned-responses/{cid}", headers=auth, json={"content": "Ouvert 8h-20h."}
    )
    assert upd.status_code == 200 and upd.json()["content"] == "Ouvert 8h-20h."

    # cloisonnement multi-tenant
    other = await _register_and_verify(client, "canned-other@example.com")
    other_auth = {"Authorization": f"Bearer {other}"}
    assert (await client.get("/api/v1/canned-responses", headers=other_auth)).json() == []
    assert (
        await client.patch(
            f"/api/v1/canned-responses/{cid}", headers=other_auth, json={"title": "X"}
        )
    ).status_code == 404

    # suppression
    assert (
        await client.delete(f"/api/v1/canned-responses/{cid}", headers=auth)
    ).status_code == 204
    assert (await client.get("/api/v1/canned-responses", headers=auth)).json() == []


@pytest.mark.asyncio
async def test_sse_stream_requires_auth(client: AsyncClient) -> None:
    """Le flux SSE exige un jeton."""
    r = await client.get("/api/v1/realtime/stream")
    assert r.status_code == 401
