#!/usr/bin/env python3
"""
Phase 6 Tests -- DraftingAgent.

Uses mock LLM providers so the drafting flow can be verified without any
external API calls.

Run:
    cd SignalForge
    python -m tests.test_drafting_agent
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("test_phase6")

from providers.llm_provider import BaseLLMProvider


class MockDraftingLLMProvider(BaseLLMProvider):
    """Deterministic mock that returns grounded JSON replies."""

    def generate(self, prompt: str, **kwargs) -> str:
        text = prompt.lower()

        if "community engagement" in text:
            return json.dumps({
                "draft": (
                    "You could make this easier by setting a few clear response "
                    "rules up front, then tracking recurring questions so the "
                    "team is not rewriting the same reply every day. If the goal "
                    "is community engagement, I would prioritize high-intent "
                    "threads and keep the replies specific to what the poster is "
                    "actually asking."
                ),
                "tone": "casual",
                "cta": "If helpful, I can share a simple workflow outline for that.",
                "reasoning": (
                    "This keeps the reply practical and friendly while focusing on "
                    "workflow clarity instead of pitching a tool."
                ),
            })

        if "hiring_intent" in text:
            return json.dumps({
                "draft": (
                    "It may help to define the handoff points before you hire, "
                    "especially around monitoring, response approval, and brand "
                    "voice. That usually makes it easier to decide whether you need "
                    "a specialist, an agency, or just a tighter internal process."
                ),
                "tone": "professional",
                "cta": "",
                "reasoning": (
                    "The reply is structured and practical because the user is "
                    "looking for a workflow decision, not a sales pitch."
                ),
            })

        return json.dumps({
            "draft": (
                "A good starting point is to break the problem into discovery, "
                "prioritization, and response steps so you are not treating every "
                "thread the same way. If you already know which conversations lead "
                "to real customer intent, you can focus on those first and keep the "
                "process much more manageable."
            ),
            "tone": "expert",
            "cta": "If useful, I can sketch a lightweight workflow for triaging those posts.",
            "reasoning": (
                "The answer is product-aware and actionable, but it still leads with "
                "the user's workflow problem rather than promotion."
            ),
        })

    def __repr__(self) -> str:
        return "<MockDraftingLLMProvider>"


class PromotionalDraftingLLMProvider(BaseLLMProvider):
    """Returns a hard-sell reply so validation can reject it."""

    def generate(self, prompt: str, **kwargs) -> str:
        return json.dumps({
            "draft": "Buy SignalForge now and book a demo today for the best results!",
            "tone": "expert",
            "cta": "Sign up now",
            "reasoning": "This is direct and sales focused.",
        })

    def __repr__(self) -> str:
        return "<PromotionalDraftingLLMProvider>"


MOCK_INPUTS = [
    {
        "opportunity": {
            "id": "draft_001",
            "title": "Need help automating Reddit lead discovery",
            "body": (
                "Our team is manually combing through Reddit posts to find people "
                "asking for social media tools. We need a workflow that helps us "
                "prioritize real buying intent without sounding robotic."
            ),
            "subreddit": "marketing",
            "opportunity_signals": ["help_request", "recommendation_request", "pain_point"],
        },
        "intent_data": {
            "intent": "buying_intent",
            "confidence": 0.93,
            "business_relevance": "High - direct sales opportunity if handled helpfully.",
            "recommended_action": "respond",
        },
        "score_data": {
            "priority_score": 87.2,
            "priority_label": "hot",
            "recommended_action": "respond_immediately",
        },
        "knowledge_context": {
            "relevant_context": [
                {
                    "content": (
                        "SignalForge helps marketing teams discover high-intent Reddit "
                        "conversations and prioritize which ones deserve a response."
                    ),
                    "source": "knowledge/product_docs/use_cases.md",
                },
                {
                    "content": (
                        "The platform focuses on authentic engagement rather than hard "
                        "selling or mass posting."
                    ),
                    "source": "knowledge/product_docs/product_overview.md",
                },
            ],
            "summary": (
                "SignalForge helps teams discover, score, and respond to relevant "
                "Reddit conversations while staying authentic."
            ),
            "sources": [
                "knowledge/product_docs/use_cases.md",
                "knowledge/product_docs/product_overview.md",
            ],
        },
    },
    {
        "opportunity": {
            "id": "draft_002",
            "title": "Need AI-based community engagement workflow",
            "body": (
                "We manage a busy subreddit community and need a better way to track "
                "questions, prioritize replies, and keep responses consistent."
            ),
            "subreddit": "community",
            "opportunity_signals": ["pain_point", "bottleneck"],
        },
        "intent_data": {
            "intent": "problem_intent",
            "confidence": 0.88,
            "business_relevance": "Medium - workflow pain point with engagement upside.",
            "recommended_action": "respond",
        },
        "score_data": {
            "priority_score": 71.5,
            "priority_label": "warm",
            "recommended_action": "respond_soon",
        },
        "knowledge_context": {
            "relevant_context": [
                {
                    "content": (
                        "SignalForge helps community managers filter out noise, surface "
                        "meaningful conversations, and maintain engagement quality."
                    ),
                    "source": "knowledge/product_docs/use_cases.md",
                }
            ],
            "summary": (
                "Community managers use SignalForge to scale authentic engagement "
                "across multiple threads."
            ),
            "sources": ["knowledge/product_docs/use_cases.md"],
        },
    },
]


def test_single_draft():
    """DraftingAgent generates a usable single reply."""
    from agents.drafting_agent import DraftingAgent, VALID_TONES

    print("\n" + "=" * 60)
    print("  TEST: Single Draft")
    print("=" * 60)

    agent = DraftingAgent(MockDraftingLLMProvider())
    result = agent.generate_draft(MOCK_INPUTS[0])

    assert set(result) == {"draft", "tone", "cta", "reasoning"}
    assert result["tone"] in VALID_TONES
    assert len(result["draft"].split()) >= 12
    assert "buy now" not in result["draft"].lower()

    print(f"  Draft: {result['draft']}")
    print(f"  Tone: {result['tone']}")
    print(f"  CTA: {result['cta']}")
    print("  -- Single Draft PASSED --")


def test_batch_drafts():
    """Batch generation returns one validated draft per input."""
    from agents.drafting_agent import DraftingAgent, VALID_TONES

    print("\n" + "=" * 60)
    print("  TEST: Batch Drafts")
    print("=" * 60)

    agent = DraftingAgent(MockDraftingLLMProvider())
    results = agent.generate_batch(MOCK_INPUTS)

    assert len(results) == len(MOCK_INPUTS)
    for result in results:
        assert result["tone"] in VALID_TONES
        assert result["draft"]
        assert result["reasoning"]

    for index, result in enumerate(results, 1):
        print(f"\n  Draft #{index}: {result['draft']}")
        print(f"  Tone: {result['tone']}")
        print(f"  CTA: {result['cta']}")

    print("\n  -- Batch Drafts PASSED --")


def test_invalid_input_fallback():
    """Invalid input and promotional output both fall back safely."""
    from agents.drafting_agent import DraftingAgent

    print("\n" + "=" * 60)
    print("  TEST: Invalid Input Fallback")
    print("=" * 60)

    invalid_agent = DraftingAgent(MockDraftingLLMProvider())
    invalid_result = invalid_agent.generate_draft({
        "opportunity": {},
        "intent_data": {},
    })
    assert invalid_result["tone"] == "helpful"
    assert invalid_result["cta"] == ""
    assert "fallback" in invalid_result["reasoning"].lower()

    promo_agent = DraftingAgent(PromotionalDraftingLLMProvider())
    promo_result = promo_agent.generate_draft(MOCK_INPUTS[0])
    assert promo_result["tone"] == "helpful"
    assert promo_result["cta"] == ""
    assert "promotional" in promo_result["reasoning"].lower()

    print(f"  Draft: {promo_result['draft']}")
    print(f"  Tone: {promo_result['tone']}")
    print(f"  CTA: {promo_result['cta']}")
    print("  -- Invalid Input Fallback PASSED --")


if __name__ == "__main__":
    print("\n+" + "=" * 58 + "+")
    print("|   SignalForge -- Phase 6 DraftingAgent Tests             |")
    print("+" + "=" * 58 + "+")

    try:
        test_single_draft()
        test_batch_drafts()
        test_invalid_input_fallback()

        print("\n" + "=" * 60)
        print("  ALL PHASE 6 TESTS PASSED")
        print("=" * 60 + "\n")

    except AssertionError as exc:
        print(f"\n  TEST FAILED: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  UNEXPECTED ERROR: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
