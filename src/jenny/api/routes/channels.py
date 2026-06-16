"""Canaux de messagerie : état + connexion/déconnexion réelle par business.

Vue de synthèse (GET) + gestion des identifiants (connect/disconnect/test) et
info webhook à coller dans Meta. Les identifiants par business sont chiffrés au
repos (si ``JENNY_MASTER_KEY``) via ``channel_credentials_service``. Quand aucun
identifiant n'est présent, le canal reste « non connecté » (réception OK, envoi
désactivé) — fallback gracieux, jamais d'erreur (même logique que l'acompte).
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.connectors.instagram.service import InstagramConnector
from jenny.connectors.whatsapp.service import WhatsAppConnector
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.db.repositories.channel_account_repo import ChannelAccountRepository
from jenny.domain.models.channel_account import ChannelAccount
from jenny.services import channel_credentials_service as creds_svc

logger = get_logger(__name__)

router = APIRouter(prefix="/channels", tags=["Channels"])

# Canaux supportés + leur libellé. ``builtin`` = intégré nativement (toujours
# disponible). ``configurable`` = on peut coller des identifiants (connect).
_SUPPORTED = [
    {"channel": "whatsapp", "label": "WhatsApp", "builtin": False, "configurable": True},
    {"channel": "instagram", "label": "Instagram", "builtin": False, "configurable": True},
    {"channel": "email", "label": "Email", "builtin": True, "configurable": True},
    {"channel": "messenger", "label": "Messenger", "builtin": False, "configurable": False},
    {"channel": "form", "label": "Formulaire web", "builtin": True, "configurable": False},
]
_SPEC_BY_CHANNEL = {s["channel"]: s for s in _SUPPORTED}
_CONFIGURABLE = {"whatsapp", "instagram", "email"}


class ChannelStatus(BaseModel):
    channel: str
    label: str
    connected: bool
    builtin: bool
    configurable: bool
    account: str | None = None
    # Envoi sortant possible (identifiants présents en base OU env).
    outbound_ready: bool = False
    last_error: str | None = None


class ConnectPayload(BaseModel):
    display_name: str | None = None
    credentials: dict = Field(default_factory=dict)


class TestResult(BaseModel):
    ok: bool
    detail: str


class WebhookInfo(BaseModel):
    channel: str
    url: str
    verify_token: str | None = None
    note: str | None = None


class FieldsResponse(BaseModel):
    channel: str
    fields: list[dict]


def _require_business(principal: CurrentUser):
    if principal.business_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aucun business associé au compte.")
    return principal.business_id


def _check_configurable(channel: str) -> None:
    if channel not in _CONFIGURABLE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Canal non configurable : {channel}")


@router.get("", response_model=list[ChannelStatus])
async def list_channels(
    db: DbSession,
    principal: CurrentUser,
) -> list[ChannelStatus]:
    """Liste l'état de connexion de chaque canal pour le business courant."""
    bid = principal.business_id
    accounts: dict[str, ChannelAccount] = {}
    if bid is not None:
        rows = (
            await db.execute(select(ChannelAccount).where(ChannelAccount.business_id == bid))
        ).scalars().all()
        for acc in rows:
            accounts[acc.channel] = acc

    out: list[ChannelStatus] = []
    for spec in _SUPPORTED:
        ch = spec["channel"]
        acc = accounts.get(ch)
        env_ready = creds_svc.env_has_credentials(ch)
        db_ready = bool(acc and acc.credentials_)
        outbound_ready = env_ready or db_ready
        connected = bool(spec["builtin"]) or acc is not None or outbound_ready
        out.append(
            ChannelStatus(
                channel=ch,
                label=spec["label"],
                connected=connected,
                builtin=bool(spec["builtin"]),
                configurable=bool(spec["configurable"]),
                account=(acc.display_name or acc.external_account_id) if acc else None,
                outbound_ready=outbound_ready,
                last_error=acc.last_error if acc else None,
            )
        )
    return out


@router.get("/{channel}/fields", response_model=FieldsResponse)
async def channel_fields(channel: str, principal: CurrentUser) -> FieldsResponse:
    """Champs d'identifiants attendus pour ce canal (pour le formulaire front)."""
    _check_configurable(channel)
    return FieldsResponse(channel=channel, fields=creds_svc.public_field_specs(channel))


