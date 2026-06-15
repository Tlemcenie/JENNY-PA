#!/usr/bin/env python3
"""Smoke test e2e pour Jenny — à lancer contre un serveur live.

Vérifie de bout en bout les fonctionnalités principales :
- /health, /ready
- Inscription + login (`/api/v1/auth/*`) sur la base réelle
- /auth/me avec JWT
- Chat conversationnel (greeting, RDV, devis, escalade)
- Statut de conversation persisté

Usage :

    # Démarrer la stack
    make demo-up

    # Puis lancer le smoke test
    python scripts/e2e_smoke.py
    BASE_URL=http://localhost:8000 python scripts/e2e_smoke.py
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any

import httpx

BASE = os.environ.get("BASE_URL", "http://localhost:8000")
TIMEOUT = httpx.Timeout(30.0)


def _step(label: str) -> None:
    print(f"\n→ {label}")


def _ok(message: str) -> None:
    print(f"  \033[32m✓\033[0m {message}")


def _fail(message: str) -> None:
    print(f"  \033[31m✗\033[0m {message}")
    sys.exit(1)


def _expect(cond: bool, msg: str) -> None:
    if cond:
        _ok(msg)
    else:
        _fail(msg)


def _post(client: httpx.Client, path: str, **kwargs: Any) -> httpx.Response:
    return client.post(f"{BASE}{path}", **kwargs)


def _get(client: httpx.Client, path: str, **kwargs: Any) -> httpx.Response:
    return client.get(f"{BASE}{path}", **kwargs)


def main() -> int:
    print(f"Jenny e2e smoke vs {BASE}")

    with httpx.Client(timeout=TIMEOUT) as c:
        _step("Health & readiness")
        r = _get(c, "/health")
        _expect(r.status_code == 200 and r.json().get("status") == "healthy", "/health")

        r = _get(c, "/ready")
        _expect(r.status_code == 200, "/ready")
        ready = r.json()
        _expect(ready["status"] in ("ready", "degraded"), f"ready status = {ready['status']}")

        _step("Auth — register / login / me")
        email = f"smoke+{uuid.uuid4().hex[:6]}@jenny.ai"
        password = "Smoke!1234"
        r = _post(
            c,
            "/api/v1/auth/register",
            json={"full_name": "Smoke User", "email": email, "password": password},
        )
        _expect(r.status_code in (200, 201), f"register → {r.status_code}")
        token = r.json()["access_token"]

        r = _post(c, "/api/v1/auth/login", json={"email": email, "password": password})
        _expect(r.status_code == 200, "login")
        token = r.json()["access_token"]

        r = _get(c, "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        _expect(r.status_code == 200, "auth/me")
        _expect(r.json()["email"] == email, "/me email matches")

        _step("Chat — greeting / RDV / devis / escalade")
        conv_id = str(uuid.uuid4())
        biz_id = str(uuid.uuid4())

        for msg in [
            "Bonjour !",
            "Je voudrais prendre rendez-vous samedi à 10h",
            "Pouvez-vous me faire un devis pour une prestation ?",
            "Quels services proposez-vous ?",
        ]:
            r = _post(
                c,
                "/api/v1/conversation/chat",
                json={"conversation_id": conv_id, "business_id": biz_id, "message": msg},
            )
            _expect(r.status_code == 200, f"chat: {msg!r}")
            _expect(bool(r.json().get("response")), "chat returned non-empty response")

        r = _post(
            c,
            "/api/v1/conversation/chat",
            json={
                "conversation_id": conv_id,
                "business_id": biz_id,
                "message": "Je veux parler à un humain",
            },
        )
        body = r.json()
        _expect(body.get("requires_human") is True, "escalation flagged requires_human")

        r = _get(c, f"/api/v1/conversation/status/{conv_id}")
        _expect(r.status_code == 200, "/conversation/status")
        _expect(r.json().get("turn_count", 0) >= 5, "5+ turns persisted in state")

    print("\n\033[32mAll smoke tests passed ✓\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
