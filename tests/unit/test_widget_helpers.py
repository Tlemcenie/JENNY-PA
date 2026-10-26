"""Tests des petits helpers du widget."""

from __future__ import annotations

from uuid import uuid4

from jenny.api.routes.public_chat import (
    _clean_text,
    _public_payment,
    _public_quote,
    _to_public,
    conversation_id_for,
    quick_replies,
)
from jenny.engine.conversation_engine import EngineResponse


class TestQuickReplies:
    def test_no_question_no_reply(self) -> None:
        assert quick_replies("Parfait, à bientôt.") == []

    def test_day(self) -> None:
        assert quick_replies("Quel jour vous arrange ?") == ["Aujourd'hui", "Demain", "Ce samedi"]

    def test_time(self) -> None:
        assert quick_replies("À quelle heure ?")[0] == "En matinée"

    def test_service(self) -> None:
        assert quick_replies("Quelle prestation souhaitez-vous ?") == [
            "Une coupe",
            "Une couleur",
            "Un balayage",
        ]

    def test_yes_no(self) -> None:
        assert quick_replies("Je vous réserve mardi 10h, ça vous va ?") != []
        assert quick_replies("Ça vous convient ?") == ["Oui", "Non"]


class TestPublicShape:
    def test_quote_whitelist(self) -> None:
        ar = {
            "quote_id": str(uuid4()),
            "reference": "DV-1",
            "items": [{"name": "Coupe", "price_eur": 30, "duration_minutes": 30, "x": 1}],
            "total_eur": 30,
            "emailed": True,
        }
        q = _public_quote(ar)
        assert q is not None
        assert q.model_dump() == {
            "reference": "DV-1",
            "lines": [{"name": "Coupe", "price_eur": 30.0}],
            "total_eur": 30.0,
        }

    def test_no_quote_without_id(self) -> None:
        assert _public_quote({"items": [{"name": "Coupe", "price_eur": 30}]}) is None

    def test_payment_https_only(self) -> None:
        assert (
            _public_payment({"deposit": {"checkout_url": "http://evil", "amount_eur": 9}}) is None
        )
        assert _public_payment({"deposit": {"checkout_url": "javascript:alert(1)"}}) is None
        p = _public_payment({"deposit": {"checkout_url": "https://pay.example/x", "amount_eur": 9}})
        assert p is not None and p.url == "https://pay.example/x" and p.amount_eur == 9.0

    def test_to_public_drops_internals(self) -> None:
        res = EngineResponse(
            response_text="Quel jour vous arrange ?",
            intent="appointment",
            entities={"phone": "0611"},
            action_result={"appointment_id": "abc", "success": True},
            agent_used="planning",
        )
        out = _to_public(res).model_dump()
        assert set(out) == {"response", "quick_replies", "handoff", "human", "quote", "payment"}
        assert out["quick_replies"] and out["handoff"] is False
        assert "abc" not in str(out) and "0611" not in str(out)


class TestHelpers:
    def test_clean_text(self) -> None:
        assert _clean_text("  a\x00b‮c\n d  ") == "abc\n d"

    def test_stable_id(self) -> None:
        bid = uuid4()
        assert conversation_id_for(bid, "v" * 20) == conversation_id_for(bid, "v" * 20)
        assert conversation_id_for(bid, "v" * 20) != conversation_id_for(bid, "w" * 20)
