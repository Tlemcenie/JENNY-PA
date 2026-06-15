"""État des canaux de messagerie connectés au business.

Vue de synthèse : pour chaque canal supporté, indique s'il est connecté
(compte de canal enregistré, ou intégré nativement comme le formulaire/email).
"""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.config import get_settings
from jenny.domain.models.channel_account import ChannelAccount

router = APIRouter(prefix="/channels", tags=["Channels"])

# Canaux supportés + leur libellé. ``builtin`` = intégré nativement (toujours
# disponible, pas de connexion externe requise).
_SUPPORTED = [
    {"channel": "whatsapp", "label": "WhatsApp", "builtin": False},
    {"channel": "instagram", "label": "Instagram", "builtin": False},
    {"channel": "messenger", "label": "Messenger", "builtin": False},
    {"channel": "twitter", "label": "Twitter / X", "builtin": False},
    {"channel": "snapchat", "label": "Snapchat", "builtin": False},
    {"channel": "email", "label": "Email", "builtin": True},
    {"channel": "form", "label": "Formulaire web", "builtin": True},
]


class ChannelStatus(BaseModel):
    channel: str
    label: str
    connected: bool
    builtin: bool
    account: str | None = None


@router.get("", response_model=list[ChannelStatus])
async def list_channels(
    db: DbSession,
    principal: CurrentUser,
) -> list[ChannelStatus]:
    """Liste l'état de connexion de chaque canal pour le business courant."""
    bid = principal.business_id
    accounts: dict[str, str] = {}
    if bid is not None:
        rows = (
            await db.execute(
                select(ChannelAccount.channel, ChannelAccount.display_name).where(
                    ChannelAccount.business_id == bid
                )
            )
        ).all()
        accounts = {ch: (name or "") for ch, name in rows}

    settings = get_settings()
    out: list[ChannelStatus] = []
    for spec in _SUPPORTED:
        ch = spec["channel"]
        connected = spec["builtin"] or ch in accounts
        # WhatsApp est aussi « connecté » si un token est configuré dans l'env.
        if ch == "whatsapp" and getattr(settings, "whatsapp_access_token", ""):
            connected = True
        out.append(
            ChannelStatus(
                channel=ch,
                label=spec["label"],
                connected=connected,
                builtin=spec["builtin"],
                account=accounts.get(ch) or None,
            )
        )
    return out
