"""CLI du banc d'essai : exécute tous les scénarios et écrit un rapport.

Usage :
    .venv/bin/python -m jenny.scripts.run_eval

Nécessite Ollama (qwen2.5:3b + nomic-embed-text). N'utilise NI Postgres NI Redis
(état conversationnel + base de connaissances en mémoire) : reproductible.
"""

from __future__ import annotations

import os

# État conversationnel en mémoire (Redis pointé sur un port fermé → repli immédiat).
os.environ.setdefault("JENNY_REDIS_URL", "redis://localhost:6390/1")
os.environ.setdefault("JENNY_LLM_PROVIDER", "llama")
os.environ.setdefault("JENNY_LLM_MODEL", "qwen2.5:3b")
os.environ.setdefault("JENNY_ENABLE_ML_MODELS", "false")

import asyncio
import json
from pathlib import Path


async def _main() -> None:
    from jenny.eval.harness import run_all
    from jenny.eval.report import format_markdown
    from jenny.eval.scenarios import SCENARIOS

    data = await run_all(SCENARIOS)
    md = format_markdown(data)

    out_dir = Path("var/eval")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "last_report.md").write_text(md, encoding="utf-8")
    (out_dir / "last_report.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(md)
    print(f"\n→ Rapport écrit dans {out_dir}/last_report.md et last_report.json")


if __name__ == "__main__":
    asyncio.run(_main())
