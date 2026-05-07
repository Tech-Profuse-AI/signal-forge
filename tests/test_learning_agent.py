"""
Phase 19 — LearningAgent tests (mock analytics).

Run: cd SignalForge && pytest tests/test_learning_agent.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from agents.learning_agent import LearningAgent


def _intent(intent: str) -> Dict[str, Any]:
    return {
        "intent": intent,
        "confidence": 0.85,
        "reasoning": "mock",
        "business_relevance": "high",
        "recommended_action": "respond",
    }


def _score(priority_score: float, label: str = "warm") -> Dict[str, Any]:
    return {
        "priority_score": priority_score,
        "priority_label": label,
        "scoring_breakdown": {
            "intent_score": 10.0,
            "engagement_score": 5.0,
            "signal_boost": 2.0,
            "urgency_boost": 0.0,
        },
        "recommended_action": "respond_soon",
    }


def _review(
    review_id: str,
    status: str,
    platform: str,
    intent_name: str,
    priority_score: float,
    draft_body: str,
    tone: str = "casual",
    cta: str = "Optional CTA",
) -> Dict[str, Any]:
    return {
        "review_status": status,
        "tracked_at": "2026-05-01T00:00:00+00:00",
        "review_id": review_id,
        "opportunity": {
            "id": review_id,
            "platform": platform,
            "title": f"Title {review_id}",
            "url": f"https://example.com/{review_id}",
        },
        "draft": {"draft": draft_body, "tone": tone, "cta": cta, "reasoning": "mock"},
        "compliance": {"approved": True, "risk_level": "safe"},
        "intent": _intent(intent_name),
        "score": _score(priority_score),
    }


def _publish(
    platform: str,
    success: bool,
    opp_id: str = "pub-1",
) -> Dict[str, Any]:
    return {
        "tracked_at": "2026-05-01T01:00:00+00:00",
        "opportunity": {"id": opp_id, "platform": platform},
        "draft": {"draft": "publish body"},
        "publish_result": {
            "success": success,
            "platform": platform,
            "published_url": "https://mock.example/p/1" if success else None,
            "status": "mock_published" if success else "error: failed",
        },
    }


def _rich_mock_analytics() -> Dict[str, Any]:
    """Synthetic history: hiring_intent converts; problem_intent lags; reddit publishes well."""
    reviews: List[Dict[str, Any]] = [
        # hiring_intent — strong approval (3/3)
        _review("r1", "approved", "reddit", "hiring_intent", 72.0, "short draft one"),
        _review("r2", "approved", "reddit", "hiring_intent", 68.0, "short draft two"),
        _review("r3", "approved", "quora", "hiring_intent", 70.0, "short draft three"),
        # problem_intent — weak (3 reviews, 1 approved)
        _review("r4", "rejected", "reddit", "problem_intent", 65.0, "longer draft text " * 8),
        _review("r5", "rejected", "reddit", "problem_intent", 62.0, "longer draft text " * 8),
        _review("r6", "approved", "reddit", "problem_intent", 60.0, "longer draft text " * 8),
        # edited — shorter originals vs approved hiring (word count pattern)
        _review("r7", "edited", "medium", "buying_intent", 55.0, "tiny", cta=""),
        _review("r8", "edited", "medium", "buying_intent", 52.0, "also tiny", cta=""),
        _review("r9", "edited", "medium", "buying_intent", 58.0, "small", cta=""),
        # low-score approvals for threshold signal (below median ~60)
        _review("r10", "approved", "reddit", "feature_request", 35.0, "low score approved"),
        _review("r11", "approved", "reddit", "feature_request", 38.0, "low score approved two"),
    ]
    publishes: List[Dict[str, Any]] = [
        _publish("reddit", True, "p1"),
        _publish("reddit", True, "p2"),
        _publish("reddit", True, "p3"),
        _publish("quora", False, "p4"),
        _publish("quora", False, "p5"),
        _publish("quora", False, "p6"),
    ]
    return {
        "updated_at": "2026-05-04T12:00:00+00:00",
        "report": {"total_pipeline_volume": len(reviews) + len(publishes)},
        "review_events": reviews,
        "publish_events": publishes,
    }


def test_load_analytics_from_file(tmp_path: Path):
    analytics_path = tmp_path / "analytics.json"
    payload = _rich_mock_analytics()
    analytics_path.write_text(json.dumps(payload), encoding="utf-8")

    agent = LearningAgent(
        analytics_path=str(analytics_path),
        learning_state_path=str(tmp_path / "learning_state.json"),
    )
    loaded = agent.load_analytics()

    assert loaded["review_events"][0]["review_id"] == "r1"
    assert len(loaded["publish_events"]) == 6


def test_pattern_learning_identifies_intent_and_platform_signals(tmp_path: Path):
    analytics_path = tmp_path / "analytics.json"
    analytics_path.write_text(json.dumps(_rich_mock_analytics()), encoding="utf-8")

    agent = LearningAgent(
        analytics_path=str(analytics_path),
        learning_state_path=str(tmp_path / "learning_state.json"),
    )
    patterns = agent.learn()

    assert patterns["intent_performance"]["hiring_intent"]["approval_rate"] == 1.0
    assert patterns["intent_performance"]["problem_intent"]["approval_rate"] < 0.5
    assert patterns["platform_performance"]["reddit"]["publish_success_rate"] == 1.0
    assert patterns["platform_performance"]["quora"]["publish_success_rate"] == 0.0
    assert "score_quality" in patterns
    assert patterns["drafting_edit_patterns"]["edited_draft_stats"]["count"] == 3


def test_generate_recommendations_structure_and_scoring_alignment(tmp_path: Path):
    analytics_path = tmp_path / "analytics.json"
    analytics_path.write_text(json.dumps(_rich_mock_analytics()), encoding="utf-8")

    agent = LearningAgent(
        analytics_path=str(analytics_path),
        learning_state_path=str(tmp_path / "learning_state.json"),
    )
    rec = agent.generate_recommendations()

    assert set(rec.keys()) == {
        "score_weight_adjustments",
        "platform_priority_adjustments",
        "intent_priority_adjustments",
        "drafting_insights",
        "confidence",
    }
    assert isinstance(rec["confidence"], float)
    assert 0.0 <= rec["confidence"] <= 1.0

    sw = rec["score_weight_adjustments"]
    assert "intent_weight_deltas" in sw
    assert "threshold_deltas" in sw
    assert "baseline_reference" in sw
    assert "default_intent_weights" in sw["baseline_reference"]

    # hiring_intent should be boosted; problem_intent penalised
    deltas = sw["intent_weight_deltas"]
    assert deltas.get("hiring_intent", 0) > 0
    assert deltas.get("problem_intent", 0) < 0

    plat = rec["platform_priority_adjustments"]["platform_multipliers"]
    assert plat.get("reddit", 1.0) > plat.get("quora", 1.0)

    insights = rec["drafting_insights"]
    assert "edited_vs_approved" in insights
    assert "inferred_patterns" in insights


def test_save_learning_state_persists_file(tmp_path: Path):
    analytics_path = tmp_path / "analytics.json"
    analytics_path.write_text(json.dumps(_rich_mock_analytics()), encoding="utf-8")
    state_path = tmp_path / "learning_state.json"

    agent = LearningAgent(
        analytics_path=str(analytics_path),
        learning_state_path=str(state_path),
    )
    path = agent.save_learning_state()

    assert path == state_path
    assert state_path.is_file()

    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert "updated_at" in data
    assert "confidence" in data
    assert "score_weight_adjustments" in data
    assert "patterns_summary" in data


def test_learning_supabase_best_effort_does_not_break_json(tmp_path: Path, monkeypatch):
    analytics_path = tmp_path / "analytics.json"
    analytics_path.write_text(json.dumps(_rich_mock_analytics()), encoding="utf-8")
    state_path = tmp_path / "learning_state.json"

    agent = LearningAgent(analytics_path=str(analytics_path), learning_state_path=str(state_path))

    monkeypatch.setattr(
        "storage.supabase_store.get_supabase_client_from_settings",
        lambda *a, **k: type("C", (), {"is_configured": lambda s: True, "ping": lambda s: True})(),
    )
    monkeypatch.setattr(
        "storage.supabase_store.SupabaseTableStore",
        lambda *a, **k: type("T", (), {"save": lambda s, rows: (_ for _ in ()).throw(RuntimeError("boom"))})(),
    )

    agent.save_learning_state()
    assert state_path.is_file()


def test_missing_analytics_yields_low_confidence_and_empty_deltas(tmp_path: Path):
    missing = tmp_path / "nope.json"
    state_path = tmp_path / "learning_state.json"
    agent = LearningAgent(
        analytics_path=str(missing),
        learning_state_path=str(state_path),
    )
    assert agent.load_analytics() == {}
    rec = agent.generate_recommendations()
    assert rec["confidence"] == 0.0
    assert rec["score_weight_adjustments"]["intent_weight_deltas"] == {}
