"""Seed des données de démonstration Jenny.

Crée un environnement fonctionnel pour tester localement :
- 1 utilisateur démo (email/mot de passe) déjà rattaché à un business
- 1 business actif (slug : `demo`)
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
from jenny.rag.knowledge_base import KnowledgeBase

logger = get_logger(__name__)

DEMO_EMAIL = "demo@jenny.ai"
DEMO_PASSWORD = "Demo!1234"
DEMO_BUSINESS_SLUG = "demo"

# Entrées (titre, catégorie, contenu) ajoutées à la base de connaissances du
# business démo. Vectorisées via l'embedder configuré : Jenny s'y réfère (RAG).
_DEMO_KNOWLEDGE: list[tuple[str, str, str]] = [
    (
        "Horaires d'ouverture",
        "horaires",
        "La boutique est ouverte du lundi au samedi de 9h à 19h. "
        "Fermée le dimanche et les jours fériés. "
        "Le service client répond aux messages 7j/7 de 8h à 22h.",
    ),
    (
        "Livraison et frais de port",
        "tarifs",
        "Livraison standard en France métropolitaine : 4,90 € (offerte dès 50 € "
        "d'achat), en 2 à 4 jours ouvrés. Livraison express 24h à Paris : 9,90 €. "
        "Nous livrons aussi en Belgique et au Luxembourg (6,90 €).",
    ),
    (
        "Retours et remboursements",
        "politique",
        "Vous disposez de 30 jours pour retourner un article non utilisé dans son "
        "emballage d'origine. Le remboursement est effectué sous 14 jours après "
        "réception du retour. Les frais de retour sont offerts pour un article défectueux.",
    ),
    (
        "Moyens de paiement",
        "faq",
        "Nous acceptons les cartes Visa, Mastercard et American Express, ainsi que "
        "PayPal et Apple Pay. Le paiement en 3 fois sans frais est disponible dès "
        "100 € d'achat.",
    ),
    (
        "Nos services",
        "services",
        "Jenny Demo Boutique propose la vente de prêt-à-porter, un service de "
        "retouches sur mesure, des conseils de style personnalisés en boutique et "
        "la réservation de créneaux d'essayage privés.",
    ),
]


async def _purge_demo() -> None:
    """Supprime l'utilisateur et le business démo (cascade naturel via FK)."""
    async with async_session_factory() as session:
        biz = (
            await session.execute(
                select(Business).where(Business.slug == DEMO_BUSINESS_SLUG)
            )
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
        )
        session.add(business)
        await session.flush()

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
                        content_text="Bonjour, est-ce que vous livrez à Paris ce week-end ?",
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
                            "Bonjour ! Oui, livraison Paris en 24h, "
                            "je vous prépare un devis."
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
    """Ajoute des entrées de base de connaissances pour le business démo.

    Vectorisé via l'embedder configuré (Ollama par défaut). Best-effort : si
    l'embedder est indisponible, on log un avertissement sans bloquer le seed.
    """
    try:
        async with async_session_factory() as session:
            kb = KnowledgeBase(business_id=business_id, session=session)
            for title, category, content in _DEMO_KNOWLEDGE:
                await kb.add_text(content=content, title=title, category=category)
        logger.info("seed.demo.knowledge_done", entries=len(_DEMO_KNOWLEDGE))
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
