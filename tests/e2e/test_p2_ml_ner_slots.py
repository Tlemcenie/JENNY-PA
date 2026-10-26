"""head + ner réactivé, vraie résa."""

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

pytestmark = pytest.mark.skipif(
    not (
        Path("checkpoints/intent_head/head.npz").exists()
        and Path("checkpoints/ner/best_model.pt").exists()
    ),
    reason="checkpoints absents",
)

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
PARIS = ZoneInfo("Europe/Paris")


def _jour_ouvert() -> tuple[str, date]:
    """un jour ouvert, 2 à 7 j."""
    today = datetime.now(PARIS).date()
    for k in range(2, 8):
        d = today + timedelta(days=k)
        if d.weekday() in (1, 2, 3, 4, 5):
            return JOURS[d.weekday()], d
    raise AssertionError("pas de jour ouvert")


@pytest.fixture
def engine(monkeypatch):
    """head + ner, réactivé à la main."""
    monkeypatch.setenv("JENNY_ENABLE_ML_MODELS", "true")
    monkeypatch.delenv("JENNY_INTENT_MODEL_KIND", raising=False)
    # coupé par défaut
    monkeypatch.setenv("JENNY_ENABLE_NER_MODEL", "true")
    get_settings.cache_clear()
    eng = factory.build_engine(state_manager=StateManager())
    eng.response_generator = None
    yield eng
    get_settings.cache_clear()


async def _salon() -> tuple:
    async with async_session_factory() as s, s.begin():
        biz = Business(id=uuid4(), name="Salon", slug=f"p2-{uuid4().hex[:8]}", business_hours=HOURS)
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


async def _send(eng, bid, cid, text):
    return await eng.process(
        EngineRequest(
            conversation_id=uuid4(),
            business_id=bid,
            customer_id=cid,
            message_text=text,
            channel="whatsapp",
            catalog_services=NAMES,
            timezone="Europe/Paris",
        )
    )


class TestServiceParNer:
    """presta du catalogue, phrase libre."""

    def test_reglages_de_service(self, engine) -> None:
        assert type(engine.intent_predictor).__name__ == "EmbeddingIntentPredictor"
        assert engine.ner_predictor is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "modele",
        [
            "jvoudrais un rdv coupe homme {jour} 15h svp",
            "je veux reserver une coupe homme pour {jour} 11h",
        ],
    )
    async def test_coupe_reservee(self, db_tables, engine, modele) -> None:
        bid, cid = await _salon()
        jour, d = _jour_ouvert()
        r = await _send(engine, bid, cid, modele.format(jour=jour))
        assert r.intent == "appointment"
        assert (r.action_result or {}).get("success") is True, r.action_result
        async with async_session_factory() as s:
            appt = (
                await s.execute(select(Appointment).where(Appointment.business_id == bid))
            ).scalar_one()
        # « coupe » seule : voir test_p3_ml_ner_resa
        assert appt.title.startswith("Coupe homme"), appt.title
        assert appt.start_at.astimezone(PARIS).date() == d


class TestDateParNer:
    """planning : le jour demandé."""

    @pytest.mark.asyncio
    async def test_jour_demande(self, db_tables, engine) -> None:
        bid, cid = await _salon()
        jour, d = _jour_ouvert()
        r = await _send(engine, bid, cid, f"Vous avez de la place {jour} ?")
        assert r.intent == "planning"
        assert (r.action_result or {}).get("requested_date") == d.isoformat()

    @pytest.mark.asyncio
    async def test_jour_ferme(self, db_tables, engine) -> None:
        bid, cid = await _salon()
        r = await _send(engine, bid, cid, "Vous êtes ouverts dimanche ?")
        assert r.intent == "planning"
        assert (r.action_result or {}).get("closed") is True, r.action_result
