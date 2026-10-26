"""Dérive ORM / migrations sur le vrai Postgres migré (CI).

Zéro dérive exigée, commentaires compris : même règle que
``alembic check`` (bloquant en CI). Modèle changé sans révision = rouge.
"""

from __future__ import annotations

import os

import pytest

PG_URL = os.environ.get("JENNY_TEST_POSTGRES_URL", "")

pytestmark = [
    pytest.mark.services,
    pytest.mark.skipif(not PG_URL, reason="JENNY_TEST_POSTGRES_URL absent"),
]

# dérive connue : vide depuis jen_drift_m6n7
# (cliquet : toute entrée doit disparaître)
KNOWN_DRIFT: frozenset[str] = frozenset()
# alembic check compte tout, commentaires compris
IGNORED_KINDS: frozenset[str] = frozenset()


def _flat(diffs: list) -> list[tuple]:
    """Aplatit les groupes modify_*."""
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


async def _drift() -> set[str]:
    """Ops autogenerate, filtre de env.py."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    import jenny.domain.models  # noqa: F401
    from jenny.db.base import Base
    from jenny.db.schema_filter import include_name, include_object

    def _compare(conn) -> list:  # type: ignore[no-untyped-def]
        ctx = MigrationContext.configure(
            connection=conn,
            opts={
                "include_object": include_object,
                "include_name": include_name,
                "compare_type": True,
            },
        )
        return compare_metadata(ctx, Base.metadata)

    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            ops = _flat(await conn.run_sync(_compare))
    finally:
        await engine.dispose()
    return {_key(op) for op in ops if op[0] not in IGNORED_KINDS}


@pytest.mark.filterwarnings("ignore::sqlalchemy.exc.SAWarning")
async def test_pas_de_nouvelle_derive() -> None:
    """Modèle sans migration : CI rouge."""
    found = await _drift()
    assert sorted(found - KNOWN_DRIFT) == [], "révision alembic manquante"
    # dérive résorbée : liste à réduire
    assert sorted(KNOWN_DRIFT - found) == [], "retirer de KNOWN_DRIFT"


def test_env_utilise_le_filtre() -> None:
    """env.py branche le même filtre."""
    from pathlib import Path

    env = (Path(__file__).resolve().parents[2] / "migrations" / "env.py").read_text()
    assert "from jenny.db.schema_filter import include_name, include_object" in env
    assert env.count("include_object=include_object") == 2
