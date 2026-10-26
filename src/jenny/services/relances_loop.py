"""Boucle de fond des relances, pour la prod sans worker.

Sans Redis (prod démo : 1 process), aucun cron ARQ ne tourne. L'API
lance donc elle-même, toutes les 10 min, la passe trous d'agenda (le
matin + après annulation) et reprend les campagnes coupées net.
Si un worker ARQ est vivant, elle ne fait rien : c'est lui qui s'en
charge. Désactivée en test ; JENNY_RELANCES_LOOP=0 pour la couper.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import TYPE_CHECKING, Any

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from datetime import datetime

logger = get_logger(__name__)

# même rythme que le cron
INTERVAL_S = 600.0
# laisse l'API démarrer
FIRST_DELAY_S = 45.0

_tick_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None
_task: asyncio.Task | None = None

_OFF = {"0", "false", "no", "off", "non"}
_ON = {"1", "true", "yes", "on", "oui"}


def loop_enabled(settings: Any) -> bool:
    """Boucle voulue ? (env, réglage)"""
    if getattr(settings, "env", None) == "test":
        return False
    raw = (os.environ.get("JENNY_RELANCES_LOOP") or "").strip().lower()
    if raw in _OFF:
        return False
    if raw in _ON:
        return True
    # réglage futur, actif par défaut
    return bool(getattr(settings, "relances_loop_enabled", True))


def _lock() -> asyncio.Lock:
    """Verrou de tick, boucle courante."""
    global _tick_lock
    loop = asyncio.get_running_loop()
    if _tick_lock is None or _tick_lock[0] is not loop:
        _tick_lock = (loop, asyncio.Lock())
    return _tick_lock[1]


async def relances_tick(now: datetime | None = None) -> dict[str, Any]:
    """Une passe : trous d'agenda + campagnes figées."""
    from jenny.services.campaigns import resume_stale_campaigns
    from jenny.services.gap_filler import run_gap_filler, worker_alive

    lock = _lock()
    if lock.locked():
        # passe déjà en cours
        return {"skipped": "busy"}
    async with lock:
        if await worker_alive():
            return {"skipped": "worker"}
        stats: dict[str, Any] = dict(await run_gap_filler(now))
        stats["resumed"] = await resume_stale_campaigns(now)
        return stats


async def relances_loop(interval: float = INTERVAL_S, first_delay: float = FIRST_DELAY_S) -> None:
    """Tourne jusqu'à l'arrêt de l'API."""
    await asyncio.sleep(first_delay)
    while True:
        try:
            stats = await relances_tick()
            if stats.get("sent") or stats.get("failed") or stats.get("resumed"):
                logger.info("relances_loop.tick", **stats)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # jamais fatal
            logger.error("relances_loop.tick_failed", error=str(exc))
        await asyncio.sleep(interval)


def start_relances_loop(settings: Any) -> asyncio.Task | None:
    """Lance la boucle (une seule)."""
    global _task
    if not loop_enabled(settings):
        return None
    if _task is not None and not _task.done():
        return _task
    _task = asyncio.get_running_loop().create_task(relances_loop(), name="relances_loop")
    logger.info("relances_loop.started", interval_s=INTERVAL_S)
    return _task


async def stop_relances_loop(task: asyncio.Task | None, timeout: float = 10.0) -> None:
    """Arrêt propre au shutdown."""
    global _task
    if task is None:
        return
    task.cancel()
    # attend sans relever l'erreur
    await asyncio.wait([task], timeout=timeout)
    if task.done() and not task.cancelled():
        with contextlib.suppress(Exception):
            task.result()
    if _task is task:
        _task = None
    logger.info("relances_loop.stopped")


__all__ = ["loop_enabled", "relances_tick", "start_relances_loop", "stop_relances_loop"]
