"""Collecte de corpus + tokenizer BPE maison + tokenisation → bins.

But : construire un gros corpus de texte FR (FAQ / Q&R / langue générale) pour
entraîner le LM NanoGPT **from scratch** (aucun fine-tune, aucun poids pré-entraîné).

Sources (best-effort, cumulées jusqu'à la cible) :
  1. Données internes Jenny (FAQ d'éval, intents générés, base de connaissances).
  2. Datasets publics via HuggingFace `datasets` (Wikipédia FR, Q&R FR).
  3. Scraping léger de pages FAQ publiques (stdlib, poli, best-effort).

Le tokenizer est lui aussi entraîné de zéro (BPE byte-level sur le corpus) — il
n'apporte aucune connaissance, il ne fait que découper le texte.

Usage :
    python -m nanogpt.data --target-mb 40 --vocab-size 16000
Produit :
    data/raw/corpus_fr.txt
    checkpoints/nanogpt/tokenizer.json
    data/processed/train.bin, val.bin, meta.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "corpus_fr.txt"
PROC = ROOT / "data" / "processed"
TOKENIZER_PATH = ROOT / "checkpoints" / "nanogpt" / "tokenizer.json"

# Pages FR publiques à scraper (best-effort ; échecs ignorés). Wikipédia = fiable,
# libre, et pile dans le use case (coiffure / beauté / relation & service client).
FAQ_URLS = [
    "https://fr.wikipedia.org/wiki/Foire_aux_questions",
    "https://fr.wikipedia.org/wiki/Service_client",
    "https://fr.wikipedia.org/wiki/Relation_client",
    "https://fr.wikipedia.org/wiki/Exp%C3%A9rience_client",
    "https://fr.wikipedia.org/wiki/Satisfaction_du_client",
    "https://fr.wikipedia.org/wiki/Fid%C3%A9lisation",
    "https://fr.wikipedia.org/wiki/Centre_d%27appels",
    "https://fr.wikipedia.org/wiki/R%C3%A9clamation",
    "https://fr.wikipedia.org/wiki/Coiffure",
    "https://fr.wikipedia.org/wiki/Salon_de_coiffure",
    "https://fr.wikipedia.org/wiki/Coloration_capillaire",
    "https://fr.wikipedia.org/wiki/Coupe_de_cheveux",
    "https://fr.wikipedia.org/wiki/Soin_capillaire",
    "https://fr.wikipedia.org/wiki/Coiffeur",
    "https://fr.wikipedia.org/wiki/Barbier",
    "https://fr.wikipedia.org/wiki/Manucure",
    "https://fr.wikipedia.org/wiki/Esth%C3%A9tique",
    "https://fr.wikipedia.org/wiki/Maquillage",
    "https://fr.wikipedia.org/wiki/Rendez-vous",
    "https://fr.wikipedia.org/wiki/Commerce_%C3%A9lectronique",
    "https://fr.wikipedia.org/wiki/Vente",
    "https://fr.wikipedia.org/wiki/Paiement",
    "https://fr.wikipedia.org/wiki/Devis",
    "https://fr.wikipedia.org/wiki/Livraison_(logistique)",
]


def _log(msg: str) -> None:
    print(f"[data] {msg}", flush=True)


# ──────────────────────────────────────────────────────────────────────────
# 1. Sources
# ──────────────────────────────────────────────────────────────────────────
def _internal_texts() -> list[str]:
    """Textes internes Jenny : FAQ d'éval, intents, KB de seed."""
    out: list[str] = []
    # Scénarios d'éval (connaissances FAQ inline)
    try:
        from jenny.eval.scenarios import SCENARIOS  # type: ignore

        for sc in SCENARIOS:
            out.extend(getattr(sc, "knowledge", []) or [])
            for turn in getattr(sc, "turns", []) or []:
                msg = getattr(turn, "message", None) or getattr(turn, "prompt", None)
                if msg:
                    out.append(str(msg))
    except Exception as exc:
        _log(f"scénarios d'éval indisponibles ({exc})")

    # JSONL générés (intents / ner) — on récupère les champs texte
    for name in ("intents.jsonl", "ner.jsonl"):
        p = ROOT / "data" / "generated" / name
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                for key in ("text", "query", "question", "utterance", "content"):
                    if isinstance(obj.get(key), str):
                        out.append(obj[key])
        except Exception as exc:
            _log(f"lecture {name} échouée ({exc})")

    _log(f"interne : {len(out)} extraits")
    return out


