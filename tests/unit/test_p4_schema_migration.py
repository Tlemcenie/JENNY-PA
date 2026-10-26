"""Migration jen_drift_m6n7 et downgrade initial, sans base."""

from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path
from typing import TYPE_CHECKING

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

import jenny.domain.models  # noqa: F401
from jenny.db.base import Base

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "migrations" / "versions"


def _load(name: str) -> ModuleType:
    """Charge un fichier de migration."""
    spec = importlib.util.spec_from_file_location(f"mig_{name}", VERSIONS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _load("m6n7o8p9q0r1_schema_drift")
INITIAL = _load("3d09b043955c_initial_schema")


def _sql(fn, dialect: str = "postgresql") -> str:  # type: ignore[no-untyped-def]
    """SQL rendu en mode --sql."""
    buf = io.StringIO()
    ctx = MigrationContext.configure(
        dialect_name=dialect, opts={"as_sql": True, "output_buffer": buf}
    )
    with Operations.context(ctx):
        fn()
    return buf.getvalue()


def _statements(sql: str) -> list[str]:
    """Une ligne par ordre SQL."""
    return [" ".join(s.split()) for s in sql.split(";") if s.strip()]


def test_chainee_apres_staff_skills() -> None:
    """Une seule tête, qui passe par la révision."""
    assert MIG.revision == "jen_drift_m6n7"
    assert MIG.down_revision == "jen_staffsk_l5m6"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {r.revision for r in script.iterate_revisions(heads[0], "base")}
    assert {"jen_drift_m6n7", "jen_staffsk_l5m6"} <= chain


def test_not_null_comme_les_modeles() -> None:
    """Chaque colonne visée est NOT NULL au modèle."""
    tables = Base.metadata.tables
    cols = [(t, c) for t, by_col in MIG.NOT_NULL.items() for c in by_col]
    assert len(cols) == 20
    for table, col in cols:
        column = tables[table].c[col]
        assert column.nullable is False, f"{table}.{col}"
        # l'ORM pose toujours une valeur
        assert column.default is not None or column.server_default is not None, col


def test_commentaires_comme_les_modeles() -> None:
    """Texte posé = texte du modèle."""
    tables = Base.metadata.tables
    assert len(MIG.COMMENTS) == 35
    for (table, col), (old, new) in MIG.COMMENTS.items():
        assert tables[table].c[col].comment == new, f"{table}.{col}"
        assert old != new


def test_commentaires_base_seule_dans_les_modeles() -> None:
    """Commentaires gardés : déclarés au modèle."""
    tables = Base.metadata.tables
    expected = {
        ("customer_addresses", "label"): "billing, shipping, home",
        ("customer_addresses", "country"): "ISO 3166-1 alpha-2",
        ("customer_documents", "storage_uri"): "S3, chemin local, ou URL signée",
        ("customer_transactions", "provider"): "stripe, paypal, manual, …",
        ("orders", "reference"): "Référence métier unique par business",
        ("orders", "total_amount_minor"): "Montant total en plus petite unité",
        ("payments", "provider"): "stripe, paypal",
    }
    for (table, col), comment in expected.items():
        assert tables[table].c[col].comment == comment, f"{table}.{col}"


def test_upgrade_remplit_puis_verrouille() -> None:
    """UPDATE des NULL avant SET NOT NULL."""
    stmts = _statements(_sql(MIG.upgrade))
    for table, by_col in MIG.NOT_NULL.items():
        alter = next(i for i, s in enumerate(stmts) if s.startswith(f"ALTER TABLE {table} "))
        for col, fill in by_col.items():
            upd = stmts.index(f"UPDATE {table} SET {col} = {fill} WHERE {col} IS NULL")
            assert upd < alter
            assert f"ALTER COLUMN {col} SET NOT NULL" in stmts[alter]
    # dates : l'autre date d'abord
    assert MIG.NOT_NULL["prestations"]["created_at"].startswith("coalesce(updated_at")
    assert "DROP INDEX IF EXISTS ix_webhook_deliveries_dedup_key" in stmts


def test_upgrade_commentaires_echappes() -> None:
    """Apostrophes doublées, accents gardés."""
    sql = _sql(MIG.upgrade)
    assert (
        "COMMENT ON COLUMN businesses.auto_reply_message IS "
        "'Message envoyé automatiquement hors horaires d''ouverture'"
    ) in sql
    assert "COMMENT ON COLUMN message_events.payload IS 'Données associées à l''événement'" in sql
    assert len(re.findall(r"COMMENT ON COLUMN", sql)) == len(MIG.COMMENTS)


def test_downgrade_remet_l_etat_d_avant() -> None:
    """NULL permis, index et commentaires d'avant."""
    stmts = _statements(_sql(MIG.downgrade))
    for table, by_col in MIG.NOT_NULL.items():
        alter = next(s for s in stmts if s.startswith(f"ALTER TABLE {table} "))
        for col in by_col:
            assert f"ALTER COLUMN {col} DROP NOT NULL" in alter
    assert (
        "CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_dedup_key "
        "ON webhook_deliveries (dedup_key)"
    ) in stmts
    assert "COMMENT ON COLUMN businesses.phone IS NULL" in stmts
    assert "COMMENT ON COLUMN businesses.email IS 'Email principal'" in stmts
    # rien ne s'efface en descente
    assert not any(s.startswith(("UPDATE", "DELETE", "DROP TABLE")) for s in stmts)


def test_hors_postgres_rien() -> None:
    """Chaîne Postgres seulement."""
    assert _sql(MIG.upgrade, "sqlite") == ""
    assert _sql(MIG.downgrade, "sqlite") == ""


def _fk_parents(create_sql: str) -> dict[str, set[str]]:
    """Table -> tables pointées."""
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\)", create_sql, re.S):
        out[m.group(1)] = set(re.findall(r"REFERENCES (\w+)", m.group(2))) - {m.group(1)}
    return out


def test_downgrade_initial_respecte_les_fk() -> None:
    """Enfant supprimé avant parent."""
    parents = _fk_parents(_sql(INITIAL.upgrade))
    assert "businesses" in parents["document_embeddings"]
    drops = re.findall(r"DROP TABLE (\w+)", _sql(INITIAL.downgrade))
    assert sorted(drops) == sorted(parents)
    for child, refs in parents.items():
        for parent in refs:
            assert drops.index(child) < drops.index(parent), f"{child} avant {parent}"
