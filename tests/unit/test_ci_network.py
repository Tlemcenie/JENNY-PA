"""Coupe-circuit réseau des tests : tout est bloqué sauf le local à nous."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import httpx
import pytest

from tests.conftest import _NET_GUARDS, _net_refused, net_guard_active

ROOT = Path(__file__).resolve().parents[2]
# ip documentaire, jamais routée
FAR_IP = "192.0.2.10"


def _run_pytest(
    tmp_path: Path, body: str, *args: str, extra_env: dict[str, str] | None = None
) -> tuple[int, str]:
    """Lance un mini pytest isolé."""
    (tmp_path / "test_mini.py").write_text(textwrap.dedent(body))
    env = {**os.environ, **(extra_env or {}), "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}"}
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


def test_garde_posee() -> None:
    """Toutes les fonctions sont gardées."""
    assert net_guard_active()
    names = {name for _, name, _ in _NET_GUARDS}
    assert {"connect", "connect_ex", "sendto", "getaddrinfo", "gethostbyname"} <= names


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
    with pytest.raises(socket.gaierror):
        socket.gethostbyname("api.stripe.com")
    assert blocked_network.targets == ["dns:graph.facebook.com", "dns:api.stripe.com"]


def test_udp_externe_refuse(blocked_network) -> None:
    """UDP sans connect : coupé aussi."""
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
        pytest.raises(ConnectionRefusedError),
    ):
        sock.sendto(b"x", (FAR_IP, 53))
    assert blocked_network.targets == [f"{FAR_IP}:53"]


async def test_httpx_externe_refuse(blocked_network) -> None:
    """httpx vers Meta : coupé."""
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("https://graph.facebook.com/v21.0/me")
    assert "dns:graph.facebook.com" in blocked_network.targets


@pytest.fixture
def no_test_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans URL de test déclarée."""
    from tests import conftest

    # cache réel laissé intact
    monkeypatch.setattr(conftest, "_service_endpoints", frozenset)


def test_services_locaux_refuses(blocked_network, no_test_services) -> None:
    """Postgres/Redis/Ollama/API locaux : coupés."""
    for port in (5432, 5433, 6379, 6381, 11434, 8000):
        with pytest.raises(ConnectionRefusedError, match="réseau coupé"):
            socket.create_connection(("127.0.0.1", port), timeout=1)
    assert blocked_network.targets == [
        "127.0.0.1:5432",
        "127.0.0.1:5433",
        "127.0.0.1:6379",
        "127.0.0.1:6381",
        "127.0.0.1:11434",
        "127.0.0.1:8000",
    ]


def test_serveur_du_test_permis(blocked_network) -> None:
    """Serveur local lancé ici : ok."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def _echo() -> None:
            conn, _ = srv.accept()
            with conn:
                conn.sendall(conn.recv(2))

        t = threading.Thread(target=_echo, daemon=True)
        t.start()
        with socket.create_connection(("127.0.0.1", port), timeout=2) as cli:
            cli.sendall(b"ok")
            assert cli.recv(2) == b"ok"
        t.join(2)
    assert blocked_network.targets == []


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


def test_services_de_test_permis(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL de test déclarée : permise."""
    from tests import conftest

    try:
        with monkeypatch.context() as mp:
            mp.setenv("JENNY_TEST_POSTGRES_URL", "postgresql+asyncpg://u:p@127.0.0.1:55432/x")
            mp.setenv("JENNY_TEST_REDIS_URL", "redis://localhost:56379/0")
            conftest._service_endpoints.cache_clear()
            assert _net_refused(("127.0.0.1", 55432)) is None
            assert _net_refused(("127.0.0.1", 56379)) is None
    finally:
        # env remis avant le recalcul
        conftest._service_endpoints.cache_clear()


def test_services_declares_sans_effet_sur_le_reste(blocked_network, monkeypatch) -> None:
    """Services CI déclarés : reste coupé."""
    from tests import conftest

    # comme le job CI
    try:
        with monkeypatch.context() as mp:
            mp.setenv("JENNY_TEST_POSTGRES_URL", "postgresql+asyncpg://u:p@localhost:5432/jenny")
            mp.setenv("JENNY_TEST_REDIS_URL", "redis://localhost:6379/0")
            conftest._service_endpoints.cache_clear()
            assert _net_refused(("127.0.0.1", 5432)) is None
            assert _net_refused(("127.0.0.1", 6379)) is None
            assert _net_refused(("localhost", 6379)) is None
            for port in (5433, 6381, 11434, 8000):
                assert _net_refused(("127.0.0.1", port))
            assert _net_refused((FAR_IP, 5432))
    finally:
        conftest._service_endpoints.cache_clear()
    assert blocked_network.targets == [
        "127.0.0.1:5433",
        "127.0.0.1:6381",
        "127.0.0.1:11434",
        "127.0.0.1:8000",
        f"{FAR_IP}:5432",
    ]


def test_services_locaux_refuses_sous_env_ci(tmp_path: Path) -> None:
    """Env du job CI : test vert."""
    ci_env = {
        "JENNY_TEST_POSTGRES_URL": "postgresql+asyncpg://u:p@localhost:5432/jenny",
        "JENNY_TEST_REDIS_URL": "redis://localhost:6379/0",
    }
    code, out = _run_pytest(
        tmp_path,
        """
        from tests.unit.test_ci_network import *  # noqa: F403
        """,
        "-k",
        "services_locaux_refuses and not sous_env_ci",
        extra_env=ci_env,
    )
    assert code == 0, out
    assert "1 passed" in out


def test_hf_hors_ligne() -> None:
    """Hugging Face jamais joint."""
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


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


def test_reseau_a_la_collecte_fait_echouer(tmp_path: Path) -> None:
    """Hors test aussi : run rouge."""
    code, out = _run_pytest(
        tmp_path,
        """
        import socket

        # à l'import du module
        try:
            socket.getaddrinfo("example.com", 443)
        except OSError:
            pass

        def test_rien():
            assert True
        """,
    )
    assert code == 1, out
    assert "1 passed" in out
    assert "dns:example.com" in out


def test_garde_retiree_fait_echouer(tmp_path: Path) -> None:
    """Test qui retire la garde : rouge."""
    code, out = _run_pytest(
        tmp_path,
        """
        import socket

        from tests import conftest

        def test_retire():
            socket.socket.connect = conftest._orig_connect
        """,
    )
    assert code == 1, out
    assert "coupe-circuit réseau retiré par le test" in out
