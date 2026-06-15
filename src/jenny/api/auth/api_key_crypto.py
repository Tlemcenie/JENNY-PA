"""Hachage des clés API (bcrypt).

Utilise directement la lib ``bcrypt`` (et non passlib) pour éviter le bug de
détection de backend de passlib avec bcrypt >= 4.1 — même choix que
``password_utils``. bcrypt limite le secret à 72 octets : on tronque
explicitement (comportement standard).
"""

from __future__ import annotations

import bcrypt

_MAX_BYTES = 72


def _to_bytes(secret: str) -> bytes:
    return secret.encode("utf-8")[:_MAX_BYTES]


def hash_api_key(raw_secret: str) -> str:
    return bcrypt.hashpw(_to_bytes(raw_secret), bcrypt.gensalt()).decode("utf-8")


def verify_api_key(raw_secret: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(raw_secret), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
