import asyncio, uuid
from sqlalchemy import delete
from jenny.db.session import async_session_factory
from jenny.domain.models.business import Business
from jenny.domain.models.prestation import Prestation
from jenny.engine.factory import build_engine
from jenny.engine.conversation_engine import EngineRequest

async def main():
    bid=uuid.uuid4(); cid=uuid.uuid4(); conv=uuid.uuid4()
    async with async_session_factory() as s, s.begin():
        s.add(Business(id=bid, name="Salon", slug=f"dbg-{uuid.uuid4().hex[:6]}",
                       business_hours={k:["09:00","19:00"] for k in ("mon","tue","wed","thu","fri","sat","sun")}))
        s.add(Prestation(business_id=bid, name="Coupe", price_cents=3500, duration_minutes=30))
    eng=build_engine()
    from jenny.services.prestation_service import load_active_prestations
    async with async_session_factory() as s:
        svc=[p.name for p in await load_active_prestations(s, bid)]
    for t in ["Je voudrais prendre rendez-vous pour une coupe","demain","à 14h"]:
        r=await eng.process(EngineRequest(conversation_id=conv,business_id=bid,customer_id=cid,
                                          message_text=t,channel="whatsapp",catalog_services=svc))
        st=eng.state_manager.get(conv)
        slots={k:v.value for k,v in st.slots.items() if v.filled}
        ar={k:v for k,v in (r.action_result or {}).items() if not str(k).startswith('_')}
        print(f"\n>> {t!r}  intent={r.intent}")
        print(f"   slots={slots}")
        print(f"   action_result={ar}")
    async with async_session_factory() as s, s.begin():
        await s.execute(delete(Business).where(Business.id==bid))
asyncio.run(main())
