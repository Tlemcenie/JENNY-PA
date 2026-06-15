"""Vérif live du pipeline COMPLET : ML (intent+NER) + LLM (Ollama) + Postgres réel.

Joue une conversation cliente de bout en bout et vérifie qu'un VRAI rendez-vous
est créé en base. À lancer avec JENNY_DATABASE_URL pointant sur le Postgres live.
"""
import asyncio, uuid
from datetime import UTC, datetime
from sqlalchemy import select, delete
from jenny.db.session import async_session_factory
from jenny.domain.models.business import Business
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.appointment import Appointment
from jenny.engine.factory import build_engine
from jenny.engine.conversation_engine import EngineRequest

async def main():
    bid = uuid.uuid4(); cid = uuid.uuid4(); conv = uuid.uuid4()
    async with async_session_factory() as s, s.begin():
        s.add(Business(id=bid, name="Salon Live", slug=f"live-{uuid.uuid4().hex[:6]}",
                       business_hours={k:["09:00","19:00"] for k in ("mon","tue","wed","thu","fri","sat","sun")}))
        s.add(Prestation(business_id=bid, name="Coupe", price_cents=3500, duration_minutes=30))
        s.add(Prestation(business_id=bid, name="Couleur", price_cents=6000, duration_minutes=60))
        from jenny.domain.models.customer import Customer
        s.add(Customer(id=cid, business_id=bid, full_name="Client Live"))
    eng = build_engine()  # ML + Ollama + PG réels
    print("Moteur prêt. ML:", eng.intent_predictor is not None, "| NER:", eng.ner_predictor is not None,
          "| LLM:", eng.response_generator is not None)
    from jenny.services.prestation_service import format_catalog, load_active_prestations
    async with async_session_factory() as s:
        _presta = await load_active_prestations(s, bid)
        catalog = format_catalog(_presta); _svc = [p.name for p in _presta]
    turns = ["Bonjour", "Je voudrais prendre rendez-vous pour une coupe", "demain", "à 14h"]
    for t in turns:
        r = await eng.process(EngineRequest(conversation_id=conv, business_id=bid, customer_id=cid,
                                            message_text=t, channel="whatsapp", catalog=catalog, catalog_services=_svc))
        ar = r.action_result or {}
        flag = ""
        if ar.get("success") and ar.get("appointment_id"): flag = f"  [RDV CRÉÉ {ar.get('day')} {ar.get('time')}]"
        elif ar.get("propose_slots"): flag = f"  [propose: {ar.get('slots_text')}]"
        print(f"\nClient : {t}\n  intent={r.intent} conf={r.intent_confidence:.2f}\n  Jenny : {r.response_text[:160]}{flag}")
    async with async_session_factory() as s:
        appts = (await s.execute(select(Appointment).where(Appointment.business_id==bid))).scalars().all()
    print("\n=== RÉSULTAT ===")
    print(f"RDV créés en base : {len(appts)}")
    for a in appts: print(f"  - {a.title} | {a.start_at} | status={a.status} | customer={a.customer_id}")
    ok = len(appts) >= 1
    # nettoyage
    async with async_session_factory() as s, s.begin():
        await s.execute(delete(Business).where(Business.id==bid))
    print("VERDICT:", "✅ PIPELINE OK" if ok else "❌ AUCUN RDV CRÉÉ")
    return ok

asyncio.run(main())
