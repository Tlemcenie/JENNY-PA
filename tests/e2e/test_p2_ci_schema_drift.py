"""Dérive ORM / migrations sur le vrai Postgres migré (CI)."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

PG_URL = os.environ.get("JENNY_TEST_POSTGRES_URL", "")
ROOT = Path(__file__).resolve().parents[2]

pytestmark = [
    pytest.mark.services,
    pytest.mark.skipif(not PG_URL, reason="JENNY_TEST_POSTGRES_URL absent"),
]

# dérive connue (passe 2), à résorber
KNOWN_DRIFT = frozenset(
    {
        # nullable : modèle != migration
        "modify_nullable:business_closures.created_at",
        "modify_nullable:business_closures.updated_at",
        "modify_nullable:businesses.is_active",
        "modify_nullable:conversations.is_escalated",
        "modify_nullable:conversations.message_count",
        "modify_nullable:customer_facts.created_at",
        "modify_nullable:customer_facts.updated_at",
        "modify_nullable:knowledge_gaps.created_at",
        "modify_nullable:knowledge_gaps.updated_at",
        "modify_nullable:messages.attachment_count",
        "modify_nullable:messages.has_attachments",
        "modify_nullable:messages.urgency_flag",
        "modify_nullable:pending_questions.created_at",
        "modify_nullable:pending_questions.updated_at",
        "modify_nullable:prestations.created_at",
        "modify_nullable:prestations.updated_at",
        "modify_nullable:reviews.created_at",
        "modify_nullable:reviews.updated_at",
        "modify_nullable:waitlist_entries.created_at",
        "modify_nullable:waitlist_entries.updated_at",
        # index posés à la main
        "remove_index:ix_customer_transactions_business_occurred",
        "remove_index:ix_customer_transactions_provider_external",
        "remove_index:ix_orders_business_reference",
        "remove_index:ix_support_tickets_business_reference",
        "remove_index:ix_webhook_deliveries_dedup_key",
        "remove_constraint:uq_payments_provider_external",
    }
)
# commentaires : sans effet runtime
IGNORED_KINDS = {"modify_comment"}


def _env_filter():  # type: ignore[no-untyped-def]
    """include_object de migrations/env.py."""
    tree = ast.parse((ROOT / "migrations" / "env.py").read_text(encoding="utf-8"))
    names = {"_TABLES_HORS_ORM", "_INDEX_HORS_ORM", "include_object"}
    keep = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in names)
        or (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id in names for t in node.targets)
        )
    ]
    ns: dict[str, object] = {}
    # sans lancer les migrations
    exec(compile(ast.Module(body=keep, type_ignores=[]), "migrations/env.py", "exec"), ns)
    return ns["include_object"]


def _flat(diffs: list) -> list[tuple]:
    """Aplati les groupes modify_*."""
    out: list[tuple] = []
    for d in diffs:
        out.extend(d if isinstance(d, list) else [d])
    return out


def _key(op: tuple) -> str:
    """Op en texte stable."""
    kind = op[0]
    if kind in ("add_table", "remove_table", "add_index", "remove_index"):
        return f"{kind}:{op[1].name}"
    if kind in ("add_column", "remove_column"):
        return f"{kind}:{op[2]}.{op[3].name}"
    if kind in ("add_constraint", "remove_constraint", "add_fk", "remove_fk"):
        obj = op[1]
        cols = ",".join(c.name for c in obj.columns)
        return f"{kind}:{obj.name or f'{obj.table.name}({cols})'}"
    if kind.startswith("modify_"):
        return f"{kind}:{op[2]}.{op[3]}"
    return f"{kind}:{op!r}"


async def _diffs() -> list[tuple]:
    """Ops autogenerate contre la base."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    import jenny.domain.models  # noqa: F401
    from jenny.db.base import Base

    include = _env_filter()

    def _compare(conn) -> list:  # type: ignore[no-untyped-def]
        ctx = MigrationContext.configure(
            connection=conn, opts={"include_object": include, "compare_type": True}
        )
        return compare_metadata(ctx, Base.metadata)

    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return _flat(await conn.run_sync(_compare))
    finally:
        await engine.dispose()


@pytest.mark.filterwarnings("ignore::sqlalchemy.exc.SAWarning")
async def test_pas_de_nouvelle_derive() -> None:
    """Modèle sans migration : CI rouge."""
    found = {_key(op) for op in await _diffs() if op[0] not in IGNORED_KINDS}
    new = sorted(found - KNOWN_DRIFT)
    assert new == [], "révision alembic manquante (ou KNOWN_DRIFT à revoir)"


def test_filtre_env_charge() -> None:
    """Filtre lu sans migrer."""
    include = _env_filter()
    assert include(None, "document_embeddings", "table", True, None) is False
    assert include(None, "users", "table", True, None) is True
