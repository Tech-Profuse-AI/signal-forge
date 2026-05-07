#!/usr/bin/env python3
"""
Phase 7 Tests -- ComplianceAgent.

Validates draft outputs using deterministic rule-based checks and safer
rewrite behavior for review/reject cases.

Run:
    cd SignalForge
    python -m tests.test_compliance_agent
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("test_phase7")


SAFE_DRAFT = {
    "draft": (
        "A good starting point is to separate discovery from response so your "
        "team is not treating every thread the same way. If you identify the "
        "questions that consistently signal real intent, it gets much easier to "
        "prioritize the replies that deserve thoughtful follow-up."
    ),
    "tone": "helpful",
    "cta": "If helpful, I can share a simple triage framework here.",
    "reasoning": "This stays practical and keeps the focus on the user's workflow.",
}

REVIEW_DRAFT = {
    "draft": (
        "A structured workflow can help here. SignalForge can help surface the "
        "right threads, and SignalForge can save time once you know which "
        "signals matter most."
    ),
    "tone": "expert",
    "cta": "Worth checking out now if you're comparing options.",
    "reasoning": "This ties the advice to a product-aware workflow.",
}

REJECT_DRAFT = {
    "draft": (
        "Buy SignalForge now and click here because it guarantees 10x better "
        "results overnight. DM me if you want the fastest setup."
    ),
    "tone": "aggressive",
    "cta": "Contact sales today.",
    "reasoning": "This is intentionally pushy for testing.",
}


def test_safe_draft():
    """Clean helpful drafts should pass as safe."""
    from agents.compliance_agent import ComplianceAgent

    print("\n" + "=" * 60)
    print("  TEST: Safe Draft")
    print("=" * 60)

    agent = ComplianceAgent()
    result = agent.validate(SAFE_DRAFT)

    assert result["approved"] is True
    assert result["risk_level"] == "safe"
    assert result["violations"] == []
    assert "triage framework" in result["safe_draft"].lower()

    print(f"  Risk Level: {result['risk_level']}")
    print(f"  Violations: {result['violations']}")
    print(f"  Safe Draft: {result['safe_draft']}")
    print("  -- Safe Draft PASSED --")


def test_review_draft():
    """Minor promotional issues should be softened and flagged for review."""
    from agents.compliance_agent import ComplianceAgent

    print("\n" + "=" * 60)
    print("  TEST: Review Draft")
    print("=" * 60)

    agent = ComplianceAgent()
    result = agent.validate(REVIEW_DRAFT)

    assert result["approved"] is False
    assert result["risk_level"] == "review"
    assert "excessive_product_mention" in result["violations"]
    assert result["safe_draft"].lower().count("signalforge") <= 1
    assert "worth checking out now" not in result["safe_draft"].lower()

    print(f"  Risk Level: {result['risk_level']}")
    print(f"  Violations: {result['violations']}")
    print(f"  Safe Draft: {result['safe_draft']}")
    print("  -- Review Draft PASSED --")


def test_reject_draft():
    """High-risk content should be rejected and rewritten safely."""
    from agents.compliance_agent import ComplianceAgent

    print("\n" + "=" * 60)
    print("  TEST: Reject Draft")
    print("=" * 60)

    agent = ComplianceAgent()
    result = agent.validate(REJECT_DRAFT)

    assert result["approved"] is False
    assert result["risk_level"] == "reject"
    assert "hard_sell_language" in result["violations"]
    assert "unsafe_claims" in result["violations"]
    assert "platform_unsafe_language" in result["violations"]

    lowered = result["safe_draft"].lower()
    assert "buy now" not in lowered
    assert "click here" not in lowered
    assert "dm me" not in lowered
    assert "guarantee" not in lowered
    assert "10x" not in lowered

    print(f"  Risk Level: {result['risk_level']}")
    print(f"  Violations: {result['violations']}")
    print(f"  Safe Draft: {result['safe_draft']}")
    print("  -- Reject Draft PASSED --")


def test_batch_validation():
    """Batch validation should classify safe, review, and reject drafts."""
    from agents.compliance_agent import ComplianceAgent

    print("\n" + "=" * 60)
    print("  TEST: Batch Validation")
    print("=" * 60)

    agent = ComplianceAgent()
    results = agent.validate_batch([SAFE_DRAFT, REVIEW_DRAFT, REJECT_DRAFT])

    assert len(results) == 3
    assert [item["risk_level"] for item in results] == ["safe", "review", "reject"]
    assert agent.stats["safe"] >= 1
    assert agent.stats["review"] >= 1
    assert agent.stats["reject"] >= 1

    for index, result in enumerate(results, 1):
        print(f"\n  Result #{index}")
        print(f"  Risk Level: {result['risk_level']}")
        print(f"  Violations: {result['violations']}")
        print(f"  Safe Draft: {result['safe_draft']}")

    print("\n  -- Batch Validation PASSED --")


if __name__ == "__main__":
    print("\n+" + "=" * 58 + "+")
    print("|   SignalForge -- Phase 7 ComplianceAgent Tests           |")
    print("+" + "=" * 58 + "+")

    try:
        test_safe_draft()
        test_review_draft()
        test_reject_draft()
        test_batch_validation()

        print("\n" + "=" * 60)
        print("  ALL PHASE 7 TESTS PASSED")
        print("=" * 60 + "\n")

    except AssertionError as exc:
        print(f"\n  TEST FAILED: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  UNEXPECTED ERROR: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
