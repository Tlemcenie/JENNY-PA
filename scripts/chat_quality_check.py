"""Contrôle qualité du chat : conversation multi-tours réaliste, réponses verbatim."""
import asyncio
import uuid

from sqlalchemy import delete

from jenny.db.session import async_session_factory
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.prestation import Prestation
from jenny.engine.conversation_engine import EngineRequest
from jenny.engine.factory import build_engine


async def main():
    bid = uuid.uuid4()
    cid = uuid.uuid4()
    conv = uuid.uuid4()
    async with async_session_factory() as s, s.begin():
        s.add(Business(id=bid, name="Studio Lina", slug=f"q-{uuid.uuid4().hex[:6]}",
                       business_hours={k:["09:00","19:00"] for k in ("mon","tue","wed","thu","fri","sat","sun")}))
        s.add(Prestation(business_id=bid, name="Coupe femme", price_cents=4500, duration_minutes=45))
        s.add(Prestation(business_id=bid, name="Balayage", price_cents=9000, duration_minutes=120))
        s.add(Customer(id=cid, business_id=bid, full_name="Sophie"))
    eng=build_engine()
    from jenny.services.prestation_service import format_catalog, load_active_prestations
    async with async_session_factory() as s:
        pres = await load_active_prestations(s, bid)
        cat = format_catalog(pres)
        svc = [p.name for p in pres]
    turns=["Bonjour !","C'est combien un balayage ?","ok je voudrais réserver alors","demain","à 14h","merci beaucoup !"]
    for t in turns:
        r=await eng.process(EngineRequest(conversation_id=conv,business_id=bid,customer_id=cid,
                                          message_text=t,channel="whatsapp",catalog=cat,catalog_services=svc))
        print(f"\n👤 {t}\n🤖 {r.response_text}")
    async with async_session_factory() as s, s.begin():
        await s.execute(delete(Business).where(Business.id==bid))
asyncio.run(main())
