"""Score lexical et fusion des candidats RAG.

Score final : 0.7 · vectoriel + 0.3 · lexical (racines + synonymes).
L'ordre vient d'une fusion RRF (vectoriel, texte intégral, lexical).
"""

from __future__ import annotations

import re

from jenny.rag.lexique import coverage, doc_pool, query_terms

_WORD_RE = re.compile(r"[a-zà-ÿ0-9]+")

VECTOR_WEIGHT = 0.7
LEXICAL_WEIGHT = 0.3
# constante RRF classique
RRF_K = 60
# poids du rang RRF (mode mix)
RRF_WEIGHT = 0.10


def tokens(text: str) -> set[str]:
    """Tokens bruts (≥ 3 lettres)."""
    return {t for t in _WORD_RE.findall(text.lower()) if len(t) >= 3}


def lexical_score(query: str, content: str, title: str = "") -> float:
    """Part des termes de la question couverts."""
    return coverage(query_terms(query), doc_pool(f"{title}\n{content}" if title else content))


def blend(vector_score: float, lex: float) -> float:
    """Score blendé (échelle des seuils)."""
    return VECTOR_WEIGHT * float(vector_score) + LEXICAL_WEIGHT * float(lex)


def rrf(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Fusion Reciprocal Rank."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank)
    return fused


def fusion_key(score: float, fused: float, fused_max: float, mode: str = "mix") -> float:
    """Clé de tri finale."""
    if mode == "score":
        return score
    rel = fused / fused_max if fused_max > 0 else 0.0
    if mode == "rrf":
        return rel + 1e-6 * score
    return score + RRF_WEIGHT * rel


def _title_of(d) -> str:
    meta = getattr(d, "metadata", None)
    if not isinstance(meta, dict):
        return ""
    return meta.get("title") or ""


def rerank(query: str, docs: list, top_k: int) -> list:
    """Re-classe en mélangeant vectoriel et lexical.

    Les objets exposent ``content`` et ``score`` (score muté en place).
    """
    terms = query_terms(query)
    if not docs:
        return []
    for d in docs:
        pool = doc_pool(f"{_title_of(d)}\n{d.content}")
        d.score = blend(d.score, coverage(terms, pool))
    ranked = sorted(docs, key=lambda d: d.score, reverse=True)
    return ranked[:top_k]
