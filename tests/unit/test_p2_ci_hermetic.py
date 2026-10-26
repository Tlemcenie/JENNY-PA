"""Env de test, passe 2 : vrai singleton, réseau coupé, timeout sûr."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from jenny.engine import factory
from jenny.rag import embeddings, knowledge_base
from jenny.rag.embeddings import SentenceTransformerEmbedder
from tests.conftest import (
    _DEFAULT_TIMEOUT,
    HashEmbedder,
    _fallback_timeout,
    _net_refused,
)

ROOT = Path(__file__).resolve().parents[2]
# ip documentaire, jamais routée
FAR_IP = "192.0.2.10"


def _run_pytest(tmp_path: Path, body: str, *args: str) -> tuple[int, str]:
    """Lance un mini pytest isolé."""
    (tmp_path / "test_mini.py").write_text(textwrap.dedent(body))
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}"}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(tmp_path / "test_mini.py"),
            "-p",
            "tests.conftest",
            "-p",
            "no:cacheprovider",
            "-q",
            "--rootdir",
            str(tmp_path),
            *args,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


# ── embedder : vraie fonction ──


def test_singleton_jamais_remplace() -> None:
    """Personne ne patche la fonction."""
    real = embeddings.get_default_embedder
    assert real.__module__ == "jenny.rag.embeddings"
    assert factory.get_default_embedder is real
    assert knowledge_base.get_default_embedder is real


def test_hash_dans_le_vrai_cache() -> None:
    """Le cache de prod sert le hash."""
    emb = embeddings.get_default_embedder()
    assert isinstance(emb, HashEmbedder)
    assert any(v is emb for v in embeddings._DEFAULT_EMBEDDERS.values())
    # retriever du moteur aussi
    assert factory.build_retriever().embedder is emb


@pytest.mark.real_embedder
def test_marqueur_vrai_embedder() -> None:
    """Marqueur : vrai embedder, paresseux."""
    emb = embeddings.get_default_embedder()
    assert type(emb) is SentenceTransformerEmbedder
    assert emb is embeddings.get_default_embedder()
    assert emb.dimension == 768


# ── sqlite comme postgres ──


async def test_sqlite_refuse_fk_orpheline(db_tables) -> None:
    """Clé étrangère vérifiée en test."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from sqlalchemy.exc import IntegrityError

    from jenny.db.session import async_session_factory
    from jenny.domain.models.appointment import Appointment

    start = datetime(2031, 3, 4, 10, tzinfo=UTC)
    async with async_session_factory() as session:
        # salon inexistant
        session.add(
            Appointment(
                business_id=uuid4(),
                title="Coupe",
                start_at=start,
                end_at=start + timedelta(hours=1),
            )
        )
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            await session.flush()


# ── réseau coupé ──


def test_ip_externe_refusee(blocked_network) -> None:
    """Connexion sortante : refus net."""
    start = time.monotonic()
    with pytest.raises(ConnectionRefusedError, match="réseau coupé"):
        socket.create_connection((FAR_IP, 443), timeout=5)
    assert blocked_network.targets == [f"{FAR_IP}:443"]
    assert time.monotonic() - start < 1


def test_dns_externe_refuse(blocked_network) -> None:
    """Pas de résolution DNS."""
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("graph.facebook.com", 443)
    assert blocked_network.targets == ["dns:graph.facebook.com"]


async def test_httpx_externe_refuse(blocked_network) -> None:
    """httpx vers Meta : coupé."""
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("https://graph.facebook.com/v21.0/me")
    assert "dns:graph.facebook.com" in blocked_network.targets


def test_services_locaux_refuses(blocked_network) -> None:
    """Postgres/Redis/Ollama locaux : coupés."""
    for port in (5433, 6381, 11434, 8000):
        with pytest.raises(ConnectionRefusedError, match="réseau coupé"):
            socket.create_connection(("127.0.0.1", port), timeout=1)
    assert blocked_network.targets == [
        "127.0.0.1:5433",
        "127.0.0.1:6381",
        "127.0.0.1:11434",
        "127.0.0.1:8000",
    ]


def test_port_mort_et_unix_permis(blocked_network) -> None:
    """Redis mort et socket unix : ok."""
    # vrai refus de l'os
    with pytest.raises(ConnectionRefusedError) as exc:
        socket.create_connection(("127.0.0.1", 1), timeout=1)
    assert "réseau coupé" not in str(exc.value)
    a, b = socket.socketpair()
    with a, b:
        a.sendall(b"ok")
        assert b.recv(2) == b"ok"
    assert blocked_network.targets == []


def test_hf_hors_ligne() -> None:
    """Hugging Face jamais joint."""
    assert os.environ["HF_HUB_OFFLINE"] == "1"


@pytest.mark.allow_network
def test_marqueur_allow_network() -> None:
    """Marqueur : guard levé, sans connexion."""
    assert _net_refused((FAR_IP, 443)) is None


def test_reseau_non_voulu_fait_echouer(tmp_path: Path) -> None:
    """Accès oublié : test en échec."""
    code, out = _run_pytest(
        tmp_path,
        """
        import socket

        def test_fuite():
            try:
                socket.create_connection(("192.0.2.10", 80), timeout=1)
            except OSError:
                pass
        """,
    )
    assert code == 1, out
    assert "réseau sortant en test : 192.0.2.10:80" in out
    assert "1 passed, 1 error" in out


# ── timeout de secours ──


def test_timeout_sans_option_ini() -> None:
    """Option ini absente : pas de crash."""

    def _no_ini(name: str) -> object:
        raise ValueError(f"unknown configuration value: {name!r}")

    config = SimpleNamespace(
        pluginmanager=SimpleNamespace(hasplugin=lambda name: False),
        getoption=lambda name, default=None: False,
        getini=_no_ini,
    )
    item = SimpleNamespace(config=config, get_closest_marker=lambda name: None)
    assert _fallback_timeout(item) == _DEFAULT_TIMEOUT  # type: ignore[arg-type]


def test_timeout_plugin_coupe(tmp_path: Path) -> None:
    """-p no:timeout : le secours prend le relais."""
    start = time.monotonic()
    code, out = _run_pytest(
        tmp_path,
        """
        import time

        def test_lent():
            time.sleep(30)
        """,
        "-p",
        "no:timeout",
        "-o",
        "timeout=1",
    )
    assert code == 1, out
    assert "INTERNALERROR" not in out
    assert "secours conftest" in out
    assert "1 failed" in out
    assert time.monotonic() - start < 25
