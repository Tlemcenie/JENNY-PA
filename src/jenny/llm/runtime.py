"""Choix du LLM actif, modifiable À CHAUD depuis l'UI (bouton de bascule).

Trois moteurs possibles pour Jenny :
- **ollama**  : modèle local (qwen2.5:7b-instruct) — gratuit, privé, sur la machine ;
- **groq**    : Llama 3.3 70B hébergé — très rapide (nécessite une clé API) ;
- **nanogpt** : le modèle « maison » entraîné de A à Z (nécessite un checkpoint).

Le choix est persisté dans ``var/llm_choice.json`` pour survivre aux redémarrages.
Par défaut : le provider/modèle défini dans ``.env`` (JENNY_LLM_PROVIDER/MODEL).
"""

from __future__ import annotations

import json
from pathlib import Path

from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.llm.providers import GROQ_DEFAULT_MODEL

logger = get_logger(__name__)

_STORE = Path("var/llm_choice.json")

# Catalogue présenté dans l'UI : clé UI → provider interne + modèle + libellé/aide.
LLM_OPTIONS: dict[str, dict] = {
    "ollama": {
        "provider": "llama",
        "model": "qwen2.5:7b-instruct",
        "label": "Ollama — local",
        "hint": "Tourne sur TA machine (Ollama). Gratuit et privé — indisponible "
        "sur le serveur hébergé.",
    },
    "groq": {
        "provider": "groq",
        "model": GROQ_DEFAULT_MODEL,
        "label": "Groq — GPT-OSS 120B",
        "hint": "Hébergé, très rapide et qualitatif. Le cerveau par défaut en prod.",
    },
    "nanogpt": {
        "provider": "nanogpt",
        "model": "nanogpt-jenny",
        "label": "NanoGPT — maison",
        "hint": "Notre LLM entraîné de A à Z (from scratch). Démonstrateur : "
        "réponses volontairement basiques.",
    },
}

_active_key: str | None = None


def _default_key() -> str:
    """Clé par défaut, déduite de ``JENNY_LLM_PROVIDER``. Repli ultime : Groq
    (seul moteur toujours disponible côté serveur hébergé)."""
    prov = (get_settings().llm_provider or "groq").lower()
    for key, opt in LLM_OPTIONS.items():
        if opt["provider"] == prov:
            return key
    return "groq"


def get_active_key() -> str:
    """Clé du LLM actif (chargée du disque au premier appel)."""
    global _active_key
    if _active_key is not None:
        return _active_key
    key = _default_key()
    try:
        if _STORE.exists():
            data = json.loads(_STORE.read_text(encoding="utf-8"))
            if data.get("key") in LLM_OPTIONS:
                key = data["key"]
    except Exception as exc:  # pragma: no cover - lecture best-effort
        logger.warning("llm.runtime.read_failed", error=str(exc))
    _active_key = key
    return key


def set_active_key(key: str) -> None:
    """Change le LLM actif et le persiste."""
    if key not in LLM_OPTIONS:
        raise ValueError(f"LLM inconnu : {key}")
    global _active_key
    _active_key = key
    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps({"key": key}), encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        logger.warning("llm.runtime.persist_failed", error=str(exc))
    logger.info("llm.runtime.switched", key=key)


def active_provider_model() -> tuple[str, str | None]:
    """(provider interne, modèle) du LLM actif — consommé par la factory."""
    opt = LLM_OPTIONS[get_active_key()]
    return opt["provider"], opt.get("model")