class _TextExtractor(HTMLParser):
    """Strip HTML → texte (stdlib, pas de dépendance)."""

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            t = data.strip()
            if t:
                self.parts.append(t)


def _scrape_faq(urls: list[str], budget_chars: int) -> list[str]:
    """Scraping poli de pages FAQ publiques (best-effort)."""
    out: list[str] = []
    total = 0
    for url in urls:
        if total >= budget_chars:
            break
        try:
            req = Request(url, headers={"User-Agent": "JennyResearchBot/1.0 (educational)"})
            with urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            ext = _TextExtractor()
            ext.feed(html)
            text = "\n".join(ext.parts)
            text = re.sub(r"\n{3,}", "\n\n", text)
            out.append(text)
            total += len(text)
            _log(f"scrape OK {url} (+{len(text)} car.)")
            time.sleep(1.0)  # poli
        except Exception as exc:
            _log(f"scrape ignoré {url} ({exc})")
    return out


# Datasets HF cumulés jusqu'à la cible (repo, config, field, kind).
#   kind="text" → champ texte direct ; kind="qa" → Q&R (question/contexte/réponse).
# Les sources *gated* (OSCAR, CulturaX) nécessitent un token HF accepté ; sinon
# elles sont ignorées en silence. Pour un gros run, fais `huggingface-cli login`
# ou exporte HF_TOKEN (compte gratuit) — ça enlève aussi les limites de débit.
HF_SOURCES = [
    ("HuggingFaceFW/fineweb-2", "fra_Latn", "text", "text"),   # web FR haute qualité (gros)
    ("wikimedia/wikipedia", "20231101.fr", "text", "text"),     # encyclopédie FR (propre)
    ("allenai/c4", "fr", "text", "text"),                       # Common Crawl FR nettoyé
    ("uonlp/CulturaX", "fr", "text", "text"),                   # *gated* — multilingue nettoyé
    ("oscar-corpus/OSCAR-2301", "fr", "text", "text"),          # *gated* — crawl web FR massif
    ("etalab-ia/piaf", None, None, "qa"),                       # Q&R FR (saveur FAQ)
    ("lincoln/newsquadfr", None, None, "qa"),                   # Q&R FR
]


def _extract_row(row: dict, field: str | None, kind: str) -> str | None:
    """Extrait le texte d'une ligne (texte direct, ou reformaté Q&R/FAQ)."""
    if kind == "qa":
        q = row.get("question")
        ctx = row.get("context")
        ans = row.get("answers")
        a = None
        if isinstance(ans, dict):
            t = ans.get("text")
            a = (t[0] if isinstance(t, list) and t else t) if t else None
        elif isinstance(ans, str):
            a = ans
        parts = [p for p in (ctx, f"Question : {q}" if q else None,
                             f"Réponse : {a}" if a else None) if p]
        return "\n".join(str(p) for p in parts) if parts else None
    return row.get(field) if field else None


def _hf_stream(target_chars: int) -> list[str]:
    """Texte FR en flux depuis plusieurs datasets HuggingFace (bulk + Q&R/FAQ)."""
    out: list[str] = []
    total = 0
    try:
        from datasets import load_dataset  # type: ignore
    except Exception as exc:
        _log(f"`datasets` indisponible ({exc}) — on saute les sources HF")
        return out

    for repo, config, field, kind in HF_SOURCES:
        if total >= target_chars:
            break
        try:
            _log(f"HF stream {repo} ({config or 'default'}, {kind})…")
            ds = load_dataset(repo, config, split="train", streaming=True)  # type: ignore[arg-type]
            n0 = total
            for i, row in enumerate(ds):
                if not isinstance(row, dict):
                    continue
                txt = _extract_row(row, field, kind)
                if not txt:
                    continue
                out.append(str(txt))
                total += len(txt)
                if total >= target_chars:
                    break
                if i % 5000 == 0:
                    _log(f"  …{total / 1e6:.1f} Mo")
            _log(f"HF {repo} : +{(total - n0) / 1e6:.1f} Mo (cumulé {total / 1e6:.1f} Mo)")
        except Exception as exc:
            _log(f"HF {repo} ignoré ({exc})")
    return out


