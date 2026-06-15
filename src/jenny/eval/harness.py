"""Exécution du banc d'essai : moteur réel (Ollama) + RAG en mémoire + scoring.

Pour chaque scénario, on amorce une base de connaissances **en mémoire** (vrais
embeddings nomic-embed-text), on fait tourner le VRAI moteur conversationnel
(qwen2.5:3b) tour par tour, puis on score chaque réponse selon les attentes du
scénario. Aucune dépendance Postgres : l'éval est hermétique et reproductible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from jenny.agents.fallback_agent import FallbackAgent
from jenny.agents.faq_agent import FAQAgent
from jenny.agents.router import AgentRouter
from jenny.core.logging import get_logger
from jenny.engine.conversation_engine import ConversationEngine, EngineRequest
from jenny.engine.intelligence import detect_language
from jenny.engine.response_generator import _AI_TERMS_RE, _META_LEAK_RE, ResponseGenerator
from jenny.engine.state_manager import StateManager
from jenny.rag.memory_store import _cosine_similarity

if TYPE_CHECKING:
    from jenny.eval.scenarios import Scenario, Turn

logger = get_logger(__name__)

# Intentions purement relationnelles : pas de recherche RAG.
_RELATIONAL = {"greeting", "closing", "small_talk", "escalation"}


@dataclass
class _Hit:
    content: str
    score: float
    metadata: dict


class EvalRetriever:
    """Retriever RAG en mémoire (vrais embeddings) compatible avec ``FAQAgent``."""

    def __init__(self, embedder) -> None:
        self.embedder = embedder
        self._docs: list[tuple[str, list[float], dict]] = []

    async def seed(self, texts: list[str]) -> None:
        if not texts:
            return
        vecs = await self.embedder.embed_batch(texts)
        for t, v in zip(texts, vecs, strict=False):
            self._docs.append((t, v, {"source": "eval"}))

    async def search(self, query: str, *, business_id=None, top_k: int = 3, **_) -> list[_Hit]:
        if not self._docs:
            return []
        qv = await self.embedder.embed_text(query)
        scored = [
            _Hit(content=c, score=_cosine_similarity(qv, v), metadata=m)
            for c, v, m in self._docs
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]


class EvalRouter(AgentRouter):
    """Routeur contrôlé : consulte toujours la KB pour les intentions « question ».

    En production le routage dépend du modèle d'intention ; pour mesurer le
    grounding de façon fiable, on s'assure ici que la base de connaissances est
    bien interrogée pour toute demande non purement relationnelle.
    """

    def __init__(self, faq: FAQAgent, fallback: FallbackAgent) -> None:
        super().__init__()
        self.register("faq", faq)
        self.register("fallback", fallback)
        self._faq = faq
        self._fallback = fallback

    async def route(self, state) -> dict:
        intent = state.current_intent or "general"
        agent = self._fallback if intent in _RELATIONAL else self._faq
        result = await agent.handle(state)
        return {
            "agent": getattr(agent, "name", "agent"),
            "documents": result.get("documents", []),
            "action_result": result.get("action_result"),
        }


def build_eval_engine(provider, retriever: EvalRetriever) -> ConversationEngine:
    """Moteur conversationnel pour l'éval (état en mémoire, RAG en mémoire)."""
    router = EvalRouter(FAQAgent(retriever=retriever), FallbackAgent())
    return ConversationEngine(
        state_manager=StateManager(redis_url="redis://localhost:6390/0"),  # force mémoire
        agent_router=router,
        response_generator=ResponseGenerator(provider),
    )


# ── Scoring ───────────────────────────────────────────────────────────────────


def _forbidden_identity_or_leak(text: str) -> list[str]:
    """Renvoie les violations « persona » trouvées (IA assumée / fuite RAG)."""
    hits: list[str] = []
    if _AI_TERMS_RE.search(text or ""):
        hits.append("mention IA/robot")
    if _META_LEAK_RE.search(text or ""):
        hits.append("fuite RAG / aveu d'ignorance")
    return hits


