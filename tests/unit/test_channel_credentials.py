"""Tests du service d'identifiants de canal (chiffrement, validation, fallback)."""

from __future__ import annotations

import pytest

from jenny.services import channel_credentials_service as svc


def test_encrypt_plaintext_roundtrip_without_master_key(monkeypatch):
    """Sans clé maître : stockage en clair, déchiffrement transparent."""
    monkeypatch.setattr(svc, "_fernet", lambda: None)
    data = {"access_token": "tok123", "phone_number_id": "555"}
    stored = svc.encrypt_credentials(data)
    assert stored == data  # clair
    assert svc.decrypt_credentials(stored) == data


def test_encrypt_fernet_roundtrip_with_master_key(monkeypatch):
    """Avec une clé Fernet : la colonne ne contient PAS le token en clair."""
    from cryptography.fernet import Fernet

    f = Fernet(Fernet.generate_key())
    monkeypatch.setattr(svc, "_fernet", lambda: f)
    data = {"access_token": "super-secret", "page_id": "999"}
    stored = svc.encrypt_credentials(data)
    assert "__enc__" in stored
    assert "super-secret" not in str(stored)  # vraiment chiffré
    assert svc.decrypt_credentials(stored) == data


def test_decrypt_encrypted_without_key_returns_empty(monkeypatch):
    """Donnée chiffrée mais clé absente → vide (pas de crash, pas de fuite)."""
    monkeypatch.setattr(svc, "_fernet", lambda: None)
    assert svc.decrypt_credentials({"__enc__": "gAAAAA..."}) == {}


def test_normalize_whatsapp_ok():
    ext, creds, errors = svc.normalize_connect_payload(
        "whatsapp", {"phone_number_id": "123", "access_token": "tok", "verify_token": "v"}
    )
    assert errors == []
    assert ext == "123"
    assert creds["access_token"] == "tok"


def test_normalize_whatsapp_missing_required():
    _ext, _creds, errors = svc.normalize_connect_payload("whatsapp", {"phone_number_id": "123"})
    assert errors and any("Access Token" in e for e in errors)


def test_normalize_unsupported_channel():
    _ext, _creds, errors = svc.normalize_connect_payload("telegram", {"foo": "bar"})
    assert errors and "non supporté" in errors[0]


def test_normalize_email_port_coercion():
    ext, creds, errors = svc.normalize_connect_payload(
        "email",
        {"smtp_host": "smtp.x.fr", "smtp_username": "a@x.fr", "smtp_password": "p", "smtp_port": "465", "smtp_from_email": "a@x.fr"},
    )
    assert errors == []
    assert creds["smtp_port"] == 465  # converti en int
    assert ext == "a@x.fr"


def test_public_field_specs_never_leak_values():
    specs = svc.public_field_specs("whatsapp")
    keys = {s["key"] for s in specs}
    assert {"phone_number_id", "access_token", "verify_token"} <= keys
    # un champ secret est marqué tel quel (le front masque la saisie)
    assert any(s["secret"] for s in specs if s["key"] == "access_token")


def test_external_account_id_for_email_prefers_from_email():
    assert svc.external_account_id_for("email", {"smtp_from_email": "x@y.fr", "imap_user": "z"}) == "x@y.fr"
    assert svc.external_account_id_for("email", {"imap_user": "z@y.fr"}) == "z@y.fr"


def test_build_typed_whatsapp_defaults():
    creds = svc._build_typed("whatsapp", {"phone_number_id": "1", "access_token": "t"})
    assert isinstance(creds, svc.WhatsAppCreds)
    assert creds.verify_token == "jenny-whatsapp-verify"
    assert creds.api_version == "v21.0"


@pytest.mark.parametrize("channel,data,expected", [
    ("whatsapp", {"access_token": "x"}, True),
    ("whatsapp", {"access_token": ""}, False),
    ("email", {"smtp_password": "x"}, True),
    ("email", {}, False),
])
def test_has_token(channel, data, expected):
    assert svc._has_token(channel, data) is expected
