"""Config pytest globale : env hermétique, base isolée, réseau coupé."""

from __future__ import annotations

import contextlib
import errno
import functools
import hashlib
import ipaddress
import math
import os
import shutil
import signal
import socket
import sys
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

# ── env hermétique, avant import jenny ──

# on jette l'env hérité
for _key in list(os.environ):
    if _key.startswith("JENNY_") and not _key.startswith("JENNY_TEST_"):
        del os.environ[_key]
for _key in ("OPENAI_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT"):
    os.environ.pop(_key, None)

# base unique par process
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "main")
_TMP_DIR = Path(os.environ.get("JENNY_TEST_DB_DIR") or Path(tempfile.gettempdir()) / "jenny-pytest")
_TMP_DIR.mkdir(parents=True, exist_ok=True)
TEST_DB_PATH = _TMP_DIR / f"test-{os.getpid()}-{_WORKER}.db"
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
_RUN_DIR = _TMP_DIR / f"run-{os.getpid()}-{_WORKER}"


def _pid_alive(pid: int) -> bool:
    """Process encore vivant ?"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _sweep_stale_runs(base: Path = _TMP_DIR) -> None:
    """Vire les restes des runs morts."""
    for entry in base.iterdir():
        parts = entry.name.split("-")
        if len(parts) < 2 or parts[0] not in ("test", "run") or not parts[1].isdigit():
            continue
        pid = int(parts[1])
        # même pid = reste sale
        if pid != os.getpid() and _pid_alive(pid):
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                entry.unlink()


_sweep_stale_runs()
_RUN_DIR.mkdir(parents=True, exist_ok=True)

os.environ.update(
    {
        "JENNY_ENV": "test",
        "JENNY_DATABASE_URL": TEST_DB_URL,
        # port mort : refus immédiat
        "JENNY_REDIS_URL": "redis://127.0.0.1:1/15",
        "JENNY_SKIP_META_SIGNATURE": "true",
        "JENNY_DEFAULT_BUSINESS_ID": "",
        "JENNY_REQUIRE_AUTH": "false",
        # pas de clé = templates
        "JENNY_LLM_PROVIDER": "groq",
        "JENNY_GROQ_API_KEY": "",
        "JENNY_OPENAI_API_KEY": "",
        "JENNY_MISTRAL_API_KEY": "",
        # intentions par règles
        "JENNY_ENABLE_ML_MODELS": "false",
        # secret assez long
        "JENNY_JWT_SECRET": "jenny-tests-only-secret-0123456789abcdef",
        "JENNY_EMAIL_PREVIEW_DIR": str(_RUN_DIR / "emails"),
    }
)

# réseau ouvert sur demande
ALLOW_NETWORK = os.environ.get("JENNY_TEST_ALLOW_NETWORK") == "1"

# HF : cache local seulement
if not ALLOW_NETWORK:
    for _key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ.setdefault(_key, "1")

# .env jamais lu en test
from jenny.core import config as _config  # noqa: E402

_config.Settings.model_config["env_file"] = None
_config.get_settings.cache_clear()

# bcrypt coût mini en test
import bcrypt  # noqa: E402

_orig_gensalt = bcrypt.gensalt


def _fast_gensalt(rounds: int = 4, prefix: bytes = b"2b") -> bytes:
    """Sel bcrypt rapide (tests)."""
    return _orig_gensalt(rounds=rounds, prefix=prefix)


bcrypt.gensalt = _fast_gensalt

# ── coupe-circuit réseau LLM ──

import httpx  # noqa: E402

_LLM_HOSTS = {"api.groq.com", "api.openai.com", "api.mistral.ai"}
_OLLAMA_PORT = 11434
BLOCKED_LLM_CALLS: list[str] = []


def _is_llm_target(url: httpx.URL) -> bool:
    """Requête vers un LLM ?"""
    return url.host in _LLM_HOSTS or url.port == _OLLAMA_PORT


def _block(request: httpx.Request) -> None:
    """Note puis refuse l'appel."""
    BLOCKED_LLM_CALLS.append(str(request.url))
    raise httpx.ConnectError("réseau LLM coupé en test", request=request)


