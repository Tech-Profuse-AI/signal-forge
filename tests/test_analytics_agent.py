"""
Tests for Phase 18 — AnalyticsAgent.

Run from repo root:
    cd SignalForge && pytest tests/test_analytics_agent.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from agents.analytics_agent import AnalyticsAgent


def _sample_opportunity(platform: str = "reddit", opp_id: str = "opp-1") -> Dict[str, Any]:
    return {
        "id": opp_id,
        "platform": platform,
        "title": "Test title",
        "url": f"https://example.com/{opp_id}",
    }


def _sample_intent(label: str = "buying_intent") -> Dict[str, Any]:
    return {
        "intent": label,
        "confidence": 0.9,
        "reasoning": "test",
        "business_relevance": "high",
        "recommended_action": "respond",
    }


def _minimal_review_item(
    review_id: str,
    platform: str,
    intent_label: str,
) -> Dict[str, Any]:
    return {
        "review_id": review_id,
        "opportunity": _sample_opportunity(platform=platform, opp_id=review_id),
        "draft": {"draft": "body", "cta": "cta"},
        "compliance": {"approved": True, "risk_level": "safe"},
        "intent": _sample_intent(intent_label),
        "score": {"priority_score": 1.0},
    }


def _publisher_result(
    *,
    success: bool,
    platform: str,
    status: str = "mock_published",
    published_url: str | None = "https://mock.example/p/1",
) -> Dict[str, Any]:
    return {
        "success": success,
        "platform": platform,
        "published_url": published_url,
        "status": status,
    }


def test_track_review_counts_by_status():
    agent = AnalyticsAgent()

    agent.track_review(_minimal_review_item("r1", "reddit", "buying_intent"), "approved")
    agent.track_review(_minimal_review_item("r2", "quora", "problem_intent"), "rejected")
    agent.track_review(_minimal_review_item("r3", "medium", "buying_intent"), "edited")

    assert len(agent.review_events) == 3
    report = agent.generate_report()
    assert report["review_outcomes"] == {"approved": 1, "rejected": 1, "edited": 1}
    assert report["rates"]["approval_rate"] == pytest.approx(1 / 3)
    assert report["rates"]["rejection_rate"] == pytest.approx(1 / 3)
    assert report["rates"]["edit_rate"] == pytest.approx(1 / 3)


def test_track_review_invalid_status():
    agent = AnalyticsAgent()
    with pytest.raises(ValueError, match="status must be one of"):
        agent.track_review(_minimal_review_item("r1", "reddit", "buying_intent"), "pending")


def test_track_publish_success_and_failure():
    agent = AnalyticsAgent()

    item = {
        "opportunity": _sample_opportunity("reddit", "p1"),
        "draft": {"draft": "x"},
    }
    agent.track_publish(item, _publisher_result(success=True, platform="reddit"))
    agent.track_publish(
        item,
        _publisher_result(
            success=False,
            platform="quora",
            status="error: boom",
            published_url=None,
        ),
    )

    report = agent.generate_report()
    assert report["publish_outcomes"] == {"success": 1, "failure": 1}
    assert report["rates"]["publish_success_rate"] == pytest.approx(0.5)


def test_track_publish_requires_publisher_shape():
    agent = AnalyticsAgent()
    with pytest.raises(ValueError, match="missing keys"):
        agent.track_publish({"opportunity": {}}, {"success": True})


def test_generate_report_platform_distribution_and_top_lists():
    agent = AnalyticsAgent()

    agent.track_review(_minimal_review_item("a", "reddit", "buying_intent"), "approved")
    agent.track_review(_minimal_review_item("b", "reddit", "buying_intent"), "approved")
    agent.track_publish(
        {"opportunity": _sample_opportunity("quora", "q1"), "draft": {}},
        _publisher_result(success=True, platform="quora"),
    )

    report = agent.generate_report()
    assert report["platform_distribution"]["reddit"] == 2
    assert report["platform_distribution"]["quora"] == 1

    intents = {row["intent"]: row["count"] for row in report["top_intents"]}
    assert intents.get("buying_intent") == 2

    sources = {row["source"]: row["count"] for row in report["top_sources"]}
    assert sources["reddit"] == 2
    assert sources["quora"] == 1

    assert report["total_pipeline_volume"] == 3


def test_save_report_persists_round_trip(tmp_path: Path):
    out = tmp_path / "analytics.json"
    agent = AnalyticsAgent(output_path=str(out))

    agent.track_review(_minimal_review_item("rid-1", "medium", "feature_request"), "edited")
    agent.track_publish(
        {
            "opportunity": {"id": "pub-1", "platform": "medium"},
            "draft": {"draft": "hello"},
        },
        _publisher_result(success=True, platform="medium"),
    )

    path = agent.save_report()
    assert path == out
    assert out.is_file()

    data = json.loads(out.read_text(encoding="utf-8"))
    assert "updated_at" in data
    assert data["report"]["total_pipeline_volume"] == 2
    assert len(data["review_events"]) == 1
    assert data["review_events"][0]["review_status"] == "edited"
    assert data["review_events"][0]["intent"]["intent"] == "feature_request"
    assert len(data["publish_events"]) == 1
    pr = data["publish_events"][0]["publish_result"]
    assert pr["success"] is True
    assert set(pr.keys()) == {"success", "platform", "published_url", "status"}


def test_analytics_supabase_best_effort_does_not_break_json(tmp_path: Path, monkeypatch):
    """
    Supabase errors must never prevent JSON persistence.
    """
    out = tmp_path / "analytics.json"
    agent = AnalyticsAgent(output_path=str(out))
    agent.track_publish(
        {"opportunity": {"id": "1", "platform": "medium"}, "draft": {}},
        {"success": True, "platform": "medium", "published_url": None, "status": "ok"},
    )

    # Simulate configured Supabase but failing ping/save
    monkeypatch.setattr(
        "storage.supabase_store.get_supabase_client_from_settings",
        lambda *a, **k: type("C", (), {"is_configured": lambda s: True, "ping": lambda s: True})(),
    )
    monkeypatch.setattr(
        "storage.supabase_store.SupabaseTableStore",
        lambda *a, **k: type("T", (), {"save": lambda s, rows: (_ for _ in ()).throw(RuntimeError("boom"))})(),
    )

    agent.save_report()
    assert out.is_file()
