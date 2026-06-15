"""Génération et vérification du code de confirmation d'email.

Code numérique à 6 chiffres, tiré de façon cryptographiquement sûre, stocké
uniquement sous forme de hash (bcrypt, réutilisé depuis ``password_utils``).
Expiration courte + limite de tentatives pour contrer le brute-force.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from jenny.api.auth.password_utils import hash_password, verify_password
from jenny.core.config import get_settings

CODE_LENGTH = 6
MAX_VERIFY_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60


def generate_code() -> str:
    """Retourne un code numérique à 6 chiffres (avec zéros de tête)."""
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


def hash_code(code: str) -> str:
    return hash_password(code)


def verify_code(code: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    return verify_password(code, hashed)


def ttl_minutes() -> int:
    return get_settings().email_verification_ttl_minutes


def code_expiry(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now + timedelta(minutes=ttl_minutes())


def is_expired(expires_at: datetime | None, now: datetime | None = None) -> bool:
    if expires_at is None:
        return True
    now = now or datetime.now(UTC)
    # Tolère les datetimes naïfs (SQLite en test) en les traitant comme UTC.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return now >= expires_at
