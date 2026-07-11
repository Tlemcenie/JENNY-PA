"""Re-ranking lexical des candidats RAG (partagé par tous les chemins de recherche).

La recherche vectorielle seule ramène parfois un passage « à côté » : un bonus
lexical (mots de la question présents dans le passage) recentre sur les chunks
qui parlent littéralement du sujet demandé, et CREUSE L'ÉCART entre les
questions dont la réponse est en base et les questions hors-sujet — c'est sur
cette échelle blendée que les seuils du moteur sont calibrés (voir
GAP_SCORE_FLOOR dans engine/intelligence.py).

Score final : 0.7 · vectoriel + 0.3 · lexical.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-zà-ÿ0-9]+")


def tokens(text: str) -> set[str]:
    """Tokens alphanumériques minuscules (≥ 3 lettres) pour le score lexical."""
    return {t for t in _WORD_RE.findall(text.lower()) if len(t) >= 3}


def rerank(query: str, docs: list, top_k: int) -> list:
    """Re-classe les candidats en combinant score vectoriel et recouvrement lexical.

    Les objets de ``docs`` doivent exposer ``content`` et ``score`` (mutés en
    place : le score devient le score blendé).
    """
    q = tokens(query)
    if not q:
        return docs[:top_k]
    rescored = []
    for d in docs:
        lex = len(q & tokens(d.content)) / len(q)
        d.score = 0.7 * float(d.score) + 0.3 * lex
        rescored.append(d)
    rescored.sort(key=lambda d: d.score, reverse=True)
    return rescored[:top_k]
