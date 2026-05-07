#!/usr/bin/env python3
"""
Phase 3 Tests -- IntentAgent.

Uses a MockLLMProvider (extends BaseLLMProvider) so tests run
without any API credentials.

Run:
    cd SignalForge
    python -m tests.test_intent_agent
"""

import json
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("test_phase3")


# -- Mock LLM Provider ----------------------------------------------------

from providers.llm_provider import BaseLLMProvider


class MockLLMProvider(BaseLLMProvider):
    """
    Deterministic mock that returns pre-defined JSON responses
    based on keyword matching in the prompt.

    This lets us test IntentAgent without hitting any API.
    """

    def generate(self, prompt: str, **kwargs) -> str:
        text = prompt.lower()

        # Detect keywords to produce realistic classifications
        if "budget" in text and ("looking for" in text or "recommend" in text):
            return json.dumps({
                "intent": "buying_intent",
                "confidence": 0.92,
                "reasoning": "User is actively seeking tools with a stated budget.",
                "business_relevance": "High - direct sales opportunity.",
                "recommended_action": "respond",
            })

        if "pain point" in text or "frustrat" in text or "rant" in text:
            return json.dumps({
                "intent": "churn_risk",
                "confidence": 0.85,
                "reasoning": "User expressing frustration with current tools.",
                "business_relevance": "High - user may switch solutions.",
                "recommended_action": "respond",
            })

        if ("bottleneck" in text or "doesn't scale" in text
                or "can't keep up" in text):
            return json.dumps({
                "intent": "problem_intent",
                "confidence": 0.88,
                "reasoning": "User facing workflow scalability issues.",
                "business_relevance": "Medium - opportunity to demonstrate value.",
                "recommended_action": "respond",
            })

        if "hire" in text or "agency" in text or "freelancer" in text:
            return json.dumps({
                "intent": "hiring_intent",
                "confidence": 0.78,
                "reasoning": "User looking for external help.",
                "business_relevance": "Medium - partnership opportunity.",
                "recommended_action": "monitor",
            })

        if "hootsuite" in text or "buffer" in text or "chatgpt" in text:
            return json.dumps({
                "intent": "competitor_mention",
                "confidence": 0.80,
                "reasoning": "User mentions competitor tools by name.",
                "business_relevance": "High - competitive positioning.",
                "recommended_action": "respond",
            })

        if "wish there was" in text or "missing feature" in text:
            return json.dumps({
                "intent": "feature_request",
                "confidence": 0.75,
                "reasoning": "User wants functionality that doesn't exist.",
                "business_relevance": "Medium - product feedback.",
                "recommended_action": "monitor",
            })

        # Default
        return json.dumps({
            "intent": "problem_intent",
            "confidence": 0.70,
            "reasoning": "General problem discussion detected.",
            "business_relevance": "Medium - worth monitoring.",
            "recommended_action": "monitor",
        })

    def __repr__(self) -> str:
        return "<MockLLMProvider>"


class BrokenLLMProvider(BaseLLMProvider):
    """Always returns garbage -- tests fallback handling."""

    def generate(self, prompt: str, **kwargs) -> str:
        return "THIS IS NOT JSON AT ALL!!! {{{broken"

    def __repr__(self) -> str:
        return "<BrokenLLMProvider>"


class MarkdownLLMProvider(BaseLLMProvider):
    """Returns valid JSON wrapped in markdown code fences."""

    def generate(self, prompt: str, **kwargs) -> str:
        return (
            "```json\n"
            '{"intent": "buying_intent", "confidence": 0.91, '
            '"reasoning": "test", "business_relevance": "high", '
            '"recommended_action": "respond"}\n'
            "```"
        )

    def __repr__(self) -> str:
        return "<MarkdownLLMProvider>"


class BadIntentLLMProvider(BaseLLMProvider):
    """Returns valid JSON but with an invalid intent string."""

    def generate(self, prompt: str, **kwargs) -> str:
        return json.dumps({
            "intent": "totally_fake_intent",
            "confidence": 1.5,
            "reasoning": "bad",
            "business_relevance": "bad",
            "recommended_action": "bad",
        })

    def __repr__(self) -> str:
        return "<BadIntentLLMProvider>"


# -- Test Opportunities ---------------------------------------------------

