#!/usr/bin/env python3
"""
Phase 8 Tests -- SignalForge LangGraph Orchestration.

Builds the full mock-mode pipeline and validates that all stages execute,
structured state is preserved, and final compliance output exists.

Run:
    cd SignalForge
    python -m tests.test_signalforge_graph
"""

import json
import logging
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from pprint import pprint
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("test_phase8")

from agents.compliance_agent import ComplianceAgent
from agents.drafting_agent import DraftingAgent
from agents.intent_agent import IntentAgent
from agents.opportunity_scanner.agent import OpportunityScannerAgent
from agents.product_knowledge_agent import ProductKnowledgeAgent
from agents.scoring_agent import OpportunityScoringAgent
from providers.llm_provider import BaseLLMProvider
from providers.vector_store import LocalChromaVectorStore
from workflows.signalforge_graph import SignalForgeGraph


PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge" / "product_docs"
TMP_ROOT = PROJECT_ROOT / "tests" / ".tmp_phase8"


class MockIntentLLMProvider(BaseLLMProvider):
    """Deterministic intent classifier for full-pipeline testing."""

    def generate(self, prompt: str, **kwargs) -> str:
        text = prompt.lower()

        if "frustrated" in text or "rant" in text:
            return json.dumps({
                "intent": "churn_risk",
                "confidence": 0.87,
                "reasoning": "The user sounds frustrated with current tooling.",
                "business_relevance": "High - possible switch opportunity.",
                "recommended_action": "respond",
            })

        if "looking for" in text or "recommend" in text or "tool" in text:
            return json.dumps({
                "intent": "buying_intent",
                "confidence": 0.91,
                "reasoning": "The user appears to be evaluating workflow tools.",
                "business_relevance": "High - direct solution discovery.",
                "recommended_action": "respond",
            })

        return json.dumps({
            "intent": "problem_intent",
            "confidence": 0.79,
            "reasoning": "The user is describing a workflow pain point.",
            "business_relevance": "Medium - useful engagement opportunity.",
            "recommended_action": "respond",
        })

    def __repr__(self) -> str:
        return "<MockIntentLLMProvider>"


class MockDraftingLLMProvider(BaseLLMProvider):
    """Deterministic drafting provider for full-pipeline testing."""

    def generate(self, prompt: str, **kwargs) -> str:
        text = prompt.lower()

        if "community" in text:
            return json.dumps({
                "draft": (
                    "A practical way to handle this is to set a few clear rules for "
                    "which conversations need a response first, then keep a lightweight "
                    "playbook for recurring questions so the team is not starting from "
                    "scratch every time."
                ),
                "tone": "casual",
                "cta": "If helpful, I can share a simple response workflow outline.",
                "reasoning": "This keeps the reply helpful and specific without sounding salesy.",
            })

        return json.dumps({
            "draft": (
                "It may help to split the workflow into discovery, prioritization, "
                "and response so the team can focus on the threads that show real "
                "intent instead of trying to answer everything the same way."
            ),
            "tone": "expert",
            "cta": "If useful, I can sketch a lightweight triage approach for that.",
            "reasoning": "The reply stays practical, product-aware, and low-pressure.",
        })

    def __repr__(self) -> str:
        return "<MockDraftingLLMProvider>"


