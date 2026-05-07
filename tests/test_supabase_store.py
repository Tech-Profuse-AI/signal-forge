"""
Phase 25 — Supabase store tests (HTTP mocked; no real Supabase).
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

import pytest

from storage.supabase_store import SupabaseClient, SupabaseTableStore, SupabaseError


class _FakeResp:
    def __init__(self, status: int, payload: Any):
        self.status = status
        self._payload = payload

    def read(self) -> bytes:
        if self._payload is None:
            return b""
        if isinstance(self._payload, (dict, list)):
            return json.dumps(self._payload).encode("utf-8")
        return str(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_supabase_table_store_load_save_update_delete(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=20):
        calls.append((req.method, req.full_url))
        if req.method == "GET":
            return _FakeResp(200, [{"id": "1", "x": 1}])
        if req.method == "POST":
            return _FakeResp(201, [{"id": "1"}])
        if req.method == "PATCH":
            return _FakeResp(200, [{"id": "1", "x": 2}])
        if req.method == "DELETE":
            return _FakeResp(200, [{"id": "1"}])
        return _FakeResp(400, {"error": "bad"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = SupabaseClient(url="https://example.supabase.co", key="k")
    store = SupabaseTableStore(client=client, table="scheduled_tasks", primary_key="id")

    rows = store.load()
    assert rows and rows[0]["id"] == "1"

    out = store.save([{"id": "1"}])
    assert isinstance(out, list)

    updated = store.update("1", {"x": 2})
    assert updated

    deleted = store.delete("1")
    assert deleted


def test_supabase_client_ping_false_when_not_configured():
    client = SupabaseClient(url="", key="")
    assert client.is_configured() is False
    assert client.ping() is False