MOCK_OPPORTUNITIES = [
    {
        "id": "mock_001",
        "title": "Need help automating my social media workflow -- any tool recommendations?",
        "body": (
            "I'm running a small marketing agency and spending 4+ hours daily. "
            "Looking for tools or workflows. Budget is around $50/month."
        ),
        "opportunity_signals": ["help_request", "recommendation_request"],
        "subreddit": "socialmedia",
        "score": 47,
    },
    {
        "id": "mock_002",
        "title": "What's the best AI tool for content creation in 2025?",
        "body": (
            "I've tried ChatGPT and Jasper but they both feel generic. "
            "Looking for something that understands brand voice."
        ),
        "opportunity_signals": ["recommendation_request"],
        "subreddit": "artificial",
        "score": 89,
    },
    {
        "id": "mock_005",
        "title": "Our agency's social media pain points -- a rant",
        "body": (
            "We manage 12 client accounts. The biggest bottlenecks are: "
            "finding conversations, writing responses. We've tried Hootsuite "
            "and Buffer. This is becoming unsustainable."
        ),
        "opportunity_signals": ["pain_point", "bottleneck"],
        "subreddit": "digitalmarketing",
        "score": 134,
    },
    {
        "id": "mock_007",
        "title": "Looking for recommendations: Reddit engagement tools for SaaS",
        "body": (
            "B2B SaaS startup. Key requirements: keyword monitoring, "
            "sentiment analysis, compliance. Budget: $100-200/month."
        ),
        "opportunity_signals": ["help_request", "recommendation_request"],
        "subreddit": "SaaS",
        "score": 56,
    },
    {
        "id": "mock_009",
        "title": "How do you handle content moderation at scale?",
        "body": (
            "Content moderation doesn't scale. 500 new posts/day, "
            "3-person mod team can't keep up."
        ),
        "opportunity_signals": ["recommendation_request", "bottleneck"],
        "subreddit": "community",
        "score": 78,
    },
    {
        "id": "mock_011",
        "title": "Frustrated with social media scheduling tools",
        "body": (
            "I've tested 8 different tools this month and NONE handle Reddit. "
            "Am I asking for too much?"
        ),
        "opportunity_signals": ["help_request", "pain_point"],
        "subreddit": "socialmedia",
        "score": 201,
    },
]


# == Test Functions ========================================================

def test_single_classification():
    """IntentAgent classifies a single opportunity correctly."""
    from agents.intent_agent import IntentAgent, VALID_INTENTS

    print("\n" + "=" * 60)
    print("  TEST: Single Classification")
    print("=" * 60)

    llm = MockLLMProvider()
    agent = IntentAgent(llm)

    result = agent.classify(MOCK_OPPORTUNITIES[0])

    # Structure checks
    assert "intent" in result, "Missing intent key"
    assert "confidence" in result, "Missing confidence key"
    assert "reasoning" in result, "Missing reasoning key"
    assert "business_relevance" in result, "Missing business_relevance key"
    assert "recommended_action" in result, "Missing recommended_action key"
    print("  + Output schema verified (5 keys)")

    # Value checks
    assert result["intent"] in VALID_INTENTS, f"Bad intent: {result['intent']}"
    assert 0.0 <= result["confidence"] <= 1.0, f"Bad confidence: {result['confidence']}"
    print(f"  + Intent: {result['intent']} ({result['confidence']:.2f})")
    print(f"  + Reasoning: {result['reasoning']}")
    print(f"  + Action: {result['recommended_action']}")

    print("  -- Single Classification PASSED --")


def test_batch_classification():
    """Batch classification processes all items and logs distribution."""
    from agents.intent_agent import IntentAgent, VALID_INTENTS

    print("\n" + "=" * 60)
    print("  TEST: Batch Classification")
    print("=" * 60)

    llm = MockLLMProvider()
    agent = IntentAgent(llm)

    results = agent.classify_batch(MOCK_OPPORTUNITIES)

    assert len(results) == len(MOCK_OPPORTUNITIES), (
        f"Expected {len(MOCK_OPPORTUNITIES)} results, got {len(results)}"
    )
    print(f"  + {len(results)} items classified")

    # All results valid
    for i, res in enumerate(results):
        assert res["intent"] in VALID_INTENTS, (
            f"Item {i}: invalid intent {res['intent']}"
        )
        assert 0.0 <= res["confidence"] <= 1.0

    print("  + All intents valid, all confidences in [0, 1]")

    # Print summary table
    print("\n  Intent Summary:")
    print("  " + "-" * 50)
    for i, (opp, res) in enumerate(zip(MOCK_OPPORTUNITIES, results)):
        print(
            f"  {opp['id']:>10} | {res['intent']:<20} | "
            f"{res['confidence']:.2f} | {res['recommended_action']}"
        )
    print("  " + "-" * 50)

    # Stats
    stats = agent.stats
    assert sum(stats.values()) == len(MOCK_OPPORTUNITIES)
    print(f"  + Stats tracked: {dict(stats)}")

    print("  -- Batch Classification PASSED --")


def test_invalid_json_fallback():
    """Broken LLM output falls back to intent=ignore."""
    from agents.intent_agent import IntentAgent

    print("\n" + "=" * 60)
    print("  TEST: Invalid JSON Fallback")
    print("=" * 60)

    llm = BrokenLLMProvider()
    agent = IntentAgent(llm)

    result = agent.classify(MOCK_OPPORTUNITIES[0])

    assert result["intent"] == "ignore", f"Expected ignore, got {result['intent']}"
    assert result["confidence"] == 0.0
    print(f"  + Broken JSON -> intent={result['intent']}, confidence={result['confidence']}")
    print("  -- Invalid JSON Fallback PASSED --")


