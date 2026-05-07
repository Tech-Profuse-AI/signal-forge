"""
Phase 25 — ReviewQueue persistence tests (Supabase mocked, JSON fallback).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflows.review_queue import ReviewQueue


def test_review_queue_json_fallback_round_trip(tmp_path: Path):
    path = tmp_path / ".review_queue.json"
    q = ReviewQueue(queue_path=str(path))
    item = {
        "opportunity": {"id": "o1"},
        "draft": {"draft": "hello", "cta": ""},
        "compliance": {"approved": True, "safe_draft": "hello"},
    }
    rec = q.enqueue(item)
    assert rec["review_status"] == "pending"
    assert q.stats["pending"] == 1


def test_review_queue_supabase_mocked_does_not_break(tmp_path: Path, monkeypatch):
    """
    When Supabase is configured and reachable, ReviewQueue uses it;
    if Supabase save fails, it falls back to JSON without crashing.
    """
    path = tmp_path / ".review_queue.json"

    class _FakeStore:
        table = "review_queue"
        def load(self):
            return []
        def save(self, rows):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "storage.supabase_store.supabase_or_json_table_store",
        lambda **kwargs: _FakeStore(),
    )

    q = ReviewQueue(queue_path=str(path))
    item = {
        "opportunity": {"id": "o1"},
        "draft": {"draft": "hello", "cta": ""},
        "compliance": {"approved": True, "safe_draft": "hello"},
    }
    q.enqueue(item)
    assert path.exists()
