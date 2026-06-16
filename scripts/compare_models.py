"""Comparaison des 3 modèles : Groq · Ollama · NanoGPT (maison, from scratch).

Mini-banc d'essai AUTONOME (pas besoin d'Ollama-embeddings) : on donne à chaque
modèle le MÊME contexte salon + les MÊMES questions client, et on mesure :
  - efficacité : % de réponses contenant la bonne info (mots-clés attendus)
  - perf       : latence moyenne par réponse (ms)

Écrit var/eval/comparison.json (lu par l'onglet Efficacité / le labo).

Usage : .venv/bin/python scripts/compare_models.py
(NanoGPT marche dès qu'il est entraîné ; Groq nécessite la clé ; Ollama doit tourner.)
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "var" / "eval" / "comparison.json"

SYSTEM = (
    "Tu es Jenny, l'assistante du salon de coiffure « Studio Lila » à Bordeaux. "
    "Horaires : mardi à samedi 9h-19h, fermé dimanche et lundi. "
    "Tarifs : coupe femme 35€, coupe homme 22€, coloration 60€, balayage 90€. "
    "Réponds en français, en une phrase, en t'appuyant uniquement sur ces infos."
)

# Questions client + mots-clés attendus (un seul suffit) pour scorer l'efficacité.
PROMPTS = [
    ("Vous êtes ouverts le dimanche ?", ["non", "fermé", "ferme"]),
    ("C'est combien une coupe homme ?", ["22"]),
    ("Quels sont vos horaires le samedi ?", ["9", "19"]),
    ("Le balayage coûte combien ?", ["90"]),
    ("Vous êtes dans quelle ville ?", ["bordeaux"]),
    ("Prix d'une coloration ?", ["60"]),
]


async def _bench_provider(key: str, opt: dict) -> dict:
    from jenny.llm.providers import get_llm_provider

    label = opt.get("label", key)
    provider_name = opt["provider"]
    model = opt.get("model", "")
    res = {"key": key, "label": label, "provider": provider_name, "model": model}

    kwargs = {"model": model} if model and provider_name != "nanogpt" else {}
    try:
        provider = get_llm_provider(provider_name, **kwargs)
    except Exception as exc:
        return {**res, "available": False, "note": f"init: {exc}"}

    if not provider.is_configured:
        notes = {
            "groq": "clé API Groq manquante",
            "llama": "Ollama non joignable",
            "nanogpt": "modèle non entraîné (pas de checkpoint)",
        }
        return {**res, "available": False, "note": notes.get(provider_name, "non configuré")}

    passed = 0
    latencies: list[float] = []
    samples: list[dict] = []
    for prompt, expect in PROMPTS:
        t0 = time.perf_counter()
        try:
            r = await provider.generate(prompt, system_prompt=SYSTEM, temperature=0.3, max_tokens=120)
            text = (r.content or "").strip()
        except Exception as exc:
            return {**res, "available": False, "note": f"generate: {exc}"}
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)
        low = text.lower()
        ok = any(kw.lower() in low for kw in expect)
        passed += int(ok)
        if len(samples) < 2:
            samples.append({"q": prompt, "a": text[:180], "ok": ok})

    n = len(PROMPTS)
    return {
        **res,
        "available": True,
        "score_pct": round(100 * passed / n, 1),
        "checks_passed": passed,
        "checks_total": n,
        "avg_latency_ms": round(sum(latencies) / max(len(latencies), 1), 1),
        "samples": samples,
    }


async def main() -> int:
    from jenny.llm.runtime import LLM_OPTIONS

    print(f"Comparaison sur {len(PROMPTS)} questions client (contexte salon partagé)…\n")
    results = []
    for key, opt in LLM_OPTIONS.items():
        print(f"→ {opt.get('label', key)} …", flush=True)
        r = await _bench_provider(key, opt)
        results.append(r)
        if r.get("available"):
            print(f"   efficacité {r['score_pct']}% · latence {r['avg_latency_ms']} ms")
        else:
            print(f"   indisponible ({r.get('note')})")

    # Ordre stable : ollama, groq, nanogpt
    order = {"ollama": 0, "groq": 1, "nanogpt": 2}
    results.sort(key=lambda r: order.get(r["key"], 9))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"generated_at": int(time.time()), "prompts": len(PROMPTS), "results": results}, indent=2,
                   ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n✓ comparaison écrite : {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