@router.get("/{channel}/webhook-info", response_model=WebhookInfo)
async def webhook_info(
    channel: str,
    request: Request,
    db: DbSession,
    principal: CurrentUser,
) -> WebhookInfo:
    """URL de webhook + verify token à coller dans la console Meta (ou inbound email)."""
    _check_configurable(channel)
    bid = _require_business(principal)
    settings = get_settings()
    base = (settings.public_api_base_url or "").rstrip("/")
    if not base:
        # Dérive l'origine de la requête entrante (scheme + host).
        base = str(request.base_url).rstrip("/")
    if channel == "email":
        return WebhookInfo(
            channel=channel,
            url=f"{base}/api/v1/ingest/email/inbound",
            note="Réception par IMAP (polling) ou en transférant vos emails vers cette URL "
            "avec l'en-tête X-Jenny-Inbound-Secret.",
        )
    creds = await creds_svc.resolve(db, bid, channel)
    verify = getattr(creds, "verify_token", None) if creds else None
    if not verify:
        verify = (
            settings.whatsapp_verify_token if channel == "whatsapp" else settings.instagram_verify_token
        )
    return WebhookInfo(
        channel=channel,
        url=f"{base}/api/v1/webhooks/{channel}",
        verify_token=verify,
        note="Collez l'URL et le Verify Token dans la configuration du webhook Meta.",
    )


@router.post("/{channel}/connect", response_model=ChannelStatus)
async def connect_channel(
    channel: str,
    payload: ConnectPayload,
    db: DbSession,
    principal: CurrentUser,
) -> ChannelStatus:
    """Enregistre/met à jour les identifiants d'un canal pour le business courant."""
    _check_configurable(channel)
    bid = _require_business(principal)

    external_id, creds, errors = creds_svc.normalize_connect_payload(channel, payload.credentials)
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "; ".join(errors))

    stored = creds_svc.encrypt_credentials(creds)
    repo = ChannelAccountRepository(db)
    acc = await repo.upsert(
        business_id=bid,
        channel=channel,
        external_account_id=external_id,
        display_name=payload.display_name or external_id,
        credentials=stored,
    )
    acc.webhook_verified_at = None
    await db.commit()
    logger.info("channel.connected", channel=channel, business_id=str(bid))

    return ChannelStatus(
        channel=channel,
        label=_SPEC_BY_CHANNEL[channel]["label"],
        connected=True,
        builtin=bool(_SPEC_BY_CHANNEL[channel]["builtin"]),
        configurable=True,
        account=acc.display_name or acc.external_account_id,
        outbound_ready=True,
        last_error=None,
    )


@router.delete("/{channel}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_channel(
    channel: str,
    db: DbSession,
    principal: CurrentUser,
) -> None:
    """Supprime les identifiants d'un canal pour le business courant."""
    _check_configurable(channel)
    bid = _require_business(principal)
    repo = ChannelAccountRepository(db)
    await repo.delete_for_business(bid, channel)
    await db.commit()
    logger.info("channel.disconnected", channel=channel, business_id=str(bid))


@router.post("/{channel}/test", response_model=TestResult)
async def test_channel(
    channel: str,
    db: DbSession,
    principal: CurrentUser,
) -> TestResult:
    """Teste les identifiants résolus du canal (ping API Meta / présence SMTP)."""
    _check_configurable(channel)
    bid = _require_business(principal)
    creds = await creds_svc.resolve(db, bid, channel)
    if creds is None:
        return TestResult(ok=False, detail="Aucun identifiant configuré pour ce canal.")

    if channel == "whatsapp":
        ok = await WhatsAppConnector().health_check(creds)  # type: ignore[arg-type]
        detail = "Connexion à l'API WhatsApp Cloud OK." if ok else "Échec du ping API WhatsApp (token/ID ?)."
    elif channel == "instagram":
        ok = await InstagramConnector().health_check(creds)  # type: ignore[arg-type]
        detail = "Connexion à l'API Instagram OK." if ok else "Échec du ping API Instagram (token/ID ?)."
    elif channel == "email":
        ok = bool(getattr(creds, "smtp_password", "") and getattr(creds, "smtp_host", ""))
        detail = (
            "Identifiants SMTP présents (envoi possible)."
            if ok
            else "SMTP incomplet : hôte + mot de passe requis pour l'envoi."
        )
    else:
        ok, detail = False, "Test non disponible pour ce canal."

    # Diagnostic persisté pour l'UI (best-effort).
    acc = await ChannelAccountRepository(db).get_account(bid, channel)
    if acc is not None:
        acc.last_error = None if ok else detail
        if ok:
            acc.webhook_verified_at = datetime.now(UTC)
        await db.commit()

    return TestResult(ok=ok, detail=detail)
