#!/usr/bin/env python3
"""
Phase 4 Tests -- OpportunityScoringAgent.

Tests the scoring pipeline using mock opportunities that simulate
combined Phase 2 + Phase 3 output. No API credentials required.

Run:
    cd SignalForge
    python -m tests.test_scoring_agent
"""

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("test_phase4")


# -- Mock opportunities (Phase 2 + Phase 3 combined output) ---------------

MOCK_SCORED_OPPORTUNITIES = [
    {
        "id": "mock_001",
        "title": "Need help automating my social media workflow -- any tool recommendations?",
        "body": (
            "I'm running a small marketing agency and spending 4+ hours daily. "
            "Looking for tools or workflows. Budget is around $50/month. "
            "This is urgent, we need a solution ASAP."
        ),
        "score": 47,
        "subreddit": "socialmedia",
        "opportunity_signals": ["help_request", "recommendation_request", "pain_point", "bottleneck"],
        "intent": "buying_intent",
        "confidence": 0.92,
        "business_relevance": "High - direct sales opportunity.",
        "recommended_action": "respond",
    },
    {
        "id": "mock_002",
        "title": "What's the best AI tool for content creation in 2025?",
        "body": (
            "I've tried ChatGPT and Jasper but they both feel generic. "
            "Looking for something that understands brand voice."
        ),
        "score": 89,
        "subreddit": "artificial",
        "opportunity_signals": ["recommendation_request"],
        "intent": "competitor_mention",
        "confidence": 0.80,
        "business_relevance": "High - competitive positioning.",
        "recommended_action": "respond",
    },
    {
        "id": "mock_005",
        "title": "Our agency's social media pain points -- a rant",
        "body": (
            "We manage 12 client accounts. The biggest bottlenecks are: "
            "finding conversations, writing responses. We've tried Hootsuite "
            "and Buffer. This is becoming unsustainable. I'm so frustrated."
        ),
        "score": 134,
        "subreddit": "digitalmarketing",
        "opportunity_signals": ["pain_point", "bottleneck"],
        "intent": "churn_risk",
        "confidence": 0.85,
        "business_relevance": "High - user may switch solutions.",
        "recommended_action": "respond",
    },
    {
        "id": "mock_007",
        "title": "Looking for recommendations: Reddit engagement tools for SaaS",
        "body": (
            "B2B SaaS startup. Key requirements: keyword monitoring, "
            "sentiment analysis, compliance. Budget: $100-200/month."
        ),
        "score": 56,
        "subreddit": "SaaS",
        "opportunity_signals": ["help_request", "recommendation_request"],
        "intent": "buying_intent",
        "confidence": 0.92,
        "business_relevance": "High - direct sales opportunity.",
        "recommended_action": "respond",
    },
    {
        "id": "mock_009",
        "title": "How do you handle content moderation at scale?",
        "body": (
            "Content moderation doesn't scale. 500 new posts/day, "
            "3-person mod team can't keep up."
        ),
        "score": 78,
        "subreddit": "community",
        "opportunity_signals": ["recommendation_request", "bottleneck"],
        "intent": "problem_intent",
        "confidence": 0.88,
        "business_relevance": "Medium - opportunity to demonstrate value.",
        "recommended_action": "respond",
    },
    {
        "id": "mock_011",
        "title": "Frustrated with social media scheduling tools",
        "body": (
            "I've tested 8 different tools this month and NONE handle Reddit. "
            "Am I asking for too much? So frustrated with the current options."
        ),
        "score": 201,
        "subreddit": "socialmedia",
        "opportunity_signals": ["help_request", "pain_point"],
        "intent": "churn_risk",
        "confidence": 0.90,
        "business_relevance": "High - user may switch solutions.",
        "recommended_action": "respond",
    },
    {
        "id": "mock_low",
        "title": "Random question about CSS",
        "body": "How do I center a div? Thanks.",
        "score": 3,
        "subreddit": "webdev",
        "opportunity_signals": [],
        "intent": "ignore",
        "confidence": 0.95,
        "business_relevance": "None.",
        "recommended_action": "skip",
    },
    {
        "id": "mock_feature",
        "title": "I wish there was a tool that could auto-detect subreddit tone",
        "body": (
            "Every subreddit has its own vibe and culture. I wish my social "
            "media tool could auto-detect the tone and adjust my drafts. "
            "Missing feature in every tool I've tried."
        ),
        "score": 42,
        "subreddit": "socialmedia",
        "opportunity_signals": ["pain_point"],
        "intent": "feature_request",
        "confidence": 0.75,
        "business_relevance": "Medium - product feedback.",
        "recommended_action": "monitor",
    },
]


# == Test Functions ========================================================