_orig_async_send = httpx.AsyncHTTPTransport.handle_async_request
_orig_sync_send = httpx.HTTPTransport.handle_request


async def _guarded_async_send(self, request):  # type: ignore[no-untyped-def]
    if _is_llm_target(request.url):
        _block(request)
    return await _orig_async_send(self, request)


def _guarded_sync_send(self, request):  # type: ignore[no-untyped-def]
    if _is_llm_target(request.url):
        _block(request)
    return _orig_sync_send(self, request)


httpx.AsyncHTTPTransport.handle_async_request = _guarded_async_send  # type: ignore[method-assign]
httpx.HTTPTransport.handle_request = _guarded_sync_send  # type: ignore[method-assign]

# ── coupe-circuit réseau global ──

BLOCKED_NET_CALLS: list[str] = []
# port 1 : redis mort voulu
_DEAD_PORT = 1
_NET_STATE = {"open": ALLOW_NETWORK}
# serveurs lancés par le test
_LOCAL_PORTS: set[int] = set()
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_sendto = socket.socket.sendto
_orig_bind = socket.socket.bind
_orig_getaddrinfo = socket.getaddrinfo
_orig_gethostbyname = socket.gethostbyname


def _is_ip(host: str) -> bool:
    """Adresse IP littérale ?"""
    try:
        ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False
    return True


def _is_loopback(host: str) -> bool:
    """Boucle locale ?"""
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return host == "localhost" or host.endswith(".localhost")


@functools.cache
def _service_endpoints() -> frozenset[tuple[str, int]]:
    """Postgres/Redis de test permis."""
    allowed: set[tuple[str, int]] = set()
    for var, port in (("JENNY_TEST_POSTGRES_URL", 5432), ("JENNY_TEST_REDIS_URL", 6379)):
        raw = os.environ.get(var, "")
        if not raw:
            continue
        url = urlsplit(raw)
        if not url.hostname:
            continue
        p = url.port or port
        allowed.add((url.hostname, p))
        with contextlib.suppress(OSError):
            for info in _orig_getaddrinfo(url.hostname, p, type=socket.SOCK_STREAM):
                allowed.add((str(info[4][0]), p))
    return frozenset(allowed)


def _net_refused(address: object) -> str | None:
    """Raison du refus, None = permis."""
    if _NET_STATE["open"] or not isinstance(address, tuple) or len(address) < 2:
        return None
    host, port = str(address[0]), int(address[1])
    if (host, port) in _service_endpoints():
        return None
    # local : port mort ou à nous
    if _is_loopback(host) and (port == _DEAD_PORT or port in _LOCAL_PORTS):
        return None
    BLOCKED_NET_CALLS.append(f"{host}:{port}")
    return f"réseau coupé en test : {host}:{port}"


def _name_refused(host: object) -> str | None:
    """Nom à résoudre interdit ?"""
    name = host.decode() if isinstance(host, bytes) else str(host or "")
    if (
        _NET_STATE["open"]
        or not name
        or _is_ip(name)
        or _is_loopback(name)
        or any(name == h for h, _ in _service_endpoints())
    ):
        return None
    BLOCKED_NET_CALLS.append(f"dns:{name}")
    return f"DNS coupé en test : {name}"


def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
    reason = _net_refused(address)
    if reason:
        raise ConnectionRefusedError(errno.ECONNREFUSED, reason)
    return _orig_connect(self, address)


def _guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
    if _net_refused(address):
        return errno.ECONNREFUSED
    return _orig_connect_ex(self, address)


def _guarded_sendto(self, data, *args):  # type: ignore[no-untyped-def]
    # udp sans connect
    reason = _net_refused(args[-1]) if args else None
    if reason:
        raise ConnectionRefusedError(errno.ECONNREFUSED, reason)
    return _orig_sendto(self, data, *args)


def _guarded_bind(self, address):  # type: ignore[no-untyped-def]
    _orig_bind(self, address)
    # serveur de test : permis
    if self.family in (socket.AF_INET, socket.AF_INET6):
        with contextlib.suppress(OSError):
            _LOCAL_PORTS.add(int(self.getsockname()[1]))


