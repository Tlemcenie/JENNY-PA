"""pile servie : le ner ne fausse pas la résa."""

from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from jenny.core.config import get_settings
from jenny.db.session import async_session_factory
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.prestation import Prestation
from jenny.engine import factory
from jenny.engine.conversation_engine import EngineRequest
from jenny.engine.state_manager import StateManager

CKPTS = (Path("checkpoints/intent_head/head.npz"), Path("checkpoints/ner/best_model.pt"))
pytestmark = pytest.mark.skipif(not all(p.exists() for p in CKPTS), reason="checkpoints absents")

# catalogue de seed-coiffeur
CATALOG = [
    ("Coupe femme", "coupe", 45, 3900),
    ("Coupe homme", "coupe", 30, 2500),
    ("Brushing", "coiffage", 30, 2500),
    ("Coloration", "couleur", 90, 5500),
    ("Balayage", "couleur", 120, 8000),
    ("Soin profond", "soin", 30, 2000),
    ("Barbe", "barbe", 20, 1500),
]
NAMES = [c[0] for c in CATALOG]
# fermé dimanche et lundi
HOURS = {k: ["09:00", "19:00"] for k in ("tue", "wed", "thu", "fri", "sat")}
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
OUVERTS = JOURS[1:6]
PARIS = ZoneInfo("Europe/Paris")

# moteur pas encore protégé
MOTEUR_ECRASE = pytest.mark.xfail(
    strict=True, reason="moteur : ner posé sans intention ni catalogue (merge_notes)"
)
PILES = ["servi", pytest.param("avec_ner", marks=MOTEUR_ECRASE)]


def _prochain(jour: str) -> date:
    """ce jour-là, dans 1 à 6 j."""
    today = datetime.now(PARIS).date()
    if JOURS[today.weekday()] == jour:
        pytest.skip("aujourd'hui : jour ambigu")
    for k in range(1, 7):
        d = today + timedelta(days=k)
        if JOURS[d.weekday()] == jour:
            return d
    raise AssertionError(jour)


@pytest.fixture(scope="module")
def moteurs():
    """défaut et ner forcé, une fois."""
    out = {}
    for name, ner in (("servi", None), ("avec_ner", "true")):
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("JENNY_ENABLE_ML_MODELS", "true")
            mp.delenv("JENNY_INTENT_MODEL_KIND", raising=False)
            if ner is None:
                mp.delenv("JENNY_ENABLE_NER_MODEL", raising=False)
            else:
                mp.setenv("JENNY_ENABLE_NER_MODEL", ner)
            get_settings.cache_clear()
            eng = factory.build_engine(state_manager=StateManager())
            eng.response_generator = None
            out[name] = eng
    get_settings.cache_clear()
    return out


@pytest.fixture
def eng(request, moteurs):
    return moteurs[request.param]


async def _salon() -> tuple:
    async with async_session_factory() as s, s.begin():
        biz = Business(id=uuid4(), name="Salon", slug=f"p3-{uuid4().hex[:8]}", business_hours=HOURS)
        s.add(biz)
        for i, (name, cat, duree, prix) in enumerate(CATALOG):
            s.add(
                Prestation(
                    business_id=biz.id,
                    name=name,
                    category=cat,
                    duration_minutes=duree,
                    price_cents=prix,
                    sort_order=i,
                )
            )
        cust = Customer(business_id=biz.id, full_name="Léa")
        s.add(cust)
        await s.flush()
        return biz.id, cust.id


async def _parle(eng, bid, cid, msgs: list[str]):
    """une même conversation."""
    conv = uuid4()
    out = []
    for text in msgs:
        out.append(
            await eng.process(
                EngineRequest(
                    conversation_id=conv,
                    business_id=bid,
                    customer_id=cid,
                    message_text=text,
                    channel="whatsapp",
                    catalog_services=NAMES,
                    timezone="Europe/Paris",
                )
            )
        )
    return out


async def _rdvs(bid) -> list[Appointment]:
    async with async_session_factory() as s:
        rows = await s.execute(select(Appointment).where(Appointment.business_id == bid))
        return list(rows.scalars().all())


def test_pile_servie(moteurs) -> None:
    servi = moteurs["servi"]
    assert type(servi.intent_predictor).__name__ == "EmbeddingIntentPredictor"
    assert servi.ner_predictor is None
    assert moteurs["avec_ner"].ner_predictor is not None


@pytest.mark.parametrize("jour", OUVERTS)
@pytest.mark.parametrize("eng", PILES, indirect=True)
class TestQuestionPrixPendantResa:
    """prix d'une autre presta en cours de résa."""

    MSGS = (
        "Je voudrais un rendez-vous pour une coupe homme",
        "c'est combien une coupe femme ?",
        "{jour} 14h",
    )

    @pytest.mark.asyncio
    async def test_garde_la_coupe_homme(self, db_tables, eng, jour) -> None:
        d = _prochain(jour)
        bid, cid = await _salon()
        out = await _parle(eng, bid, cid, [m.format(jour=jour) for m in self.MSGS])
        assert out[0].intent == "appointment"
        assert out[1].intent in ("pricing", "quote")
        assert (out[2].action_result or {}).get("success") is True, out[2].action_result
        (appt,) = await _rdvs(bid)
        assert appt.title.startswith("Coupe homme"), appt.title
        assert appt.start_at.astimezone(PARIS).date() == d


@pytest.mark.parametrize("jour", OUVERTS)
@pytest.mark.parametrize("eng", PILES, indirect=True)
class TestHorsCatalogue:
    """presta inconnue ou floue : jenny demande."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "modele",
        [
            # hors catalogue
            "Je voudrais un rendez-vous pour un lissage brésilien {jour} à 10h",
            # femme ou homme ?
            "jvoudrais un rdv coupe {jour} 15h svp",
        ],
    )
    async def test_pas_de_rdv_devine(self, db_tables, eng, jour, modele) -> None:
        _prochain(jour)
        bid, cid = await _salon()
        (r,) = await _parle(eng, bid, cid, [modele.format(jour=jour)])
        assert r.intent == "appointment"
        assert not (r.action_result or {}).get("appointment_id"), r.action_result
        assert await _rdvs(bid) == []
