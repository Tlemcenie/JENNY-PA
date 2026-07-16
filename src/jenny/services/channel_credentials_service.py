"""Identifiants de canal par business."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.db.repositories.channel_account_repo import ChannelAccountRepository

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


# identifiants typés par canal
@dataclass
class WhatsAppCreds:
    phone_number_id: str
    access_token: str
    verify_token: str = "jenny-whatsapp-verify"
    api_version: str = "v21.0"


@dataclass
class InstagramCreds:
    page_id: str
    access_token: str
    verify_token: str = "jenny-instagram-verify"


@dataclass
class EmailCreds:
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Jenny"
    smtp_use_tls: bool = True
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_use_ssl: bool = True


AnyCreds = WhatsAppCreds | InstagramCreds | EmailCreds


# spécification des champs
@dataclass
class FieldSpec:
    key: str
    label: str
    secret: bool = False
    required: bool = False
    placeholder: str = ""


CHANNEL_FIELDS: dict[str, list[FieldSpec]] = {
    "whatsapp": [
        FieldSpec("phone_number_id", "Phone Number ID", required=True, placeholder="1234567890"),
        FieldSpec("access_token", "Access Token (permanent)", secret=True, required=True),
        FieldSpec("verify_token", "Verify Token (webhook)", placeholder="jenny-whatsapp-verify"),
    ],
    "instagram": [
        FieldSpec("page_id", "Page / compte IG ID", required=True),
        FieldSpec("access_token", "Access Token", secret=True, required=True),
        FieldSpec("verify_token", "Verify Token (webhook)", placeholder="jenny-instagram-verify"),
    ],
    "email": [
        FieldSpec("smtp_host", "SMTP — Hôte", required=True, placeholder="smtp.gmail.com"),
        FieldSpec("smtp_port", "SMTP — Port", placeholder="587"),
        FieldSpec("smtp_username", "SMTP — Utilisateur", required=True),
        FieldSpec("smtp_password", "SMTP — Mot de passe", secret=True, required=True),
        FieldSpec("smtp_from_email", "Email expéditeur", placeholder="contact@salon.fr"),
        FieldSpec("imap_host", "IMAP — Hôte (réception)", placeholder="imap.gmail.com"),
        FieldSpec("imap_user", "IMAP — Utilisateur"),
        FieldSpec("imap_password", "IMAP — Mot de passe", secret=True),
    ],
}

# clé externe par canal
_EXTERNAL_KEY: dict[str, str] = {
    "whatsapp": "phone_number_id",
    "instagram": "page_id",
    "messenger": "page_id",
    "email": "smtp_from_email",
}


def external_account_id_for(channel: str, data: dict) -> str:
    """Identifiant pour le routage webhook."""
    if channel == "email":
        return str(data.get("smtp_from_email") or data.get("imap_user") or data.get("smtp_username") or "")
    return str(data.get(_EXTERNAL_KEY.get(channel, "external_account_id"), "") or "")


def _has_token(channel: str, data: dict) -> bool:
    """Identifiants exploitables ?"""
    if channel in ("whatsapp", "instagram", "messenger"):
        return bool(data.get("access_token"))
    if channel == "email":
        return bool(data.get("smtp_password") or data.get("imap_password") or data.get("imap_host"))
    return False


# chiffrement au repos
def _fernet():
    key = (get_settings().master_key or "").strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode())
    except Exception as exc:  # clé invalide
        logger.warning("channel_creds.fernet_init_failed", error=str(exc))
        return None


def encrypt_credentials(data: dict) -> dict:
    """Chiffre si clé maître."""
    f = _fernet()
    if f is None:
        return dict(data)
    token = f.encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()
    return {"__enc__": token}


def decrypt_credentials(stored: dict | None) -> dict:
    """Déchiffre credentials_."""
    if not stored:
        return {}
    if "__enc__" in stored:
        f = _fernet()
        if f is None:
            logger.warning("channel_creds.decrypt_no_key")
            return {}
        try:
            return json.loads(f.decrypt(str(stored["__enc__"]).encode()).decode())
        except Exception as exc:
            logger.warning("channel_creds.decrypt_failed", error=str(exc))
            return {}
    return dict(stored)


# fallback depuis l'env
def _creds_from_env(channel: str) -> dict | None:
    s = get_settings()
    if channel == "whatsapp" and s.whatsapp_access_token:
        return {
            "phone_number_id": s.whatsapp_phone_number_id,
            "access_token": s.whatsapp_access_token,
            "verify_token": s.whatsapp_verify_token,
            "api_version": s.whatsapp_api_version,
        }
    if channel == "instagram" and s.instagram_access_token:
        return {
            "page_id": s.instagram_page_id,
            "access_token": s.instagram_access_token,
            "verify_token": s.instagram_verify_token,
        }
    if channel == "email" and (s.smtp_username or s.imap_host):
        return {
            "smtp_host": s.smtp_host,
            "smtp_port": s.smtp_port,
            "smtp_username": s.smtp_username,
            "smtp_password": s.smtp_password,
            "smtp_from_email": s.smtp_from_email,
            "smtp_from_name": s.smtp_from_name,
            "smtp_use_tls": s.smtp_use_tls,
            "imap_host": s.imap_host,
            "imap_user": s.imap_user,
            "imap_password": s.imap_password,
            "imap_mailbox": s.imap_mailbox,
            "imap_use_ssl": s.imap_use_ssl,
        }
    return None


def env_has_credentials(channel: str) -> bool:
    """Identifiants env présents ?"""
    return _creds_from_env(channel) is not None


def _build_typed(channel: str, data: dict) -> AnyCreds | None:
    try:
        if channel == "whatsapp":
            return WhatsAppCreds(
                phone_number_id=str(data.get("phone_number_id", "")),
                access_token=str(data.get("access_token", "")),
                verify_token=str(data.get("verify_token") or "jenny-whatsapp-verify"),
                api_version=str(data.get("api_version") or "v21.0"),
            )
        if channel in ("instagram", "messenger"):
            return InstagramCreds(
                page_id=str(data.get("page_id", "")),
                access_token=str(data.get("access_token", "")),
                verify_token=str(data.get("verify_token") or "jenny-instagram-verify"),
            )
        if channel == "email":
            return EmailCreds(
                smtp_host=str(data.get("smtp_host", "")),
                smtp_port=int(data.get("smtp_port") or 587),
                smtp_username=str(data.get("smtp_username", "")),
                smtp_password=str(data.get("smtp_password", "")),
                smtp_from_email=str(data.get("smtp_from_email", "")),
                smtp_from_name=str(data.get("smtp_from_name") or "Jenny"),
                smtp_use_tls=bool(data.get("smtp_use_tls", True)),
                imap_host=str(data.get("imap_host", "")),
                imap_user=str(data.get("imap_user", "")),
                imap_password=str(data.get("imap_password", "")),
                imap_mailbox=str(data.get("imap_mailbox") or "INBOX"),
                imap_use_ssl=bool(data.get("imap_use_ssl", True)),
            )
    except (TypeError, ValueError) as exc:
        logger.warning("channel_creds.build_failed", channel=channel, error=str(exc))
    return None


# résolution
async def resolve_raw(
    session: AsyncSession, business_id: UUID | None, channel: str
) -> dict | None:
    """Base d'abord, sinon env."""
    if business_id is not None:
        repo = ChannelAccountRepository(session)
        acct = await repo.get_account(business_id, channel)
        if acct is not None and acct.credentials_:
            data = decrypt_credentials(acct.credentials_)
            if data:
                data.setdefault(_EXTERNAL_KEY.get(channel, "external_account_id"), acct.external_account_id)
                if _has_token(channel, data):
                    return data
    return _creds_from_env(channel)