def _guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    reason = _name_refused(host)
    if reason:
        raise socket.gaierror(socket.EAI_NONAME, reason)
    return _orig_getaddrinfo(host, *args, **kwargs)


def _guarded_gethostbyname(host):  # type: ignore[no-untyped-def]
    reason = _name_refused(host)
    if reason:
        raise socket.gaierror(socket.EAI_NONAME, reason)
    return _orig_gethostbyname(host)


_NET_GUARDS = (
    (socket.socket, "connect", _guarded_connect),
    (socket.socket, "connect_ex", _guarded_connect_ex),
    (socket.socket, "sendto", _guarded_sendto),
    (socket.socket, "bind", _guarded_bind),
    (socket, "getaddrinfo", _guarded_getaddrinfo),
    (socket, "gethostbyname", _guarded_gethostbyname),
)


def install_net_guard() -> None:
    """Pose le coupe-circuit (idempotent)."""
    for owner, name, guard in _NET_GUARDS:
        setattr(owner, name, guard)


def net_guard_active() -> bool:
    """Coupe-circuit toujours en place ?"""
    return all(getattr(owner, name) is guard for owner, name, guard in _NET_GUARDS)


# dès l'import : collecte comprise
install_net_guard()

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from pytest import MonkeyPatch  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.dialects.postgresql import ARRAY  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402

from jenny.api.main import create_app  # noqa: E402
from jenny.core.config import Settings  # noqa: E402
from jenny.db.session import engine as _db_engine  # noqa: E402
from jenny.llm.providers import BaseLLMProvider, LLMResponse  # noqa: E402
from jenny.rag.embeddings import BaseEmbedder  # noqa: E402


