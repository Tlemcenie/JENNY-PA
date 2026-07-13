"""Nettoyage du business démo : dédup KB + re-sync des connaissances + purge des
données de test (prestations « QA », rendez-vous hors horaires qui faussent les
statistiques). Piloté par l'API → fonctionne en local ET en prod.

Usage :
    python scripts/cleanup_demo.py                       # local (http://localhost:8000)
    python scripts/cleanup_demo.py --api-url https://…   # prod
    python scripts/cleanup_demo.py --dry-run             # n'affiche que ce qui serait fait
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Titres re-synchronisés depuis les fichiers sources (applique tout correctif de
# contenu, ex. horaires harmonisés). Le reste des entrées est seulement dédupliqué.
SAMPLE_FILES = [
    ("Politiques & infos pratiques", "knowledge_samples/01_politiques_salon.md", "politique"),
    ("Produits & marques", "knowledge_samples/02_produits_marques.md", "general"),
    ("Équipe & expertises", "knowledge_samples/03_equipe_expertise.md", "equipe"),
]


def _api(base, method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-url", default="http://localhost:8000")
    ap.add_argument("--email", default="demo@jenny.ai")
    ap.add_argument("--password", default="Demo!1234")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    base = args.api_url.rstrip("/") + "/api/v1"
    dry = args.dry_run
    tag = "[dry-run] " if dry else ""

    code, tok = _api(base, "POST", "/auth/login", body={"email": args.email, "password": args.password})
    if code != 200 or not tok:
        print(f"Login échoué ({code})", file=sys.stderr)
        sys.exit(1)
    token = tok["access_token"]
    _, me = _api(base, "GET", "/auth/me", token)
    bid = me["business_id"]
    print(f"Business démo : {bid}\n")

    # ── 1. Dédup KB par titre (garde la plus récente) ──
    _, entries = _api(base, "GET", f"/knowledge/entries/{bid}", token)
    entries = entries if isinstance(entries, list) else (entries or {}).get("entries", [])
    by_title: dict[str, list] = {}
    for e in entries:
        by_title.setdefault(e["title"], []).append(e)
    dedup = 0
    for title, group in by_title.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda e: e.get("created_at") or "", reverse=True)  # plus récente d'abord
        for old in group[1:]:
            print(f"{tag}dédup KB : « {title} » (doublon {old['id'][:8]})")
            if not dry:
                _api(base, "DELETE", f"/knowledge/entries/{bid}/{old['id']}", token)
            dedup += 1

    # ── 2. Re-sync des connaissances-source (applique les corrections de contenu) ──
    resync = 0
    for title, rel, category in SAMPLE_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        # Supprime toutes les entrées existantes de ce titre, puis ré-ajoute.
        for e in by_title.get(title, []):
            if not dry:
                _api(base, "DELETE", f"/knowledge/entries/{bid}/{e['id']}", token)
        print(f"{tag}re-sync KB : « {title} »")
        if not dry:
            _api(base, "POST", "/knowledge/text", token,
                 {"business_id": bid, "title": title, "content": content, "category": category})
        resync += 1

    # ── 3. Prestations de test (« Test … QA ») ──
    _, pr = _api(base, "GET", "/prestations", token)
    prestations = (pr or {}).get("prestations", pr if isinstance(pr, list) else [])
    purged_p = 0
    for p in prestations:
        name = (p.get("name") or "").lower()
        if "test" in name or " qa" in name or name.endswith("qa"):
            print(f"{tag}suppr. prestation de test : « {p['name']} »")
            if not dry:
                _api(base, "DELETE", f"/prestations/{p['id']}", token)
            purged_p += 1

    # ── 4. Rendez-vous hors horaires (avant 8h / après 20h = données de test qui
    #      faussent les heures de pointe) ──
    _, ap_list = _api(base, "GET", "/appointments", token)
    appts = (ap_list or {}).get("appointments", ap_list if isinstance(ap_list, list) else [])
    purged_a = 0
    for a in appts:
        start = a.get("start_at") or ""
        hour = None
        if "T" in start:
            try:
                hour = int(start.split("T")[1][:2])
            except (ValueError, IndexError):
                hour = None
        if hour is not None and (hour < 8 or hour >= 20):
            print(f"{tag}suppr. RDV hors horaires ({start}) : {a.get('title', '')}")
            if not dry:
                _api(base, "DELETE", f"/appointments/{a['id']}", token)
            purged_a += 1

    print(
        f"\n{tag}Terminé — KB dédupliquée : {dedup}, re-sync : {resync}, "
        f"prestations test purgées : {purged_p}, RDV hors horaires purgés : {purged_a}."
    )


if __name__ == "__main__":
    main()
