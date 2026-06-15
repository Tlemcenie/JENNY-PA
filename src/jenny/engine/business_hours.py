"""Horaires d'ouverture d'un business + détection ouvert/fermé.

``business_hours`` est un dict ``{"mon": ["09:00","19:00"], …, "sun": null}``
(clés anglaises lun→dim). Une valeur null/absente = fermé ce jour-là. Si tout
le dict est vide/None, le business est considéré comme toujours ouvert
(pas de restriction → pas d'auto-réponse hors horaires).
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def is_open(
    business_hours: dict | None,
    timezone_name: str | None,
    now_utc: datetime | None = None,
) -> bool:
    """Indique si le business est ouvert à l'instant ``now_utc`` (UTC)."""
    if not business_hours:
        return True  # aucun horaire configuré → toujours ouvert
    now_utc = now_utc or datetime.now(UTC)
    try:
        tz = ZoneInfo(timezone_name or "Europe/Paris")
    except Exception:
        tz = ZoneInfo("Europe/Paris")
    local = now_utc.astimezone(tz)
    rng = business_hours.get(_DAYS[local.weekday()])
    if not rng or len(rng) != 2:
        return False  # jour fermé
    try:
        open_t = time.fromisoformat(str(rng[0]))
        close_t = time.fromisoformat(str(rng[1]))
    except (ValueError, TypeError):
        return True  # horaire mal formé → on ne bloque pas
    return open_t <= local.time() <= close_t
