"""Éval du RAG sur la vraie base pgvector (KB coiffeur).

Mesure la recherche (recall@1/3/5, MRR) et la décision de lacune
(taux de fausse lacune, taux de fausse réponse) en passant par le vrai
chemin du chat : FAQAgent → grounding moteur → is_knowledge_gap.

Usage (KB seedée par scripts/seed_kb_coiffeur.py) :
    python src/jenny/eval/rag_eval.py                 # business démo
    python src/jenny/eval/rag_eval.py --sweep         # balaye les seuils
    python src/jenny/eval/rag_eval.py --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DATA_PATH = Path(__file__).resolve().parent / "data" / "rag_questions_coiffeur.json"
DEMO_SLUG = "demo"
# seuil du grounding moteur
ENGINE_GROUNDING_THRESHOLD = 0.35
KS = (1, 3, 5)


@dataclass
class Question:
    """Une question d'éval."""

    q: str
    keys: list[str] = field(default_factory=list)
    kind: str = "direct"
    keywords: list[str] = field(default_factory=list)
    # jamais vu au réglage
    holdout: bool = False

    @property
    def answerable(self) -> bool:
        return self.kind != "hors_kb"


def load_questions(path: Path = DATA_PATH) -> list[Question]:
    """Charge le jeu de questions."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        Question(
            q=r["q"],
            keys=list(r.get("keys") or []),
            kind=r.get("kind", "direct"),
            keywords=list(r.get("keywords") or []),
            holdout=bool(r.get("holdout")),
        )
        for r in raw
    ]


def _meta(doc) -> dict:
    meta = doc.get("metadata") if isinstance(doc, dict) else getattr(doc, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _content(doc) -> str:
    return (doc.get("content") if isinstance(doc, dict) else getattr(doc, "content", "")) or ""


def is_relevant(doc, question: Question) -> bool:
    """Doc pertinent pour la question ?"""
    if _meta(doc).get("kb_key") in question.keys:
        return True
    if question.keywords:
        from jenny.rag.lexique import fold

        blob = fold(_content(doc))
        return any(fold(k) in blob for k in question.keywords)
    return False


def first_rank(docs: list, question: Question) -> int | None:
    """Rang (1..n) du 1er doc pertinent."""
    for i, d in enumerate(docs, start=1):
        if is_relevant(d, question):
            return i
    return None


def retrieval_metrics(ranks: list[int | None]) -> dict:
    """recall@k et MRR."""
    n = len(ranks) or 1
    out = {f"recall@{k}": sum(1 for r in ranks if r is not None and r <= k) / n for k in KS}
    out["mrr"] = sum(1.0 / r for r in ranks if r) / n
    return out


def decision_metrics(rows: list[tuple[bool, bool]]) -> dict:
    """Fausse lacune / fausse réponse."""
    ans = [gap for answerable, gap in rows if answerable]
    unans = [gap for answerable, gap in rows if not answerable]
    return {
        "false_gap_rate": (sum(ans) / len(ans)) if ans else 0.0,
        "false_answer_rate": (sum(1 for g in unans if not g) / len(unans)) if unans else 0.0,
        "answerable": len(ans),
        "unanswerable": len(unans),
    }


async def resolve_business(slug: str) -> str:
    """Id du business par slug."""
    from sqlalchemy import text

    from jenny.db.session import async_session_factory

    async with async_session_factory() as session:
        bid = (
            await session.execute(text("SELECT id FROM businesses WHERE slug = :s"), {"s": slug})
        ).scalar()
    if bid is None:
        raise SystemExit(f"Business introuvable : {slug}")
    return str(bid)


def build_retriever():
    """Retriever comme en prod."""
    from jenny.rag.embeddings import get_default_embedder
    from jenny.rag.retriever import VectorRetriever
    from jenny.rag.vector_store import PgVectorStore

    embedder = get_default_embedder()
    return VectorRetriever(embedder=embedder, vector_store=PgVectorStore(embedder.dimension))


def _docs(hits) -> list[dict]:
    return [{"content": h.content, "score": h.score, "metadata": h.metadata} for h in hits]


async def run_pipeline(questions: list[Question], business_id: str, retriever) -> list[dict]:
    """Vrai chemin du chat, question par question."""
    from jenny.agents.faq_agent import FAQAgent
    from jenny.engine.intelligence import is_knowledge_gap
    from jenny.engine.state_manager import ConversationState

    agent = FAQAgent(retriever=retriever)
    rows: list[dict] = []
    for q in questions:
        hits = _docs(await retriever.search(q.q, business_id=business_id, top_k=max(KS)))
        state = ConversationState(business_id=UUID(business_id))
        state.add_user_message(q.q)
        state.current_intent = "faq"
        state.intent_confidence = 0.9
        out = await agent.handle(state)
        docs = out.get("documents") or []
        if not docs:
            # grounding transverse moteur
            docs = _docs(
                await retriever.search(
                    q.q,
                    business_id=business_id,
                    top_k=3,
                    score_threshold=ENGINE_GROUNDING_THRESHOLD,
                )
            )
        gap = is_knowledge_gap(intent="faq", documents=docs, action_result=None, message=q.q)
        rows.append(
            {
                "q": q.q,
                "kind": q.kind,
                "holdout": q.holdout,
                "answerable": q.answerable,
                "rank": first_rank(hits, q) if q.answerable else None,
                "top_score": round(max((d["score"] for d in hits), default=0.0), 4),
                "top_keys": [_meta(d).get("kb_key") for d in hits[:3]],
                "injected": len(docs),
                "injected_relevant": any(is_relevant(d, q) for d in docs),
                "gap": gap,
            }
        )
    return rows


def summarize(rows: list[dict], split: bool = True) -> dict:
    """Métriques globales + par type."""
    ans_rows = [r for r in rows if r["answerable"]]
    out = {"n": len(rows), **retrieval_metrics([r["rank"] for r in ans_rows])}
    out.update(decision_metrics([(r["answerable"], r["gap"]) for r in rows]))
    by_kind = {}
    for kind in sorted({r["kind"] for r in rows}):
        sub = [r for r in rows if r["kind"] == kind]
        entry = {"n": len(sub)}
        if sub[0]["answerable"]:
            entry.update(retrieval_metrics([r["rank"] for r in sub]))
            entry["false_gap_rate"] = sum(r["gap"] for r in sub) / len(sub)
        else:
            entry["false_answer_rate"] = sum(1 for r in sub if not r["gap"]) / len(sub)
        by_kind[kind] = entry
    out["by_kind"] = by_kind
    # docs injectés mais hors sujet
    injected = [r for r in ans_rows if r["injected"]]
    out["injected_relevant_rate"] = (
        sum(r["injected_relevant"] for r in injected) / len(injected) if injected else 0.0
    )
    if split and any(r.get("holdout") for r in rows):
        # réglage vs jamais vu
        out["tuning"] = summarize([r for r in rows if not r.get("holdout")], split=False)
        out["holdout"] = summarize([r for r in rows if r.get("holdout")], split=False)
    return out


# ── balayage des seuils ──


async def collect_candidates(questions: list[Question], business_id: str, pool: int = 10):
    """Candidats bruts (vectoriel, lexical, rrf)."""
    from jenny.db.session import async_session_factory
    from jenny.rag.retriever import embed_query

    retriever = build_retriever()
    out = []
    for q in questions:
        emb = await embed_query(retriever.embedder, q.q)
        async with async_session_factory() as session:
            docs = await retriever.vector_store.search(
                session, business_id, emb, top_k=pool, query_text=q.q
            )
        out.append(
            (
                q,
                [
                    {
                        "content": d.content,
                        "metadata": d.metadata,
                        "v": d.vector_score,
                        "l": d.lexical_score,
                        "f": d.fused,
                    }
                    for d in docs
                ],
            )
        )
    return out


def simulate(
    cands,
    *,
    w: float,
    fusion: str,
    faq_min: float,
    floor: float,
    strong: float,
    min_cov: float,
    max_gap: float,
    strong_cov: float = 0.0,
) -> dict:
    """Rejoue la décision avec d'autres réglages."""
    from jenny.agents.faq_agent import select_documents
    from jenny.engine.intelligence import gap_verdict
    from jenny.rag.rerank import fusion_key

    rows = []
    for q, docs in cands:
        scored = [{**d, "score": w * d["v"] + (1 - w) * d["l"]} for d in docs]
        fmax = max((d["f"] for d in scored), default=0.0)
        scored.sort(key=lambda d: fusion_key(d["score"], d["f"], fmax, fusion), reverse=True)
        top5 = scored[: max(KS)]
        chosen = select_documents(
            [d for d in scored if d["score"] >= faq_min][:3],
            min_score=faq_min,
            max_gap=max_gap,
        )
        if not chosen:
            chosen = [d for d in scored if d["score"] >= ENGINE_GROUNDING_THRESHOLD][:3]
        grounded, _reason, _top = gap_verdict(
            chosen,
            q.q,
            floor=floor,
            strong=strong,
            min_coverage=min_cov,
            strong_coverage=strong_cov,
        )
        rows.append(
            {
                "q": q.q,
                "kind": q.kind,
                "holdout": q.holdout,
                "answerable": q.answerable,
                "rank": first_rank(top5, q) if q.answerable else None,
                "gap": not grounded,
                "injected": len(chosen),
                "injected_relevant": any(is_relevant(d, q) for d in chosen),
            }
        )
    return summarize(rows)