@event.listens_for(_db_engine.sync_engine, "connect")
def _sqlite_fast(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
    """Base jetable : pas de fsync."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA synchronous=OFF")
    cur.execute("PRAGMA journal_mode=MEMORY")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


# ARRAY postgres en JSON
@compiles(ARRAY, "sqlite")
def _array_as_json_on_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


# ── timeout par test ──

_DEFAULT_TIMEOUT = 120.0


def pytest_addoption(parser: pytest.Parser, pluginmanager: pytest.PytestPluginManager) -> None:
    """Rend l'option timeout connue."""
    # plugin absent ou coupé
    if not pluginmanager.hasplugin("timeout"):
        parser.addini("timeout", "timeout par test (secours)", default=str(_DEFAULT_TIMEOUT))


def pytest_configure(config: pytest.Config) -> None:
    """Déclare les marqueurs maison."""
    config.addinivalue_line("markers", "services: besoin de Postgres/Redis réels")
    config.addinivalue_line("markers", "real_embedder: vrai embedder RAG, sans HashEmbedder")
    config.addinivalue_line("markers", "allow_network: réseau sortant permis pour ce test")
    if not config.pluginmanager.hasplugin("timeout"):
        config.addinivalue_line("markers", "timeout(seconds): timeout du test")


def _fallback_timeout(item: pytest.Item) -> float:
    """Durée max, 0 = aucune."""
    config = item.config
    if config.pluginmanager.hasplugin("timeout") or not hasattr(signal, "setitimer"):
        return 0.0
    if threading.current_thread() is not threading.main_thread():
        return 0.0
    # pas pendant un débogage
    if config.getoption("usepdb", False) or config.getoption("trace", False):
        return 0.0
    marker = item.get_closest_marker("timeout")
    try:
        raw = marker.args[0] if marker and marker.args else config.getini("timeout")
        return max(float(raw or 0), 0.0)
    except (TypeError, ValueError):
        # option inconnue : défaut
        return _DEFAULT_TIMEOUT


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):  # type: ignore[no-untyped-def]
    """Secours SIGALRM sans pytest-timeout."""
    seconds = _fallback_timeout(item)
    if not seconds:
        yield
        return

    def _on_alarm(signum, frame):  # type: ignore[no-untyped-def]
        pytest.fail(f"Timeout : test > {seconds:g} s (secours conftest)")

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # type: ignore[no-untyped-def]
    """Signale les appels réseau bloqués."""
    if BLOCKED_LLM_CALLS:
        hosts = sorted({httpx.URL(u).host for u in BLOCKED_LLM_CALLS})
        terminalreporter.write_line(
            f"jenny: {len(BLOCKED_LLM_CALLS)} appel(s) LLM bloqué(s) : {', '.join(hosts)}",
            red=True,
        )
    if BLOCKED_NET_CALLS:
        targets = sorted(set(BLOCKED_NET_CALLS))
        terminalreporter.write_line(
            f"jenny: {len(BLOCKED_NET_CALLS)} accès réseau bloqué(s) : {', '.join(targets)}",
            red=True,
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Run rouge si réseau tenté."""
    # même hors test (collecte)
    if (BLOCKED_NET_CALLS or BLOCKED_LLM_CALLS) and exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_unconfigure(config: pytest.Config) -> None:
    """Nettoie la base du run."""
    for path in TEST_DB_PATH.parent.glob(f"{TEST_DB_PATH.name}*"):
        with contextlib.suppress(OSError):
            path.unlink()
    shutil.rmtree(_RUN_DIR, ignore_errors=True)


# ── fixtures ──


@pytest.fixture(autouse=True)
def _skip_meta_signature(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("JENNY_SKIP_META_SIGNATURE", "true")


class BlockedCalls:
    """Vue sur les appels bloqués."""

    def __init__(self) -> None:
        self.start = len(BLOCKED_LLM_CALLS)

    @property
    def urls(self) -> list[str]:
        return BLOCKED_LLM_CALLS[self.start :]


@pytest.fixture
def blocked_llm_calls() -> Iterator[BlockedCalls]:
    """Appels LLM bloqués pendant le test."""
    view = BlockedCalls()
    yield view
    # voulus : hors résumé
    del BLOCKED_LLM_CALLS[view.start :]


class BlockedNet:
    """Vue sur les accès réseau bloqués."""

    def __init__(self) -> None:
        self.start = len(BLOCKED_NET_CALLS)

    @property
    def targets(self) -> list[str]:
        return BLOCKED_NET_CALLS[self.start :]


@pytest.fixture
def blocked_network() -> Iterator[BlockedNet]:
    """Accès réseau bloqués, voulus."""
    view = BlockedNet()
    yield view
    del BLOCKED_NET_CALLS[view.start :]


@pytest.fixture(autouse=True, scope="session")
def _network_guard() -> Iterator[None]:
    """Réseau coupé toute la session."""
    install_net_guard()
    yield
    # personne ne l'a retiré
    if not net_guard_active():
        raise RuntimeError("coupe-circuit réseau retiré pendant la session")


@pytest.fixture(autouse=True)
def _no_stray_network(request: pytest.FixtureRequest, _network_guard: None) -> Iterator[None]:
    """Test en échec si réseau tenté."""
    llm_start, net_start = len(BLOCKED_LLM_CALLS), len(BLOCKED_NET_CALLS)
    opened = bool(request.node.get_closest_marker("allow_network")) and not _NET_STATE["open"]
    if opened:
        _NET_STATE["open"] = True
    try:
        yield
    finally:
        if opened:
            _NET_STATE["open"] = False
    if not net_guard_active():
        install_net_guard()
        pytest.fail("coupe-circuit réseau retiré par le test", pytrace=False)
    # voulus déjà retirés
    stray = BLOCKED_LLM_CALLS[llm_start:] + BLOCKED_NET_CALLS[net_start:]
    if stray:
        pytest.fail(
            "réseau sortant en test : "
            + ", ".join(sorted(set(stray)))
            + " (fixture blocked_network/blocked_llm_calls si voulu)",
            pytrace=False,
        )


def _project_modules() -> list:
    """Modules jenny déjà chargés."""
    return [
        mod
        for name, mod in list(sys.modules.items())
        if mod is not None and name.split(".")[0] in ("jenny", "ml", "tests")
    ]


class FakeArqPool:
    """File arq en mémoire."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple, dict]] = []
        self.real_get_arq_pool = None

    async def enqueue_job(self, function: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.jobs.append((function, args, kwargs))
        return None

    async def close(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def arq_pool(monkeypatch: MonkeyPatch) -> FakeArqPool:
    """Pas de Redis : jobs notés."""
    from jenny.workers import queue

    pool = FakeArqPool()
    # vrai pool gardé sous la main
    pool.real_get_arq_pool = queue.get_arq_pool

    async def _get_pool() -> FakeArqPool:
        return pool

    monkeypatch.setattr(queue, "_pool", None)
    monkeypatch.setattr(queue, "get_arq_pool", _get_pool)
    return pool


class HashEmbedder(BaseEmbedder):
    """Embedder léger et déterministe."""

    dimension = 768  # comme mpnet

    async def embed_text(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for word in text.lower().split():
            digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
            vec[int.from_bytes(digest, "big") % self.dimension] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_text(t) for t in texts]


# vrai modèle sur demande
REAL_EMBEDDER = os.environ.get("JENNY_TEST_REAL_EMBEDDER") == "1"


def seed_hash_embedder() -> BaseEmbedder:
    """HashEmbedder dans le vrai cache."""
    from jenny.rag import embeddings

    # vraie fonction, vrai cache
    current = embeddings.get_default_embedder()
    if isinstance(current, HashEmbedder):
        return current
    fake = HashEmbedder()
    with embeddings._DEFAULT_LOCK:
        for key, value in list(embeddings._DEFAULT_EMBEDDERS.items()):
            if value is current:
                embeddings._DEFAULT_EMBEDDERS[key] = fake
    if embeddings.get_default_embedder() is not fake:
        raise RuntimeError("cache embedder introuvable : adapter seed_hash_embedder")
    return fake


@pytest.fixture(autouse=True)
def _hash_embedder(request: pytest.FixtureRequest) -> Iterator[None]:
    """RAG léger, sauf marqueur real_embedder."""
    from jenny.rag import embeddings

    if request.node.get_closest_marker("real_embedder"):
        # vrai embedder, cache vierge
        embeddings.reset_default_embedder()
        yield
        embeddings.reset_default_embedder()
        return
    if not REAL_EMBEDDER:
        seed_hash_embedder()
    yield


async def reset_schema(*, create: bool = True) -> None:
    """Vide puis recrée le schéma."""
    import jenny.domain.models  # noqa: F401
    from jenny.db.base import Base
    from jenny.db.session import engine

    async with engine.begin() as conn:
        # reste éventuel : on repart
        await conn.run_sync(Base.metadata.drop_all)
        if create:
            await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
async def db_tables() -> AsyncIterator[None]:
    """Schéma neuf pour le test."""
    await reset_schema()
    yield
    await reset_schema(create=False)


class FakeLLMProvider(BaseLLMProvider):
    """LLM déterministe pour les tests."""

    def __init__(self, replies: list[str] | None = None, default: str = "") -> None:
        self.replies = list(replies or [])
        self.default = default or "Avec plaisir, je regarde ça pour vous."
        self.calls: list[dict] = []

    @property
    def model_name(self) -> str:
        return "fake-llm"

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        content = self.replies.pop(0) if self.replies else self.default
        return LLMResponse(content=content, model=self.model_name)

    async def embed(self, text: str) -> list[float]:
        return [0.0] * 8


@pytest.fixture
def fake_llm(monkeypatch: MonkeyPatch) -> FakeLLMProvider:
    """Branche un faux LLM partout."""
    from jenny.engine import factory
    from jenny.llm import providers

    fake = FakeLLMProvider()
    original = providers.get_default_llm_provider
    for mod in _project_modules():
        if getattr(mod, "get_default_llm_provider", None) is original:
            monkeypatch.setattr(mod, "get_default_llm_provider", lambda: fake)
    # moteur reconstruit avec lui
    monkeypatch.setattr(factory, "_engine_singleton", None)
    return fake


@pytest.fixture
def test_settings() -> Settings:
    """Settings configurés pour les tests."""
    return Settings(
        env="test",
        debug=True,
        log_level="DEBUG",
        database_url=TEST_DB_URL,
        redis_url="redis://127.0.0.1:1/15",
    )


@pytest.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    """Client HTTP async pour tester les routes FastAPI."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
