"""Hashing bcrypt pour mots de passe utilisateur.

Utilise directement la lib `bcrypt` (et non passlib) pour éviter le bug de
détection de backend de passlib avec bcrypt >= 4.1. bcrypt limite le secret à
72 octets : on tronque explicitement, ce qui est le comportement standard.
"""

from __future__ import annotations

import bcrypt

_MAX_BYTES = 72


def _to_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
