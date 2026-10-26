"""refus après un report raté : vrai moteur."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time
from tests.e2e.test_p3_moteur_aurevoir_offre import (
    _WD,
    _appts,
    _at,
    _Chat,
    _client_rdv,
    _day,
    _FixedIntent,
    _local,
    _seed,
    _waitlist,
    db_tables,  # noqa: F401
)

# il garde son rdv, sans « à demain »
_REFUS = [
    "Non merci, je reste sur demain",
    "Tant pis, je garde demain alors, merci !",
    "Laissez tomber, demain c'est très bien",
    "Ah non pas après-demain finalement, je garde demain",
    "Tant pis, je garde demain 10h alors, merci !",
    "Non merci, je reste sur demain 10h",
    "Bon, demain 10h ça me va très bien",
    "Non merci, je ne veux plus décaler, je garde demain",
    "Je reste sur demain comme prévu",
    "Laissez tomber",
    "Non merci",
    "demain alors",
    "Non merci, je ne veux plus décaler",
]
_MODELS = [None, "appointment", "manage_appointment", "closing", "general"]


@pytest.fixture
def utc_tz(monkeypatch):
    """sqlite : dates naïves lues en UTC"""
    # comme Postgres en prod
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _model(chat: _Chat, model: str | None) -> None:
    """modèle fixé pour ce tour"""
    if model:
        chat.eng.intent_predictor = _FixedIntent(model)


def _no_move(r) -> None:
    assert (r.action_result or {}).get("operation") != "reschedule"
    assert r.intent != "appointment"


class TestRefusApresReport:
    @pytest.mark.parametrize("model", _MODELS)
    @pytest.mark.parametrize("msg", _REFUS)
    @pytest.mark.asyncio
    async def test_rdv_du_fil_garde(self, db_tables, msg: str, model) -> None:  # noqa: F811
        # rdv pris ici, report en conflit
        biz = await _seed(block=(2, 12, 17))
        chat = _Chat(biz)
        r1 = await chat.say("je réserve une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("success") is True
        r2 = await chat.say("je voudrais décaler à après-demain 14h")
        assert (r2.action_result or {}).get("conflict") is True
        assert (r2.action_result or {}).get("alternatives_text")
        _model(chat, model)
        r3 = await chat.say(msg)
        _no_move(r3)
        (appt,) = await _appts(biz)
        assert _local(appt.start_at) == _at(1, 10)
        # personne prévenu à tort
        assert await _waitlist(biz) == ["waiting"]

    @pytest.mark.parametrize("model", _MODELS)
    @pytest.mark.parametrize("msg", _REFUS)
    @pytest.mark.asyncio
    async def test_client_connu_rdv_en_base(self, db_tables, utc_tz, msg: str, model) -> None:  # noqa: F811
        # rdv hors du fil (whatsapp)
        biz = await _seed(block=(2, 12, 17))
        cust = await _client_rdv(biz, 1, 10)
        chat = _Chat(biz, customer_id=cust.id)
        r1 = await chat.say("Je peux décaler à après-demain 14h ?")
        assert (r1.action_result or {}).get("conflict") is True
        _model(chat, model)
        r2 = await chat.say(msg)
        _no_move(r2)
        (appt,) = await _appts(biz)
        assert _local(appt.start_at) == _at(1, 10)
        assert await _waitlist(biz) == ["waiting"]

    @pytest.mark.asyncio
    async def test_puis_nouveau_report_redemande(self, db_tables) -> None:  # noqa: F811
        # vieux créneau pas rejoué
        biz = await _seed(block=(2, 12, 17))
        chat = _Chat(biz)
        await chat.say("je réserve une coupe femme demain à 10h")
        await chat.say("je voudrais décaler à après-demain 14h")
        await chat.say("Non merci, je reste sur demain")
        r = await chat.say("je voudrais décaler mon rdv")
        assert r.intent == "manage_appointment"
        assert (r.action_result or {}).get("need_when") is True
        (appt,) = await _appts(biz)
        assert _local(appt.start_at) == _at(1, 10)

    @pytest.mark.asyncio
    async def test_refus_puis_autre_creneau_deplace(self, db_tables) -> None:  # noqa: F811
        # « non, plutôt X » : vrai report
        biz = await _seed(block=(2, 12, 17))
        chat = _Chat(biz)
        await chat.say("je réserve une coupe femme demain à 10h")
        r1 = await chat.say("je voudrais décaler à après-demain 14h")
        alt = (r1.action_result or {})["alternatives_text"].split(",")[0]
        day, hour = parse_fr_date(alt, today=_day(0)), parse_fr_time(alt)
        assert day and hour
        r2 = await chat.say(f"Non, plutôt {_WD[day.weekday()]} {hour.hour}h{hour.minute:02d}")
        assert (r2.action_result or {}).get("operation") == "reschedule"
        assert (r2.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        local = _local(appt.start_at)
        assert (local.date(), local.hour, local.minute) == (day, hour.hour, hour.minute)

    @pytest.mark.asyncio
    async def test_meme_jour_autre_heure_deplace(self, db_tables) -> None:  # noqa: F811
        # même jour, autre heure : report
        biz = await _seed(block=(2, 12, 17))
        chat = _Chat(biz)
        await chat.say("je réserve une coupe femme demain à 10h")
        await chat.say("je voudrais décaler à après-demain 14h")
        r = await chat.say("et demain 16h ?")
        assert (r.action_result or {}).get("operation") == "reschedule"
        assert (r.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        assert _local(appt.start_at) == _at(1, 16)


class TestRefusApresReservationRatee:
    @pytest.mark.parametrize("model", [None, "appointment", "closing", "general"])
    @pytest.mark.parametrize(
        "msg", ["Non merci, je vais réfléchir", "Laissez tomber", "Tant pis", "Non merci"]
    )
    @pytest.mark.asyncio
    async def test_conflit_puis_refus(self, db_tables, msg: str, model) -> None:  # noqa: F811
        biz = await _seed(block=(1, 9, 12))
        chat = _Chat(biz)
        r1 = await chat.say("je voudrais une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("conflict") is True
        _model(chat, model)
        r2 = await chat.say(msg)
        assert r2.intent != "appointment"
        assert await _appts(biz) == []

    @pytest.mark.asyncio
    async def test_deuxieme_rdv_jour_du_premier(self, db_tables) -> None:  # noqa: F811
        # 2e rdv : son 1er ne compte pas
        biz = await _seed(block=(2, 12, 17))
        chat = _Chat(biz)
        r1 = await chat.say("je réserve une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("success") is True
        r2 = await chat.say("je voudrais réserver une autre coupe femme après-demain à 14h")
        assert (r2.action_result or {}).get("conflict") is True
        r3 = await chat.say("demain alors")
        assert (r3.action_result or {}).get("success") is True
        starts = sorted(_local(a.start_at) for a in await _appts(biz))
        assert starts == [_at(1, 10), _at(1, 14)]

    @pytest.mark.asyncio
    async def test_refus_puis_report_du_vieux_rdv(self, db_tables) -> None:  # noqa: F811
        # « non, plutôt décaler » : on redemande
        biz = await _seed(block=(1, 9, 12))
        cust = await _client_rdv(biz, 3, 10)
        chat = _Chat(biz, customer_id=cust.id)
        r1 = await chat.say("je voudrais une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("conflict") is True
        r2 = await chat.say("Non merci, je voudrais plutôt décaler mon rdv")
        assert r2.intent == "manage_appointment"
        assert (r2.action_result or {}).get("need_when") is True
        r3 = await chat.say("demain 15h")
        assert (r3.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        assert _local(appt.start_at) == _at(1, 15)

    @pytest.mark.asyncio
    async def test_refus_puis_autre_heure_reserve(self, db_tables) -> None:  # noqa: F811
        biz = await _seed(block=(1, 9, 12))
        chat = _Chat(biz)
        await chat.say("je voudrais une coupe femme demain à 10h")
        r = await chat.say("Non, plutôt demain 15h")
        assert (r.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        assert _local(appt.start_at) == _at(1, 15)
        assert appt.end_at - appt.start_at == timedelta(minutes=45)


class TestRechanger:
    @pytest.mark.parametrize(
        "first",
        [
            "Bonjour, je voudrais rechanger l'heure de mon rdv",
            "je dois rechanger la date de mon rdv",
            "Je peux échanger de jour pour mon rendez-vous ?",
        ],
    )
    @pytest.mark.asyncio
    async def test_rechanger_deplace_sans_doublon(self, db_tables, first: str) -> None:  # noqa: F811
        # report, pas un 2e rdv
        biz = await _seed()
        cust = await _client_rdv(biz, 1, 10)
        chat = _Chat(biz, customer_id=cust.id)
        r1 = await chat.say(first)
        assert r1.intent == "manage_appointment"
        target = _day(3)
        await chat.say(f"{_WD[target.weekday()]} 16h")
        await chat.say("c'est une coupe femme")
        (appt,) = await _appts(biz)
        assert _local(appt.start_at) == _at(3, 16)
