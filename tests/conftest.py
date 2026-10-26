"""Config pytest globale : env hermétique, base isolée, réseau LLM coupé."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import math
import os
import shutil
import signal
import sys
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

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

# modèle HF en cache : hors ligne
_HF_HUB = Path(
    os.environ.get("HF_HUB_CACHE")
    or Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
)
if (_HF_HUB / "models--sentence-transformers--paraphrase-multilingual-mpnet-base-v2").is_dir():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

# .env jamais lu en test
from jenny.core import config as _config  # noqa: E402

_config.Settings.model_config["env_file"] = None
_config.get_settings.cache_clear()

# choix LLM hors du dépôt
from jenny.llm import runtime as _llm_runtime  # noqa: E402

_llm_runtime._STORE = _RUN_DIR / "llm_choice.json"
_llm_runtime._active_key = None

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

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from pytest import MonkeyPatch  # noqa: E402
from sqlalchemy.dialects.postgresql import ARRAY  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402

from jenny.api.main import create_app  # noqa: E402
from jenny.core.config import Settings  # noqa: E402
from jenny.llm.providers import BaseLLMProvider, LLMResponse  # noqa: E402
from jenny.rag.embeddings import BaseEmbedder  # noqa: E402


# ARRAY postgres en JSON
@compiles(ARRAY, "sqlite")
def _array_as_json_on_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


# ── timeout par test ──

_HAS_TIMEOUT_PLUGIN = importlib.util.find_spec("pytest_timeout") is not None
_DEFAULT_TIMEOUT = 120.0


def pytest_addoption(parser: pytest.Parser) -> None:
    """Rend l'option timeout connue."""
    if not _HAS_TIMEOUT_PLUGIN:
        parser.addini("timeout", "timeout par test (secours)", default=str(_DEFAULT_TIMEOUT))


def pytest_configure(config: pytest.Config) -> None:
    """Déclare les marqueurs maison."""
    config.addinivalue_line("markers", "services: besoin de Postgres/Redis réels")
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
    raw = marker.args[0] if marker and marker.args else config.getini("timeout")
    try:
        return max(float(raw or 0), 0.0)
    except (TypeError, ValueError):
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
    """Signale les appels LLM bloqués."""
    if BLOCKED_LLM_CALLS:
        hosts = sorted({httpx.URL(u).host for u in BLOCKED_LLM_CALLS})
        terminalreporter.write_line(
            f"jenny: {len(BLOCKED_LLM_CALLS)} appel(s) LLM bloqué(s) : {', '.join(hosts)}",
            yellow=True,
        )


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


@pytest.fixture(autouse=True)
def _reset_llm_choice() -> Iterator[None]:
    """Choix LLM remis à zéro."""
    yield
    _llm_runtime._active_key = None
    with contextlib.suppress(OSError):
        _llm_runtime._STORE.unlink()


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


@pytest.fixture(autouse=True, scope="session")
def _shared_embedder() -> Iterator[None]:
    """Embedder RAG unique par session."""
    from jenny.rag import embeddings

    original = embeddings.get_default_embedder
    # vrai modèle sur demande
    real = os.environ.get("JENNY_TEST_REAL_EMBEDDER") == "1"
    cache: dict[tuple[str, str, str], BaseEmbedder] = {}

    def _cached() -> BaseEmbedder:
        s = _config.get_settings()
        key = (s.embeddings_backend, s.embeddings_model, s.llama_base_url)
        if key not in cache:
            cache[key] = original() if real else HashEmbedder()
        return cache[key]

    mp = MonkeyPatch()
    for mod in _project_modules():
        if getattr(mod, "get_default_embedder", None) is original:
            mp.setattr(mod, "get_default_embedder", _cached)
    yield
    mp.undo()


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
