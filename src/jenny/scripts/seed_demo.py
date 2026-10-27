"""Seed des données de démonstration Jenny.

Crée un environnement fonctionnel pour tester localement :
- 1 utilisateur démo (email/mot de passe) déjà rattaché à un business
- 1 salon de coiffure actif (slug : `demo`) : horaires, acompte, catalogue
- La KB coiffeur du salon démo (fiche horaires tirée de ses horaires)
- Quelques clients, conversations, messages, commandes et tickets

Idempotent : si le user `demo@jenny.ai` existe déjà, le script ne fait rien.
On peut le forcer avec `--force` (purge puis recrée).

Lancement :

    python -m jenny.scripts.seed_demo
    python -m jenny.scripts.seed_demo --force
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from jenny.api.auth.password_utils import hash_password
from jenny.core.logging import get_logger, setup_logging
from jenny.db.session import async_session_factory
from jenny.domain.models import (
    Business,
    BusinessMember,
    Conversation,
    Customer,
    Message,
    Order,
    SupportTicket,
    User,
)
from jenny.domain.models.prestation import Prestation
from jenny.rag.kb_coiffeur import DEFAULT_COIFFEUR, SEED_TAG, build_entries, load_salon
from jenny.rag.knowledge_base import KnowledgeBase

logger = get_logger(__name__)

DEMO_EMAIL = "demo@jenny.ai"
DEMO_PASSWORD = "Demo!1234"
DEMO_BUSINESS_SLUG = "demo"

# horaires du salon démo
DEMO_HOURS: dict[str, list[str] | None] = {
    "mon": None,
    "tue": ["09:00", "19:00"],
    "wed": ["09:00", "19:00"],
    "thu": ["09:00", "21:00"],
    "fri": ["09:00", "19:00"],
    "sat": ["09:00", "18:00"],
    "sun": None,
}
# en plus du catalogue type
_DEMO_EXTRA_PRESTATIONS: list[tuple[str, str, int, int]] = [
    ("Dégradé à la lame", "coupe", 26, 1200),
]


async def _purge_demo() -> None:
    """Supprime l'utilisateur et le business démo (cascade naturel via FK)."""
    async with async_session_factory() as session:
        biz = (
            await session.execute(select(Business).where(Business.slug == DEMO_BUSINESS_SLUG))
        ).scalar_one_or_none()
        if biz is not None:
            await session.execute(delete(Business).where(Business.id == biz.id))
        await session.execute(delete(User).where(User.email == DEMO_EMAIL))
        await session.commit()
        logger.info("seed.demo.purged")


