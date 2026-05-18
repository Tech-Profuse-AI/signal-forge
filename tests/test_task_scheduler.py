"""
Phase 23 — TaskScheduler tests.

Run:
    cd SignalForge && pytest tests/test_task_scheduler.py -v
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scheduler.task_scheduler import MAX_RETRIES, TaskScheduler


class FakeAnalytics:
    def __init__(self, path: Path):
        self.path = path
        self.publish_events: List[Dict[str, Any]] = []

    def track_publish(self, item: Dict[str, Any], publish_result: Dict[str, Any]) -> None:
        self.publish_events.append({"item": item, "publish_result": publish_result})

    def save_report(self) -> Path:
        payload = {
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "report": {"total_pipeline_volume": len(self.publish_events)},
            "review_events": [],
            "publish_events": [
                {
                    "tracked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "opportunity": e["item"].get("opportunity", {}),
                    "draft": e["item"].get("draft", {}),
                    "publish_result": e["publish_result"],
                }
                for e in self.publish_events
            ],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return self.path


class FakeLearning:
    def __init__(self, path: Path):
        self.path = path
        self.calls = 0

    def save_learning_state(self) -> Path:
        self.calls += 1
        self.path.write_text(
            json.dumps(
                {
                    "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "confidence": 0.0,
                    "score_weight_adjustments": {},
                    "platform_priority_adjustments": {},
                    "intent_priority_adjustments": {},
                    "drafting_insights": {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return self.path


def test_task_creation_persistence_listing_and_cancellation(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()

    sched = TaskScheduler(outputs_dir=str(outputs), pipeline_executor=lambda q: {"ok": True})
    task = sched.schedule_task("AI automation", "daily")

    tasks_file = outputs / "scheduled_tasks.json"
    assert tasks_file.is_file()

    tasks = sched.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task["id"]
    assert tasks[0]["frequency"] == "daily"
    assert tasks[0]["active"] is True
    assert isinstance(tasks[0]["next_run"], str)

    assert sched.cancel_task(task["id"]) is True
    tasks2 = sched.list_tasks()
    assert tasks2[0]["active"] is False


def test_scheduler_uses_supabase_task_store_when_configured(tmp_path: Path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()

    # Configure Supabase settings env and mock ping + table operations.
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "k")
    monkeypatch.setenv("SIGNALFORGE_SCHEDULER_BACKEND", "supabase")

    class _FakeTable:
        def __init__(self):
            self.saved = []
        def load(self):
            return []
        def save(self, rows):
            self.saved.extend(rows)
            return rows

    monkeypatch.setattr("storage.supabase_store.get_supabase_client_from_settings", lambda *a, **k: type("C", (), {"is_configured": lambda s: True, "ping": lambda s: True, "key": "k", "url": "u", "table_url": lambda s, t: ""})())
    monkeypatch.setattr("storage.supabase_store.SupabaseTableStore", lambda client, table, primary_key="id": _FakeTable())

    sched = TaskScheduler(outputs_dir=str(outputs), pipeline_executor=lambda q: {"ok": True})
    task = sched.schedule_task("x", "daily")
    assert task["id"].startswith("task-")


def test_run_all_pending_executes_due_tasks_and_tracks_analytics_and_learning(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()

    executed: List[str] = []

    def executor(q: str) -> Dict[str, Any]:
        executed.append(q)
        return {"ok": True}

    analytics_path = outputs / "analytics.json"
    learning_path = outputs / "learning_state.json"
    fake_analytics = FakeAnalytics(analytics_path)
    fake_learning = FakeLearning(learning_path)

    sched = TaskScheduler(
        outputs_dir=str(outputs),
        pipeline_executor=executor,
        analytics_factory=lambda: fake_analytics,
        learning_factory=lambda: fake_learning,
    )
    task = sched.schedule_task("community engagement scaling", "hourly")

    # Force due
    tasks = sched.list_tasks()
    tasks[0]["next_run"] = (
        datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=1)
    ).isoformat()
    (outputs / "scheduled_tasks.json").write_text(
        json.dumps({"updated_at": "x", "tasks": tasks}, indent=2),
        encoding="utf-8",
    )

    results = sched.run_all_pending()
    assert len(results) == 1
    assert results[0]["task_id"] == task["id"]
    assert results[0]["success"] is True
    assert executed == ["community engagement scaling"]

    # Analytics: one publish-style tracking event
    assert analytics_path.is_file()
    data = json.loads(analytics_path.read_text(encoding="utf-8"))
    assert len(data["publish_events"]) == 1
    pr = data["publish_events"][0]["publish_result"]
    assert pr["platform"] == "scheduler"
    assert pr["success"] is True
    assert "frequency=hourly" in pr["status"]

    # Learning triggered after success
    assert learning_path.is_file()
    assert fake_learning.calls == 1


def test_retry_behavior_marks_failed_after_max_retries(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()

    calls = 0

    def failing_executor(q: str) -> Dict[str, Any]:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    fake_analytics = FakeAnalytics(outputs / "analytics.json")
    fake_learning = FakeLearning(outputs / "learning_state.json")

    sched = TaskScheduler(
        outputs_dir=str(outputs),
        pipeline_executor=failing_executor,
        analytics_factory=lambda: fake_analytics,
        learning_factory=lambda: fake_learning,
    )
    task = sched.schedule_task("x", "daily")

    # Make it due every time
    for _ in range(MAX_RETRIES):
        tasks = sched.list_tasks()
        tasks[0]["next_run"] = (
            datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=1)
        ).isoformat()
        (outputs / "scheduled_tasks.json").write_text(
            json.dumps({"updated_at": "x", "tasks": tasks}, indent=2),
            encoding="utf-8",
        )
        res = sched.run_all_pending()
        assert len(res) == 1
        assert res[0]["success"] is False

    assert calls == MAX_RETRIES

    # After max retries, task becomes inactive
    final = sched.list_tasks()[0]
    assert final["id"] == task["id"]
    assert final["active"] is False
    assert final["retry_count"] == MAX_RETRIES

    # Failure log exists
    failures = outputs / "scheduled_task_failures.json"
    assert failures.is_file()
    fdata = json.loads(failures.read_text(encoding="utf-8"))
    assert len(fdata["failures"]) >= MAX_RETRIES
