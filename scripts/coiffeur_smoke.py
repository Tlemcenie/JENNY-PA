"""Smoke live du parcours coiffeur (2 modèles + slot-filling + booking + tarifs).

NON inclus dans la suite : nécessite Ollama + les checkpoints ML. SQLite jetable.
"""

import os

os.environ["JENNY_DATABASE_URL"] = "sqlite+aiosqlite:///coiffeur_smoke.db"
os.environ["JENNY_REDIS_URL"] = "redis://localhost:6390/1"
os.environ["JENNY_ENABLE_ML_MODELS"] = "true"
os.environ["JENNY_LLM_PROVIDER"] = "llama"
os.environ["JENNY_LLM_MODEL"] = "qwen2.5:3b"

import asyncio  # noqa: E402
import warnings  # noqa: E402
from uuid import uuid4  # noqa: E402

warnings.filterwarnings("ignore")

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import ARRAY  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(ARRAY, "sqlite")
def _arr(el, comp, **kw):
    return "JSON"


import jenny.domain.models  # noqa: E402,F401
from jenny.db.base import Base  # noqa: E402
from jenny.db.session import async_session_factory, engine  # noqa: E402
from jenny.domain.models.appointment import Appointment  # noqa: E402
from jenny.domain.models.business import Business  # noqa: E402
from jenny.domain.models.prestation import Prestation  # noqa: E402
from jenny.engine.conversation_engine import EngineRequest  # noqa: E402
from jenny.engine.factory import build_engine  # noqa: E402
from jenny.services.prestation_service import (  # noqa: E402
    format_catalog,
    load_active_prestations,
)


async def main() -> None:
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    bid = uuid4()
    async with async_session_factory() as s, s.begin():
        s.add(Business(id=bid, name="Studio Lina", slug=f"sl-{uuid4().hex[:6]}", timezone="Europe/Paris"))
        s.add_all([
            Prestation(business_id=bid, name="Coupe femme", category="coupe", duration_minutes=45, price_cents=3900, sort_order=1),
            Prestation(business_id=bid, name="Coupe homme", category="coupe", duration_minutes=30, price_cents=2500, sort_order=2),
            Prestation(business_id=bid, name="Balayage", category="couleur", duration_minutes=120, price_cents=8000, sort_order=3),
            Prestation(business_id=bid, name="Coloration", category="couleur", duration_minutes=90, price_cents=5500, sort_order=4),
        ])

    eng = build_engine()
    conv = uuid4()

    async def send(msg: str) -> None:
        async with async_session_factory() as s:
            cat = format_catalog(await load_active_prestations(s, bid))
        r = await eng.process(
            EngineRequest(
                conversation_id=conv, business_id=bid, message_text=msg,
                business_name="Studio Lina", catalog=cat,
            )
        )
        print(f"\nClient : {msg}")
        print(f"   [intent={r.intent} | clarif={r.clarification_reason or '-'} | gap={r.knowledge_gap}]")
        print(f"   Jenny : {(r.response_text or '')[:200]}")
        print(f"   action_result={r.action_result}")

    print("===== TARIF (depuis le catalogue) =====")
    await send("Bonjour, c'est combien un balayage ?")
    print("\n===== PRISE DE RDV (slot-filling multi-tours) =====")
    await send("Je voudrais prendre rendez-vous pour une coloration s'il vous plaît")
    await send("mardi prochain")
    await send("à 14h")

    async with async_session_factory() as s:
        n = (await s.execute(select(func.count(Appointment.id)).where(Appointment.business_id == bid))).scalar_one()
        appts = (await s.execute(select(Appointment).where(Appointment.business_id == bid))).scalars().all()
    print(f"\n>>> Rendez-vous créés en base : {n}")
    for a in appts:
        print(f"    • {a.title} | {a.start_at} → {a.end_at} | canal={a.channel}")


asyncio.run(main())