@contextmanager
def _workspace_tmpdir():
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = TMP_ROOT / f"run_{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_full_signalforge_pipeline():
    """The LangGraph workflow executes every stage and returns final results."""
    print("\n" + "=" * 60)
    print("  TEST: Full SignalForge LangGraph Pipeline")
    print("=" * 60)

    with _workspace_tmpdir() as temp_dir:
        cache_dir = temp_dir / "cache"
        vector_dir = temp_dir / "vector_db"

        scanner_agent = OpportunityScannerAgent(
            reddit_provider=None,
            force_mock=True,
            cache_dir=str(cache_dir),
        )
        intent_agent = IntentAgent(MockIntentLLMProvider())
        scoring_agent = OpportunityScoringAgent()
        vector_store = LocalChromaVectorStore(
            documents_path=str(KNOWLEDGE_DIR),
            persist_directory=str(vector_dir),
            chunk_size=320,
            chunk_overlap=60,
            gemini_api_key="",
        )
        knowledge_agent = ProductKnowledgeAgent(vector_store=vector_store, top_k=3)
        drafting_agent = DraftingAgent(MockDraftingLLMProvider())
        compliance_agent = ComplianceAgent()

        workflow = SignalForgeGraph(
            scanner_agent=scanner_agent,
            intent_agent=intent_agent,
            scoring_agent=scoring_agent,
            product_knowledge_agent=knowledge_agent,
            drafting_agent=drafting_agent,
            compliance_agent=compliance_agent,
        )

        state = workflow.invoke("AI automation workflow pain points")

        assert state["opportunities"], "Scanner should return opportunities"
        assert state["intent_results"], "Intent stage should produce results"
        assert state["scored_results"], "Scoring stage should produce results"
        assert state["knowledge_results"], "Knowledge stage should produce results"
        assert state["draft_results"], "Drafting stage should produce results"
        assert state["compliance_results"], "Compliance stage should produce results"
        assert state["final_results"], "Final structured output should exist"

        expected_len = len(state["opportunities"])
        assert len(state["intent_results"]) == expected_len
        assert len(state["scored_results"]) == expected_len
        assert len(state["knowledge_results"]) == expected_len
        assert len(state["draft_results"]) == expected_len
        assert len(state["compliance_results"]) == expected_len
        assert len(state["final_results"]) == expected_len

        for item in state["final_results"]:
            assert "opportunity" in item
            assert "intent" in item
            assert "score" in item
            assert "knowledge" in item
            assert "draft" in item
            assert "compliance" in item
            assert item["compliance"], "Compliance result must exist"

        print("  Pipeline stages:")
        print(f"  - scanner: {len(state['opportunities'])}")
        print(f"  - intent: {len(state['intent_results'])}")
        print(f"  - scoring: {len(state['scored_results'])}")
        print(f"  - product_knowledge: {len(state['knowledge_results'])}")
        print(f"  - drafting: {len(state['draft_results'])}")
        print(f"  - compliance: {len(state['compliance_results'])}")

        print("\n  Final structured output:")
        pprint(state["final_results"])

        print(f"\n  Success count: {state.get('success_count', 0)}")
        print(f"  Failure count: {state.get('failure_count', 0)}")
        print("  -- Full SignalForge LangGraph Pipeline PASSED --")


def test_compliance_counts_ignore_product_knowledge_errors():
    """Compliance counters should only reflect compliance approvals/rejections."""

    class FakeComplianceAgent:
        def validate(self, draft):
            if draft.get("draft") == "approved":
                return {
                    "approved": True,
                    "risk_level": "safe",
                    "violations": [],
                    "safe_draft": draft["draft"],
                    "recommendation": "approve",
                }
            return {
                "approved": False,
                "risk_level": "reject",
                "violations": ["hard_sell_language"],
                "safe_draft": "safer draft",
                "recommendation": "reject",
            }

    workflow = SignalForgeGraph.__new__(SignalForgeGraph)
    workflow._compliance_agent = FakeComplianceAgent()

    state = {
        "opportunities": [{"id": "opp_1"}, {"id": "opp_2"}],
        "intent_results": [{}, {}],
        "scored_results": [{}, {}],
        "knowledge_results": [{}, {}],
        "draft_results": [{"draft": "approved"}, {"draft": "rejected"}],
        "compliance_results": [],
        "final_results": [],
        "errors": [
            {
                "stage": "product_knowledge",
                "opportunity_id": "opp_1",
                "error": "missing context",
            }
        ],
    }

    result = workflow.compliance_node(state)

    assert result["success_count"] == 1
    assert result["failure_count"] == 1
    assert result["errors"] == state["errors"]


if __name__ == "__main__":
    print("\n+" + "=" * 58 + "+")
    print("|   SignalForge -- Phase 8 LangGraph Tests                |")
    print("+" + "=" * 58 + "+")

    try:
        test_full_signalforge_pipeline()

        print("\n" + "=" * 60)
        print("  ALL PHASE 8 TESTS PASSED")
        print("=" * 60 + "\n")

    except AssertionError as exc:
        print(f"\n  TEST FAILED: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  UNEXPECTED ERROR: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