def sweep(cands) -> list[tuple[float, dict, dict]]:
    """Grille de réglages, triée."""
    grid = itertools.product(
        (0.6, 0.7, 0.8),  # poids vectoriel
        ("mix", "rrf", "score"),
        (ENGINE_GROUNDING_THRESHOLD,),  # seuil injection
        (0.30, 0.35, 0.40, 0.45, 0.50),  # plancher
        (0.55, 0.60, 0.65, 0.70, 0.75, 0.80),  # fort
        (0.0, 0.34, 0.5, 0.67, 1.0),  # couverture sujet
        (0.10, 0.20, 1.0),  # écart au meilleur
        (0.0, 0.34, 0.5),  # couverture si fort
    )
    results = []
    for w, fusion, faq_min, floor, strong, min_cov, max_gap, strong_cov in grid:
        if strong <= floor or strong_cov > min_cov:
            continue
        params = {
            "w": w,
            "fusion": fusion,
            "faq_min": faq_min,
            "floor": floor,
            "strong": strong,
            "min_cov": min_cov,
            "max_gap": max_gap,
            "strong_cov": strong_cov,
        }
        m = simulate(cands, **params)
        # fausse réponse = pire (bluff)
        cost = m["false_gap_rate"] + 1.5 * m["false_answer_rate"] - 0.5 * m["mrr"]
        results.append((cost, params, m))
    results.sort(key=lambda r: r[0])
    return results