def test_markdown_fence_stripping():
    """LLM output wrapped in ```json fences is parsed correctly."""
    from agents.intent_agent import IntentAgent

    print("\n" + "=" * 60)
    print("  TEST: Markdown Fence Stripping")
    print("=" * 60)

    llm = MarkdownLLMProvider()
    agent = IntentAgent(llm)

    result = agent.classify(MOCK_OPPORTUNITIES[0])

    assert result["intent"] == "buying_intent", f"Got {result['intent']}"
    assert result["confidence"] == 0.91
    print(f"  + Fenced JSON parsed -> {result['intent']} ({result['confidence']})")
    print("  -- Markdown Fence Stripping PASSED --")


def test_invalid_intent_fallback():
    """Invalid intent string from LLM falls back to ignore."""
    from agents.intent_agent import IntentAgent

    print("\n" + "=" * 60)
    print("  TEST: Invalid Intent Fallback")
    print("=" * 60)

    llm = BadIntentLLMProvider()
    agent = IntentAgent(llm)

    result = agent.classify(MOCK_OPPORTUNITIES[0])

    assert result["intent"] == "ignore", f"Expected ignore, got {result['intent']}"
    # Confidence should be clamped to 1.0 max
    assert result["confidence"] == 1.0, f"Expected 1.0, got {result['confidence']}"
    print(f"  + Bad intent -> {result['intent']}, confidence clamped to {result['confidence']}")
    print("  -- Invalid Intent Fallback PASSED --")


def test_type_validation():
    """IntentAgent rejects non-BaseLLMProvider inputs."""
    from agents.intent_agent import IntentAgent

    print("\n" + "=" * 60)
    print("  TEST: Type Validation")
    print("=" * 60)

    try:
        IntentAgent("not a provider")
        assert False, "Should have raised TypeError"
    except TypeError as e:
        print(f"  + Correctly rejected: {e}")

    try:
        IntentAgent(None)
        assert False, "Should have raised TypeError"
    except TypeError as e:
        print(f"  + Correctly rejected None: {e}")

    print("  -- Type Validation PASSED --")


def test_stats_reset():
    """Stats can be reset between runs."""
    from agents.intent_agent import IntentAgent

    print("\n" + "=" * 60)
    print("  TEST: Stats Reset")
    print("=" * 60)

    llm = MockLLMProvider()
    agent = IntentAgent(llm)

    agent.classify(MOCK_OPPORTUNITIES[0])
    assert sum(agent.stats.values()) == 1
    print(f"  + After 1 classify: {agent.stats}")

    agent.reset_stats()
    assert sum(agent.stats.values()) == 0
    print("  + After reset: stats cleared")

    print("  -- Stats Reset PASSED --")


# == Live Gemini Test (optional) ===========================================

def test_live_gemini():
    """Optional: test with real Gemini if credentials available."""
    from config.settings import Settings
    from providers.llm_provider import get_llm_provider
    from agents.intent_agent import IntentAgent, VALID_INTENTS

    print("\n" + "=" * 60)
    print("  TEST: Live Gemini (optional)")
    print("=" * 60)

    Settings.reset()
    settings = Settings()

    if not settings.gemini_api_key:
        print("  ! GEMINI_API_KEY not set -- skipping live test")
        return

    try:
        llm = get_llm_provider("gemini", api_key=settings.gemini_api_key)
        agent = IntentAgent(llm)

        result = agent.classify(MOCK_OPPORTUNITIES[0])

        assert result["intent"] in VALID_INTENTS
        assert 0.0 <= result["confidence"] <= 1.0
        print(f"  + Live result: {result['intent']} ({result['confidence']:.2f})")
        print(f"  + Reasoning: {result['reasoning']}")
        print(f"  + Relevance: {result['business_relevance']}")
        print(f"  + Action: {result['recommended_action']}")
        print("  -- Live Gemini PASSED --")

    except Exception as exc:
        print(f"  ! Live Gemini test failed: {exc}")

    Settings.reset()


# == Runner ================================================================

if __name__ == "__main__":
    print("\n+" + "=" * 58 + "+")
    print("|   SignalForge -- Phase 3 IntentAgent Tests               |")
    print("+" + "=" * 58 + "+")

    try:
        test_single_classification()
        test_batch_classification()
        test_invalid_json_fallback()
        test_markdown_fence_stripping()
        test_invalid_intent_fallback()
        test_type_validation()
        test_stats_reset()
        test_live_gemini()

        print("\n" + "=" * 60)
        print("  ALL PHASE 3 TESTS PASSED")
        print("=" * 60 + "\n")

    except AssertionError as e:
        print(f"\n  TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
