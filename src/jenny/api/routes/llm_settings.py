"""Bascule du LLM actif à chaud (Ollama local / Groq hébergé / NanoGPT maison).

Le gérant choisit quel « cerveau » fait tourner Jenny côté client. Le changement
est appliqué immédiatement (le provider du moteur est remplacé sans tout
reconstruire) et persisté pour survivre aux redémarrages.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from jenny.api.dependencies import CurrentUser  # noqa: TC001 — résolu au runtime par FastAPI
from jenny.core.logging import get_logger
from jenny.llm.providers import get_llm_provider
from jenny.llm.runtime import LLM_OPTIONS, get_active_key, set_active_key

logger = get_logger(__name__)

router = APIRouter(prefix="/settings/llm", tags=["llm"])


class LlmOption(BaseModel):
    key: str
    label: str
    hint: str
    model: str
    available: bool
    current: bool


class LlmState(BaseModel):
    active: str
    options: list[LlmOption]


class LlmSwitchRequest(BaseModel):
    key: str


async def _is_available(key: str) -> bool:
    """Le moteur est-il RÉELLEMENT prêt à répondre ?

    - Groq : clé API présente.
    - NanoGPT : checkpoint + tokenizer sur disque.
    - Ollama : on PING l'endpoint (le simple fait d'avoir une URL ne suffit pas —
      sur Cloud Run il n'y a aucun serveur Ollama, sinon on l'afficherait « dispo »
      puis on servirait du charabia). Timeout court pour ne pas bloquer l'UI.
    """
    opt = LLM_OPTIONS[key]
    try:
        kwargs = (
            {"model": opt["model"]}
            if (opt.get("model") and opt["provider"] != "nanogpt")
            else {}
        )
        provider = get_llm_provider(opt["provider"], **kwargs)
    except Exception:
        return False

    if opt["provider"] == "llama":
        # Ollama : vérifie que le serveur répond vraiment (reachability).
        base_url = getattr(provider, "base_url", None)
        if not base_url:
            return False
        try:
            import httpx

            async with httpx.AsyncClient(timeout=1.5) as client:
                r = await client.get(f"{base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    return bool(provider.is_configured)


async def _state() -> LlmState:
    active = get_active_key()
    options = []
    for k, o in LLM_OPTIONS.items():
        options.append(
            LlmOption(
                key=k,
                label=o["label"],
                hint=o["hint"],
                model=o.get("model") or "",
                available=await _is_available(k),
                current=(k == active),
            )
        )
    return LlmState(active=active, options=options)


@router.get("", response_model=LlmState)
async def get_llm_settings(_principal: CurrentUser) -> LlmState:
    """Liste les moteurs disponibles + lequel est actif."""
    return await _state()


@router.post("", response_model=LlmState)
async def switch_llm(body: LlmSwitchRequest, _principal: CurrentUser) -> LlmState:
    """Bascule Jenny sur un autre moteur, immédiatement."""
    if body.key not in LLM_OPTIONS:
        raise HTTPException(status_code=400, detail="Modèle inconnu.")
    if not await _is_available(body.key):
        opt = LLM_OPTIONS[body.key]
        raise HTTPException(
            status_code=400,
            detail=f"« {opt['label']} » n'est pas encore prêt : {opt['hint']}",
        )

    set_active_key(body.key)

    # Application à chaud : on remplace le générateur du moteur partagé (pas de
    # reconstruction complète → on ne recharge pas les modèles ML intent/NER).
    try:
        from jenny.engine.factory import get_engine
        from jenny.engine.response_generator import ResponseGenerator
        from jenny.llm.providers import get_default_llm_provider

        provider = get_default_llm_provider()
        engine = get_engine()
        engine.response_generator = (
            ResponseGenerator(provider) if provider is not None else None
        )
    except Exception as exc:  # pragma: no cover - défensif
        logger.warning("llm.switch.engine_swap_failed", error=str(exc))

    logger.info("llm.switched", key=body.key)
    return await _state()