def test_single_scoring():
    """Score a single opportunity and verify output schema."""
    from agents.scoring_agent import OpportunityScoringAgent

    print("\n" + "=" * 60)
    print("  TEST: Single Scoring")
    print("=" * 60)

    agent = OpportunityScoringAgent()

    # Use the high-value buying_intent opportunity
    result = agent.score(MOCK_SCORED_OPPORTUNITIES[0])

    # Schema checks
    assert "priority_score" in result, "Missing priority_score"
    assert "priority_label" in result, "Missing priority_label"
    assert "scoring_breakdown" in result, "Missing scoring_breakdown"
    assert "recommended_action" in result, "Missing recommended_action"
    print("  + Output schema verified (4 keys)")

    # Value checks
    assert 0.0 <= result["priority_score"] <= 100.0, (
        f"Score out of range: {result['priority_score']}"
    )
    assert result["priority_label"] in ("hot", "warm", "cold", "ignore"), (
        f"Bad label: {result['priority_label']}"
    )
    print(f"  + Score: {result['priority_score']}")
    print(f"  + Label: {result['priority_label']}")
    print(f"  + Action: {result['recommended_action']}")
    print(f"  + Breakdown: {result['scoring_breakdown']}")

    # Breakdown should have 4 components
    bd = result["scoring_breakdown"]
    assert "intent_score" in bd, "Missing intent_score in breakdown"
    assert "engagement_score" in bd, "Missing engagement_score in breakdown"
    assert "signal_boost" in bd, "Missing signal_boost in breakdown"
    assert "urgency_boost" in bd, "Missing urgency_boost in breakdown"
    print("  + Breakdown has all 4 components")

    # Buying intent with urgency and signals should score high
    assert result["priority_label"] in ("hot", "warm"), (
        f"Expected hot/warm for buying_intent+urgency, got {result['priority_label']}"
    )
    print("  + High-value opportunity scored appropriately")

    print("  -- Single Scoring PASSED --")


def test_batch_scoring():
    """Batch scoring processes all items correctly."""
    from agents.scoring_agent import OpportunityScoringAgent

    print("\n" + "=" * 60)
    print("  TEST: Batch Scoring")
    print("=" * 60)

    agent = OpportunityScoringAgent()
    results = agent.score_batch(MOCK_SCORED_OPPORTUNITIES)

    assert len(results) == len(MOCK_SCORED_OPPORTUNITIES), (
        f"Expected {len(MOCK_SCORED_OPPORTUNITIES)} results, got {len(results)}"
    )
    print(f"  + {len(results)} items scored")

    # All valid
    for i, res in enumerate(results):
        assert 0.0 <= res["priority_score"] <= 100.0
        assert res["priority_label"] in ("hot", "warm", "cold", "ignore")

    print("  + All scores in [0, 100], all labels valid")

    # Print table
    print("\n  Scoring Summary:")
    print("  " + "-" * 70)
    print(f"  {'ID':>12} | {'Intent':<20} | {'Score':>6} | {'Label':<8} | Action")
    print("  " + "-" * 70)
    for opp, res in zip(MOCK_SCORED_OPPORTUNITIES, results):
        print(
            f"  {opp['id']:>12} | {opp['intent']:<20} | "
            f"{res['priority_score']:>6.1f} | {res['priority_label']:<8} | "
            f"{res['recommended_action']}"
        )
    print("  " + "-" * 70)

    # Stats
    stats = agent.stats
    print(f"  + Distribution: {stats}")

    print("  -- Batch Scoring PASSED --")


def test_sort_by_priority():
    """sort_by_priority returns items ranked highest-first."""
    from agents.scoring_agent import OpportunityScoringAgent

    print("\n" + "=" * 60)
    print("  TEST: Sort by Priority")
    print("=" * 60)

    agent = OpportunityScoringAgent()
    sorted_opps = agent.sort_by_priority(MOCK_SCORED_OPPORTUNITIES)

    assert len(sorted_opps) == len(MOCK_SCORED_OPPORTUNITIES)

    # Verify descending order
    scores = [item["_scoring"]["priority_score"] for item in sorted_opps]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], (
            f"Not sorted: {scores[i]} < {scores[i + 1]} at index {i}"
        )
    print("  + Descending order verified")

    # Print ranked list
    print("\n  Ranked Opportunities:")
    print("  " + "-" * 70)
    for rank, item in enumerate(sorted_opps, 1):
        sc = item["_scoring"]
        print(
            f"  #{rank} [{item['id']:>12}] "
            f"{sc['priority_score']:>6.1f} ({sc['priority_label']:<6}) "
            f"-- {item['title'][:40]}"
        )
    print("  " + "-" * 70)

    # The ignore-intent item should be last
    last = sorted_opps[-1]
    assert last["intent"] == "ignore", (
        f"Expected ignore at bottom, got {last['intent']}"
    )
    print("  + Ignore-intent item ranked last")

    print("  -- Sort by Priority PASSED --")


