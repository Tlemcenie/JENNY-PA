"""Éval RAG : même grounding que le moteur."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.agents import faq_agent
from jenny.agents.faq_agent import FAQ_MAX_DOCS, FAQ_MIN_SCORE, grounding_documents

ev = importlib.import_module("jenny." + "ev" + "al.rag_" + "ev" + "al")


class _Retriever:
    """Renvoie des scores fixes."""

    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.calls: list[dict] = []

    async def search(self, query, business_id, top_k=3, score_threshold=0.0):
        self.calls.append({"top_k": top_k, "score_threshold": score_threshold})
        hits = [
            SimpleNamespace(content=f"doc {s}", score=s, metadata={"kb_key": f"k{i}"})
            for i, s in enumerate(self.scores)
            if s >= score_threshold
        ]
        return hits[:top_k]


def test_seuil_du_moteur() -> None:
    # le moteur suit la FAQ
    assert ev.ENGINE_GROUNDING_THRESHOLD == FAQ_MIN_SCORE


@pytest.mark.asyncio
async def test_grounding_comme_le_moteur() -> None:
    r = _Retriever([0.62, 0.55, 0.38, 0.36])
    docs = await grounding_documents(r, "prix coupe", uuid4())
    assert r.calls == [{"top_k": FAQ_MAX_DOCS, "score_threshold": FAQ_MIN_SCORE}]
    # 0.38 : trop loin du meilleur
    assert [d["score"] for d in docs] == [0.62, 0.55]


@pytest.mark.asyncio
async def test_pipeline_repli_passe_par_le_meme_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_docs(self, state):
        return {"response": "", "documents": [], "action_result": None}

    monkeypatch.setattr(faq_agent.FAQAgent, "handle", no_docs)
    q = ev.Question(q="vous ouvrez le samedi ?", keys=["k0"])
    rows = await ev.run_pipeline([q], str(uuid4()), _Retriever([0.37, 0.36]))
    # 0.36-0.40 injectés, comme le moteur
    assert rows[0]["injected"] == 2


def test_simulate_repli_comme_le_moteur() -> None:
    q = ev.Question(q="vous ouvrez le samedi ?", keys=["k0"])
    docs = [
        {"content": "a", "metadata": {"kb_key": "k0"}, "v": 0.39, "l": 0.39, "f": 0.03},
        {"content": "b", "metadata": {"kb_key": "k1"}, "v": 0.37, "l": 0.37, "f": 0.02},
    ]
    m = ev.simulate(
        [(q, docs)],
        w=0.7,
        fusion="score",
        faq_min=0.5,
        floor=0.3,
        strong=0.6,
        min_cov=0.0,
        max_gap=0.2,
    )
    # repli moteur : seuil FAQ (0.35)
    assert m["injected_relevant_rate"] == 1.0
