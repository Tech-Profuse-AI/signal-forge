"""Canonical opportunity schema tests."""

from __future__ import annotations

from schemas.opportunity import serialize_opportunity


REQUIRED_KEYS = {"url", "draft", "score", "platform", "title", "status"}


def test_nested_pipeline_payload_serializes_to_flat_opportunity():
    item = {
        "opportunity": {
            "id": "abc123",
            "platform": "reddit",
            "title": "Need a better workflow",
            "url": "https://www.reddit.com/r/SaaS/comments/abc123/help",
            "body": "Manual replies are taking too long.",
            "subreddit": "SaaS",
        },
        "intent": {"intent": "buying_intent", "confidence": 0.9},
        "score": {"priority_score": 81.2, "priority_label": "hot"},
        "draft": {"draft": "Here is a practical workflow to try.", "tone": "helpful"},
        "compliance": {"approved": True, "risk_level": "safe", "violations": []},
        "review_state": "paused",
    }

    out = serialize_opportunity(item)

    assert REQUIRED_KEYS <= set(out)
    assert "opportunity" not in out
    assert isinstance(out["draft"], str)
    assert out["score"] == 81
    assert out["platform"] == "reddit"
    assert out["title"] == "Need a better workflow"
    assert out["status"] == "paused"
    assert out["compliance_approved"] is True


def test_scanner_payload_uses_same_shape_with_empty_draft_and_priority_score():
    item = {
        "id": "medium_abc",
        "platform": "medium",
        "title": "Automation lessons learned",
        "url": "https://medium.com/p/abc",
        "score": 37,
        "body": "A long article about manual workflow pain.",
        "author": "Ada",
        "opportunity_signals": ["workflow_pain"],
    }

    out = serialize_opportunity(item, status="discovered", pipeline_state="discovered")

    assert REQUIRED_KEYS <= set(out)
    assert out["draft"] == ""
    assert out["score"] == 0
    assert out["source_score"] == 37
    assert out["signals"] == ["workflow_pain"]
    assert out["opportunity_signals"] == ["workflow_pain"]
    assert out["status"] == "discovered"