# ──────────────────────────────────────────────────────────────────────────
# 2. Pipeline
# ──────────────────────────────────────────────────────────────────────────
def collect_corpus(target_mb: float) -> Path:
    """Assemble le corpus FR jusqu'à ~target_mb Mo, écrit data/raw/corpus_fr.txt."""
    target_chars = int(target_mb * 1_000_000)
    RAW.parent.mkdir(parents=True, exist_ok=True)

    chunks: list[str] = []
    chunks += _internal_texts()
    # Un peu de FAQ scrapée (plafonnée), puis le gros via datasets.
    chunks += _scrape_faq(FAQ_URLS, budget_chars=min(target_chars // 10, 200_000))
    used = sum(len(c) for c in chunks)
    if used < target_chars:
        chunks += _hf_stream(target_chars - used)

    text = "\n\n".join(c.strip() for c in chunks if c and c.strip())
    # Nettoyage léger
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    RAW.write_text(text, encoding="utf-8")
    mb = len(text.encode("utf-8")) / 1e6
    _log(f"corpus écrit : {RAW} ({mb:.1f} Mo, {len(text):,} car.)")
    if mb < 0.5:
        _log("⚠ corpus très petit — vérifie l'accès réseau aux datasets HF.")
    return RAW


def train_tokenizer(corpus_path: Path, vocab_size: int) -> Path:
    """Entraîne un tokenizer BPE byte-level FROM SCRATCH sur le corpus."""
    from tokenizers import Tokenizer  # type: ignore
    from tokenizers.decoders import ByteLevel as ByteLevelDecoder  # type: ignore
    from tokenizers.models import BPE  # type: ignore
    from tokenizers.pre_tokenizers import ByteLevel  # type: ignore
    from tokenizers.trainers import BpeTrainer  # type: ignore

    tok = Tokenizer(BPE(unk_token="<unk>"))
    tok.pre_tokenizer = ByteLevel(add_prefix_space=False)
    tok.decoder = ByteLevelDecoder()  # decode() reconstruit texte propre (espaces/newlines)
    trainer = BpeTrainer(
        vocab_size=vocab_size,
        special_tokens=["<unk>", "<bos>", "<eos>", "<pad>"],
        show_progress=True,
    )
    tok.train([str(corpus_path)], trainer)
    TOKENIZER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tok.save(str(TOKENIZER_PATH))
    _log(f"tokenizer entraîné : {TOKENIZER_PATH} (vocab={tok.get_vocab_size()})")
    return TOKENIZER_PATH


def tokenize_corpus(corpus_path: Path, tokenizer_path: Path, val_frac: float) -> dict:
    """Encode le corpus → train.bin / val.bin (uint16) + meta.json."""
    import numpy as np
    from tokenizers import Tokenizer  # type: ignore

    tok = Tokenizer.from_file(str(tokenizer_path))
    text = corpus_path.read_text(encoding="utf-8")
    ids = tok.encode(text).ids
    n = len(ids)
    if n == 0:
        raise SystemExit("Corpus vide après tokenisation — abandon.")
    split = int(n * (1 - val_frac))
    PROC.mkdir(parents=True, exist_ok=True)
    np.array(ids[:split], dtype=np.uint16).tofile(PROC / "train.bin")
    np.array(ids[split:], dtype=np.uint16).tofile(PROC / "val.bin")
    meta = {
        "vocab_size": tok.get_vocab_size(),
        "total_tokens": n,
        "train_tokens": split,
        "val_tokens": n - split,
        "tokenizer": str(tokenizer_path.relative_to(ROOT)),
    }
    (PROC / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _log(f"tokenisé : {n:,} tokens (train {split:,} / val {n-split:,}), vocab {meta['vocab_size']}")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description="Collecte corpus FR + tokenizer + bins (from scratch).")
    ap.add_argument("--target-mb", type=float, default=40.0, help="Taille cible du corpus (Mo).")
    ap.add_argument("--vocab-size", type=int, default=16000, help="Taille du vocabulaire BPE.")
    ap.add_argument("--val-frac", type=float, default=0.1, help="Fraction de validation.")
    ap.add_argument("--skip-collect", action="store_true", help="Réutilise le corpus existant.")
    args = ap.parse_args()

    if not args.skip_collect or not RAW.exists():
        collect_corpus(args.target_mb)
    train_tokenizer(RAW, args.vocab_size)
    tokenize_corpus(RAW, TOKENIZER_PATH, args.val_frac)
    _log("✓ pipeline data terminé.")
    return 0


if __name__ == "__main__":
    _code = main()
    # Sortie forcée : le streaming HF `datasets` laisse parfois des threads réseau
    # non-daemon qui font traîner l'arrêt du process (et bloqueraient un `&&` placé
    # derrière, ex. `data && train`). On termine net une fois le pipeline fini.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_code or 0)
