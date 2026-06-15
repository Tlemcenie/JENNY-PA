"""Service du catalogue de prestations (lecture pour le moteur + actions).

Charge les prestations d'un business, en trouve une par nom (tolérant aux
variantes), et formate le catalogue pour le contexte du LLM — afin que Jenny
donne des prix EXACTS et la bonne durée de RDV, sans rien inventer.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from sqlalchemy import select

from jenny.core.logging import get_logger
from jenny.domain.models.prestation import Prestation

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


async def load_active_prestations(db: AsyncSession, business_id: UUID) -> list[Prestation]:
    """Liste les prestations actives d'un business, triées pour l'affichage."""
    try:
        rows = (
            await db.execute(
                select(Prestation)
                .where(Prestation.business_id == business_id, Prestation.is_active.is_(True))
                .order_by(Prestation.sort_order.asc(), Prestation.name.asc())
            )
        ).scalars().all()
        return list(rows)
    except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
        logger.warning("prestation.load_error", error=str(exc))
        return []


def find_prestation(prestations: list[Prestation], query: str) -> Prestation | None:
    """Trouve la prestation correspondant le mieux à un nom libre.

    Tolérant : « balayage », « un balayage », « Balayage cheveux longs » →
    matche « Balayage ». Compare par inclusion normalisée puis par recouvrement
    de mots ; renvoie None si rien de net.
    """
    if not query or not prestations:
        return None
    q = _norm(query)
    q_words = {w for w in q.split() if len(w) > 2}

    # 1) Inclusion directe (nom de la prestation contenu dans la requête ou l'inverse).
    for p in prestations:
        n = _norm(p.name)
        if n and (n in q or q in n):
            return p

    # 2) Meilleur recouvrement de mots.
    best, best_score = None, 0
    for p in prestations:
        n_words = {w for w in _norm(p.name).split() if len(w) > 2}
        score = len(q_words & n_words)
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= 1 else None


# Connecteurs séparant plusieurs prestations dans une même demande.
_MULTI_SPLIT_RE = re.compile(r"\s*(?:\bet\b|\bpuis\b|\bavec\b|\+|&|,|/)\s*", re.I)


def match_prestations(prestations: list[Prestation], query: str) -> list[Prestation]:
    """Trouve TOUTES les prestations citées (« coupe et couleur » → [Coupe, Couleur]).

    Découpe la demande sur «  et / puis / avec / + / & / , / / » et matche chaque
    morceau au catalogue. Dédoublonne, garde l'ordre. Repli sur la requête entière
    si le découpage ne donne rien.
    """
    if not query or not prestations:
        return []
    parts = [p for p in _MULTI_SPLIT_RE.split(query) if p and p.strip()]
    matched: list[Prestation] = []
    seen: set = set()
    for part in parts or [query]:
        p = find_prestation(prestations, part)
        if p is not None and p.id not in seen:
            seen.add(p.id)
            matched.append(p)
    if not matched:
        p = find_prestation(prestations, query)
        if p is not None:
            matched.append(p)
    return matched


def format_catalog(prestations: list[Prestation], *, max_items: int = 30) -> str:
    """Formate le catalogue pour le prompt (prix en euros, durée)."""
    if not prestations:
        return ""
    lines = ["Catalogue des prestations (utilise ces prix et durées EXACTS) :"]
    for p in prestations[:max_items]:
        price = f"{p.price_eur:.0f}€" if p.price_cents else "prix sur demande"
        lines.append(f"  - {p.name} ({p.category}) — {p.duration_minutes} min — {price}")
    return "\n".join(lines)