def test_threshold_labels():
    """Verify that threshold boundaries produce correct labels."""
    from agents.scoring_agent import OpportunityScoringAgent, ScoringConfig

    print("\n" + "=" * 60)
    print("  TEST: Threshold Labels")
    print("=" * 60)

    agent = OpportunityScoringAgent()

    # The ignore-intent opportunity should score near 0
    ignore_opp = MOCK_SCORED_OPPORTUNITIES[6]  # mock_low, intent=ignore
    result = agent.score(ignore_opp)
    assert result["priority_label"] == "ignore", (
        f"Expected ignore for intent=ignore, got {result['priority_label']} "
        f"(score={result['priority_score']})"
    )
    print(f"  + ignore intent -> {result['priority_label']} ({result['priority_score']})")

    # High-value opportunity with urgency
    hot_opp = MOCK_SCORED_OPPORTUNITIES[0]  # buying + urgency + signals
    result_hot = agent.score(hot_opp)
    assert result_hot["priority_score"] >= 60.0, (
        f"Expected >= 60 for buying+urgency, got {result_hot['priority_score']}"
    )
    print(f"  + buying+urgency -> {result_hot['priority_label']} ({result_hot['priority_score']})")

    # Custom thresholds
    strict_config = ScoringConfig(
        hot_threshold=95.0,
        warm_threshold=85.0,
        cold_threshold=70.0,
    )
    strict_agent = OpportunityScoringAgent(config=strict_config)
    strict_result = strict_agent.score(hot_opp)
    print(
        f"  + Same opp with strict thresholds -> "
        f"{strict_result['priority_label']} ({strict_result['priority_score']})"
    )

    print("  -- Threshold Labels PASSED --")


def test_scoring_components():
    """Verify each scoring dimension contributes correctly."""
    from agents.scoring_agent import OpportunityScoringAgent

    print("\n" + "=" * 60)
    print("  TEST: Scoring Components")
    print("=" * 60)

    agent = OpportunityScoringAgent()

    # Test with zero engagement
    opp_no_engagement = {
        "id": "test_no_eng",
        "title": "Test post",
        "body": "Test body content here.",
        "score": 0,
        "opportunity_signals": [],
        "intent": "buying_intent",
        "confidence": 1.0,
    }
    result = agent.score(opp_no_engagement)
    bd = result["scoring_breakdown"]
    assert bd["engagement_score"] == 0.0, "Zero reddit score -> zero engagement"
    assert bd["signal_boost"] == 0.0, "No signals -> zero boost"
    assert bd["urgency_boost"] == 0.0, "No urgency words -> zero boost"
    assert bd["intent_score"] > 0.0, "Buying intent should have weight"
    print(f"  + No engagement/signals/urgency: breakdown={bd}")

    # Test urgency detection
    opp_urgent = {
        "id": "test_urgent",
        "title": "URGENT: need a tool ASAP",
        "body": "I'm stuck and frustrated.",
        "score": 10,
        "opportunity_signals": ["help_request"],
        "intent": "problem_intent",
        "confidence": 0.85,
    }
    result_urgent = agent.score(opp_urgent)
    bd_urgent = result_urgent["scoring_breakdown"]
    assert bd_urgent["urgency_boost"] > 0.0, "Should detect urgency"
    print(f"  + Urgency detected: boost={bd_urgent['urgency_boost']}")

    # Test signal stacking
    opp_signals = {
        "id": "test_signals",
        "title": "Help needed",
        "body": "Looking for recommendations.",
        "score": 50,
        "opportunity_signals": ["help_request", "pain_point", "recommendation_request", "bottleneck"],
        "intent": "buying_intent",
        "confidence": 0.90,
    }
    result_signals = agent.score(opp_signals)
    bd_signals = result_signals["scoring_breakdown"]
    assert bd_signals["signal_boost"] > 10.0, "4 signals should boost > 10"
    print(f"  + 4 signals stacked: boost={bd_signals['signal_boost']}")

    print("  -- Scoring Components PASSED --")


def test_stats_and_reset():
    """Stats tracking and reset work correctly."""
    from agents.scoring_agent import OpportunityScoringAgent

    print("\n" + "=" * 60)
    print("  TEST: Stats and Reset")
    print("=" * 60)

    agent = OpportunityScoringAgent()

    agent.score(MOCK_SCORED_OPPORTUNITIES[0])
    agent.score(MOCK_SCORED_OPPORTUNITIES[6])
    assert sum(agent.stats.values()) == 2
    print(f"  + After 2 scores: {agent.stats}")

    agent.reset_stats()
    assert sum(agent.stats.values()) == 0
    print("  + After reset: stats cleared")

    print("  -- Stats and Reset PASSED --")


# == Runner ================================================================

if __name__ == "__main__":
    print("\n+" + "=" * 58 + "+")
    print("|   SignalForge -- Phase 4 ScoringAgent Tests              |")
    print("+" + "=" * 58 + "+")

    try:
        test_single_scoring()
        test_batch_scoring()
        test_sort_by_priority()
        test_threshold_labels()
        test_scoring_components()
        test_stats_and_reset()

        print("\n" + "=" * 60)
        print("  ALL PHASE 4 TESTS PASSED")
        print("=" * 60 + "\n")

    except AssertionError as e:
        print(f"\n  TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