def score_turn(turn: Turn, response) -> list[dict]:
    """Évalue une réponse contre les attentes d'un tour. Liste de checks."""
    text = response.response_text or ""
    low = text.lower()
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # Persona : toujours vérifié (jamais d'IA assumée, jamais de fuite).
    violations = _forbidden_identity_or_leak(text)
    add("persona_humaine", not violations, ", ".join(violations))

    if turn.expect_lang is not None:
        got = response.detected_language or detect_language(turn.user)
        add("langue", got == turn.expect_lang, f"attendu {turn.expect_lang}, obtenu {got}")

    if turn.expect_clarification is not None:
        add(
            "clarification",
            bool(response.needs_clarification) == turn.expect_clarification,
            f"attendu {turn.expect_clarification}, obtenu {response.needs_clarification}",
        )

    if turn.expect_gap is not None:
        add(
            "lacune_detectee",
            bool(response.knowledge_gap) == turn.expect_gap,
            f"attendu {turn.expect_gap}, obtenu {response.knowledge_gap}",
        )

    if turn.must_contain_any:
        ok = any(frag.lower() in low for frag in turn.must_contain_any)
        add("info_cle_presente", ok, f"attendu un de {turn.must_contain_any}")

    if turn.forbid:
        bad = [f for f in turn.forbid if f.lower() in low]
        add("interdits_absents", not bad, f"présents : {bad}" if bad else "")

    return checks


async def run_scenario(scenario: Scenario, *, embedder, provider) -> dict:
    """Exécute un scénario complet (multi-tours) et score chaque réponse."""
    retriever = EvalRetriever(embedder)
    await retriever.seed(scenario.knowledge)
    engine = build_eval_engine(provider, retriever)
    conv_id, biz_id = uuid4(), uuid4()

    turns_out: list[dict] = []
    for turn in scenario.turns:
        resp = await engine.process(
            EngineRequest(
                conversation_id=conv_id,
                business_id=biz_id,
                message_text=turn.user,
                persona=scenario.persona,
                business_name=scenario.business_name,
            )
        )
        checks = score_turn(turn, resp)
        turns_out.append(
            {
                "user": turn.user,
                "response": resp.response_text,
                "language": resp.detected_language,
                "needs_clarification": resp.needs_clarification,
                "knowledge_gap": resp.knowledge_gap,
                "checks": checks,
                "passed": all(c["passed"] for c in checks),
            }
        )
    n_checks = sum(len(t["checks"]) for t in turns_out)
    n_pass = sum(c["passed"] for t in turns_out for c in t["checks"])
    return {
        "id": scenario.id,
        "domain": scenario.domain,
        "business_name": scenario.business_name,
        "turns": turns_out,
        "checks_total": n_checks,
        "checks_passed": n_pass,
    }


async def run_all(scenarios) -> dict:
    """Exécute tous les scénarios et agrège les métriques d'efficacité."""
    from jenny.llm.providers import get_default_llm_provider
    from jenny.rag.embeddings import get_default_embedder

    provider = get_default_llm_provider()
    if provider is None:
        raise RuntimeError("Aucun provider LLM configuré (Ollama requis pour l'éval).")
    embedder = get_default_embedder()

    results: list[dict] = []
    for sc in scenarios:
        logger.info("eval.scenario.start", id=sc.id)
        results.append(await run_scenario(sc, embedder=embedder, provider=provider))

    # Agrégation par critère.
    by_criterion: dict[str, dict[str, int]] = {}
    for r in results:
        for t in r["turns"]:
            for c in t["checks"]:
                slot = by_criterion.setdefault(c["name"], {"pass": 0, "total": 0})
                slot["total"] += 1
                slot["pass"] += int(c["passed"])

    total = sum(r["checks_total"] for r in results)
    passed = sum(r["checks_passed"] for r in results)
    return {
        "scenarios": results,
        "summary": {
            "scenarios": len(results),
            "turns": sum(len(r["turns"]) for r in results),
            "checks_total": total,
            "checks_passed": passed,
            "score_pct": round(100 * passed / total, 1) if total else 0.0,
            "by_criterion": {
                k: {
                    **v,
                    "pct": round(100 * v["pass"] / v["total"], 1) if v["total"] else 0.0,
                }
                for k, v in sorted(by_criterion.items())
            },
        },
    }