def _fmt(m: dict) -> str:
    return (
        f"n={m['n']}  R@1={m['recall@1']:.3f}  R@3={m['recall@3']:.3f}  "
        f"R@5={m['recall@5']:.3f}  MRR={m['mrr']:.3f}  "
        f"fausse_lacune={m['false_gap_rate']:.3f}  fausse_reponse={m['false_answer_rate']:.3f}  "
        f"docs_injectes_pertinents={m['injected_relevant_rate']:.3f}"
    )


async def main(slug: str, do_sweep: bool, json_path: str | None, label: str) -> dict:
    questions = load_questions()
    business_id = await resolve_business(slug)
    retriever = build_retriever()
    rows = await run_pipeline(questions, business_id, retriever)
    summary = summarize(rows)
    print(f"[{label}] {_fmt(summary)}")
    for kind, m in summary["by_kind"].items():
        print(f"   {kind:9s} {json.dumps({k: round(v, 3) for k, v in m.items()})}")
    for part in ("tuning", "holdout"):
        if part in summary:
            print(f"   {part:9s} {_fmt(summary[part])}")
    report = {"label": label, "summary": summary, "rows": rows}
    if do_sweep:
        # réglage sans le holdout
        tuning = [q for q in questions if not q.holdout]
        cands = await collect_candidates(tuning, business_id)
        best = sweep(cands)[:10]
        print("Meilleurs réglages :")
        for cost, params, m in best:
            print(f"  cout={cost:.3f} {params} -> {_fmt(m)}")
        report["sweep"] = [{"cost": c, "params": p, "metrics": m} for c, p, m in best]
    if json_path:
        Path(json_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Éval RAG coiffeur (pgvector live)")
    parser.add_argument("--slug", default=DEMO_SLUG)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--json", default=None)
    parser.add_argument("--label", default="eval")
    args = parser.parse_args()
    asyncio.run(main(args.slug, args.sweep, args.json, args.label))