async def _seed() -> uuid.UUID | None:
    """Crée le user + business démo (et données associées). Retourne l'id du
    business créé, ou ``None`` si le compte démo existait déjà (idempotence)."""
    async with async_session_factory() as session:
        existing = (
            await session.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("seed.demo.user_exists", email=DEMO_EMAIL)
            return None

        biz_id = uuid.uuid4()
        business = Business(
            id=biz_id,
            name="Jenny Demo Boutique",
            slug=DEMO_BUSINESS_SLUG,
            email="contact@demo.jenny.ai",
            is_active=True,
            business_hours=DEMO_HOURS,
            deposit_enabled=True,
            deposit_percent=25,
            deposit_min_cents=1000,
        )
        session.add(business)
        await session.flush()

        # catalogue du salon
        catalog = [*DEFAULT_COIFFEUR, *_DEMO_EXTRA_PRESTATIONS]
        for order, (name, category, duration, price_cents) in enumerate(catalog):
            session.add(
                Prestation(
                    business_id=business.id,
                    name=name,
                    category=category,
                    duration_minutes=duration,
                    price_cents=price_cents,
                    is_active=True,
                    sort_order=order,
                )
            )

        user = User(
            id=uuid.uuid4(),
            email=DEMO_EMAIL,
            full_name="Jenny Demo",
            password_hash=hash_password(DEMO_PASSWORD),
            email_verified=True,
        )
        session.add(user)
        await session.flush()

        session.add(
            BusinessMember(
                user_id=user.id,
                business_id=business.id,
                role="owner",
            )
        )

        now = datetime.now(UTC)
        customers: list[Customer] = []
        for i, profile in enumerate(
            [
                {
                    "full_name": "Alice Martin",
                    "email": "alice@example.com",
                    "phone": "+33611111111",
                    "tags": ["vip"],
                },
                {
                    "full_name": "Bob Durand",
                    "email": "bob@example.com",
                    "phone": "+33622222222",
                    "tags": ["prospect"],
                },
                {
                    "full_name": "Chloé Robert",
                    "email": "chloe@example.com",
                    "phone": "+33633333333",
                    "tags": [],
                },
            ]
        ):
            c = Customer(
                business_id=business.id,
                first_seen_at=now - timedelta(days=10 + i),
                last_seen_at=now - timedelta(hours=i),
                **profile,
            )
            session.add(c)
            customers.append(c)
        await session.flush()

        for i, customer in enumerate(customers):
            conv = Conversation(
                business_id=business.id,
                customer_id=customer.id,
                channel=("whatsapp", "instagram", "email")[i % 3],
                status="open",
                current_intent="faq",
                message_count=2,
                last_message_at=now,
            )
            session.add(conv)
            await session.flush()

            session.add_all(
                [
                    Message(
                        conversation_id=conv.id,
                        business_id=business.id,
                        customer_id=customer.id,
                        external_message_id=f"demo-{conv.id}-1",
                        channel=conv.channel,
                        direction="inbound",
                        sender_name=customer.full_name,
                        sender_email=customer.email,
                        content_text="Bonjour, vous avez de la place samedi pour une coupe ?",
                        status="received",
                        source_created_at=now - timedelta(minutes=5),
                        received_at=now - timedelta(minutes=5),
                    ),
                    Message(
                        conversation_id=conv.id,
                        business_id=business.id,
                        customer_id=customer.id,
                        external_message_id=f"demo-{conv.id}-2",
                        channel=conv.channel,
                        direction="outbound",
                        sender_name="Jenny",
                        content_text=(
                            "Bonjour ! Oui, il reste des créneaux samedi matin. "
                            "Je vous en propose quelques-uns ?"
                        ),
                        status="responded",
                        source_created_at=now - timedelta(minutes=4),
                        received_at=now - timedelta(minutes=4),
                    ),
                ]
            )

        session.add(
            Order(
                business_id=business.id,
                customer_id=customers[0].id,
                reference="CMD-DEMO-0001",
                status="paid",
                currency="EUR",
                total_amount_minor=12990,
                metadata_={"items": [{"sku": "PACK-S", "qty": 1}]},
            )
        )

        session.add(
            SupportTicket(
                business_id=business.id,
                customer_id=customers[1].id,
                subject="Suivi commande CMD-DEMO-0001",
                status="open",
                priority="medium",
            )
        )

        await session.commit()
        logger.info(
            "seed.demo.done",
            email=DEMO_EMAIL,
            password=DEMO_PASSWORD,
            business=DEMO_BUSINESS_SLUG,
        )
        return biz_id


async def _seed_knowledge(business_id: uuid.UUID) -> None:
    """KB coiffeur du salon démo.

    Tirée des données en base (horaires, prestations, acompte...) + les
    fiches inventées du salon démo. Best-effort : sans pgvector ou sans
    encodeur, on log sans bloquer le seed.
    """
    try:
        async with async_session_factory() as session:
            business, prestas, _staff = await load_salon(session, business_id)
            entries = build_entries(business, prestas, demo=True)
            kb = KnowledgeBase(business_id=business_id, session=session)
            chunks: list[dict] = []
            for e in entries:
                chunks += await kb.prepare_chunks(
                    e["content"],
                    knowledge_id=str(uuid.uuid4()),
                    title=e["title"],
                    category=e["category"],
                    source="text",
                    extra_metadata={"kb_key": e["key"], "seed": SEED_TAG},
                )
            # tout d'un coup
            await kb.vector_store.add_chunks(session, business_id, chunks)
            await session.commit()
        logger.info("seed.demo.knowledge_done", entries=len(entries), chunks=len(chunks))
    except Exception as exc:
        logger.warning("seed.demo.knowledge_skipped", error=str(exc))


async def seed_demo(force: bool = False) -> None:
    """Seed idempotent du compte démo (user + business + connaissances).

    Réutilisable : appelé par la CLI et par l'auto-seed au démarrage de l'API.
    """
    if force:
        await _purge_demo()
    business_id = await _seed()
    if business_id is not None:
        await _seed_knowledge(business_id)


async def main(force: bool) -> None:
    setup_logging()
    await seed_demo(force=force)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Jenny demo data")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Purge l'utilisateur/business démo avant de re-seeder.",
    )
    args = parser.parse_args()
    asyncio.run(main(force=args.force))
