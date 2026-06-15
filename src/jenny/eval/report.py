"""Mise en forme du rapport d'évaluation (Markdown lisible)."""

from __future__ import annotations


def format_markdown(data: dict) -> str:
    s = data["summary"]
    lines: list[str] = [
        "# Rapport d'efficacité de Jenny",
        "",
        f"**Score global : {s['score_pct']}%** "
        f"({s['checks_passed']}/{s['checks_total']} vérifications) — "
        f"{s['scenarios']} scénarios, {s['turns']} tours clients.",
        "",
        "## Par critère",
        "",
        "| Critère | Réussite |",
        "|---|---|",
    ]
    labels = {
        "persona_humaine": "Persona humaine (jamais « IA », pas de fuite)",
        "langue": "Bonne langue de réponse",
        "clarification": "Clarification au bon moment",
        "lacune_detectee": "Lacune détectée",
        "info_cle_presente": "Info clé fournie (grounding)",
        "interdits_absents": "Formules interdites évitées",
    }
    for k, v in s["by_criterion"].items():
        lines.append(f"| {labels.get(k, k)} | {v['pct']}% ({v['pass']}/{v['total']}) |")

    lines += ["", "## Détail par scénario", ""]
    for r in data["scenarios"]:
        lines.append(
            f"### {r['domain']} — {r['business_name']}  "
            f"({r['checks_passed']}/{r['checks_total']})"
        )
        for t in r["turns"]:
            mark = "✅" if t["passed"] else "❌"
            lines.append(f"- {mark} **Client :** {t['user']}")
            lines.append(f"  - **Jenny :** {t['response']}")
            failed = [c for c in t["checks"] if not c["passed"]]
            if failed:
                lines.append(
                    "  - ⚠️ "
                    + "; ".join(
                        f"{c['name']}"
                        + (f" — {c['detail']}" if c["detail"] else "")
                        for c in failed
                    )
                )
        lines.append("")
    return "\n".join(lines)
