"""Vérification des signatures HMAC des webhooks Meta (X-Hub-Signature-256)."""

from __future__ import annotations

import hashlib
import hmac


def verify_meta_signature(body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Valide le header `X-Hub-Signature-256` pour le corps brut du POST.

    Format attendu : ``sha256=<hexdigest>``
    """
    if not app_secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected_hex = signature_header[7:]
    try:
        expected = bytes.fromhex(expected_hex)
    except ValueError:
        return False
    mac = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return hmac.compare_digest(mac, expected)