async def resolve(
    session: AsyncSession, business_id: UUID | None, channel: str
) -> AnyCreds | None:
    """Identifiants typés ou None."""
    raw = await resolve_raw(session, business_id, channel)
    if raw is None:
        return None
    return _build_typed(channel, raw)


async def is_connected(
    session: AsyncSession, business_id: UUID | None, channel: str
) -> bool:
    """Canal connecté ?"""
    return await resolve_raw(session, business_id, channel) is not None


async def matches_verify_token(session: AsyncSession, channel: str, token: str) -> bool:
    """Vérifie le verify token."""
    if not token:
        return False
    env = _creds_from_env(channel)
    if env and env.get("verify_token") == token:
        return True
    repo = ChannelAccountRepository(session)
    for acc in await repo.list_with_credentials(channel):
        data = decrypt_credentials(acc.credentials_)
        if data.get("verify_token") == token:
            return True
    return False


def normalize_connect_payload(channel: str, raw: dict) -> tuple[str, dict, list[str]]:
    """Valide un payload de connexion."""
    specs = CHANNEL_FIELDS.get(channel)
    errors: list[str] = []
    if specs is None:
        return "", {}, [f"Canal non supporté : {channel}"]
    creds: dict = {}
    for spec in specs:
        val = raw.get(spec.key)
        if val is None or (isinstance(val, str) and not val.strip()):
            if spec.required:
                errors.append(f"Champ requis manquant : {spec.label}")
            continue
        creds[spec.key] = val.strip() if isinstance(val, str) else val
    # port en entier
    if channel == "email" and "smtp_port" in creds:
        try:
            creds["smtp_port"] = int(creds["smtp_port"])
        except (TypeError, ValueError):
            creds["smtp_port"] = 587
    external_id = external_account_id_for(channel, creds)
    if not external_id and not errors:
        errors.append("Identifiant de compte introuvable (Phone Number ID / Page ID / email).")
    return external_id, creds, errors


# champs exposables au front
def public_field_specs(channel: str) -> list[dict]:
    return [
        {"key": f.key, "label": f.label, "secret": f.secret, "required": f.required, "placeholder": f.placeholder}
        for f in CHANNEL_FIELDS.get(channel, [])
    ]


# évite l'avertissement lint
_ = field
