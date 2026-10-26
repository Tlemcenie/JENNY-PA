"""Agent FAQ : seuil d'injection et nombre de docs."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jenny.agents.faq_agent import FAQ_MAX_DOCS, FAQ_MIN_SCORE, FAQAgent, select_documents
from jenny.engine.state_manager import ConversationState
from jenny.rag.retriever import RetrievedDocument


def _d(score: float) -> dict:
    return {"content": f"doc {score}", "score": score, "metadata": {}}


def test_rien_sous_le_seuil() -> None:
    assert select_documents([_d(0.05), _d(FAQ_MIN_SCORE - 0.01)]) == []


def test_trois_docs_max_proches_du_meilleur() -> None:
    docs = [_d(0.80), _d(0.75), _d(0.70), _d(0.69), _d(0.40)]
    kept = select_documents(docs)
    assert len(kept) == FAQ_MAX_DOCS == 3
    assert [d["score"] for d in kept] == [0.80, 0.75, 0.70]


def test_ecart_au_meilleur() -> None:
    kept = select_documents([_d(0.80), _d(0.45)], max_gap=0.2)
    assert [d["score"] for d in kept] == [0.80]


class _Retriever:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.calls: list[dict] = []

    async def search(self, query, business_id, top_k=3, score_threshold=0.0):
        self.calls.append({"top_k": top_k, "score_threshold": score_threshold})
        # ignore le seuil exprès
        return [
            RetrievedDocument(id=str(i), content=f"c{i}", score=s, metadata={})
            for i, s in enumerate(self.scores)
        ]


@pytest.mark.asyncio
async def test_agent_filtre_meme_si_le_retriever_ignore_le_seuil() -> None:
    retriever = _Retriever([0.62, 0.30, 0.05])
    agent = FAQAgent(retriever=retriever)
    state = ConversationState(business_id=uuid4())
    state.add_user_message("Vous faites des colorations ?")
    out = await agent.handle(state)
    assert [d["score"] for d in out["documents"]] == [0.62]
    assert retriever.calls[0]["score_threshold"] == FAQ_MIN_SCORE
    assert retriever.calls[0]["top_k"] == FAQ_MAX_DOCS


@pytest.mark.asyncio
async def test_agent_sans_doc_utile() -> None:
    agent = FAQAgent(retriever=_Retriever([0.1, 0.05]))
    state = ConversationState(business_id=uuid4())
    state.add_user_message("Quel temps fera-t-il ?")
    out = await agent.handle(state)
    assert out["documents"] == []
