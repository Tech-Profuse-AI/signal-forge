"""
Phase 25 — Supabase-backed persistence via PostgREST.

Uses the Supabase REST API (PostgREST) with urllib (no extra deps) and
supports JSON fallback when Supabase is not configured or unreachable.

Note: This module assumes tables already exist in Supabase:
  - review_queue
  - analytics_events
  - learning_state
  - scheduled_tasks
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config.settings import Settings
from storage.base_store import JsonFileStore, is_supabase_configured

logger = logging.getLogger("signalforge.supabase_store")


class SupabaseError(RuntimeError):
    pass


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def _headers(key: str) -> Dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _http_json(
    url: str,
    *,
    method: str,
    headers: Dict[str, str],
    body: Optional[Any] = None,
    timeout: int = 20,
) -> Tuple[int, Any]:
    data_bytes: Optional[bytes] = None
    if body is not None:
        data_bytes = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = getattr(resp, "status", 200) or 200
    except urllib.error.HTTPError as exc:
        code = exc.code
        raw = exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise SupabaseError(f"network error: {exc}") from exc

    if not raw.strip():
        return code, None
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, raw


@dataclass(frozen=True)
class SupabaseClient:
    url: str
    key: str

    def table_url(self, table: str) -> str:
        return _join_url(self.url, f"rest/v1/{table}")

    def is_configured(self) -> bool:
        return is_supabase_configured(self.url, self.key)

    def ping(self) -> bool:
        """
        Lightweight connectivity check: attempt a HEAD-like GET with limit=1.
        """
        if not self.is_configured():
            return False
        try:
            url = self.table_url("scheduled_tasks") + "?select=id&limit=1"
            code, _ = _http_json(url, method="GET", headers=_headers(self.key), body=None)
            return code in (200, 206)
        except Exception:
            return False


@dataclass(frozen=True)
class SupabaseTableStore:
    """
    Generic table store with basic CRUD helpers.

    This store operates on rows (dicts).
    """

    client: SupabaseClient
    table: str
    primary_key: str = "id"

    def load(self) -> List[Dict[str, Any]]:
        url = self.client.table_url(self.table) + "?select=*"
        code, data = _http_json(url, method="GET", headers=_headers(self.client.key), body=None)
        if code not in (200, 206):
            raise SupabaseError(f"load failed HTTP {code}: {data}")
        return data if isinstance(data, list) else []

    def save(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Upsert many rows.
        """
        if not isinstance(rows, list):
            raise TypeError("SupabaseTableStore.save expects list[dict]")
        url = self.client.table_url(self.table)
        headers = _headers(self.client.key)
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        headers["Content-Type"] = "application/json"

        code, data = _http_json(url, method="POST", headers=headers, body=rows)
        if code not in (200, 201):
            raise SupabaseError(f"save failed HTTP {code}: {data}")
        return data if isinstance(data, list) else rows

    def update(self, key_value: str, patch: Dict[str, Any]) -> Any:
        url = self.client.table_url(self.table) + "?" + urllib.parse.urlencode(
            {f"{self.primary_key}": f"eq.{key_value}"}
        )
        headers = _headers(self.client.key)
        headers["Prefer"] = "return=representation"
        code, data = _http_json(url, method="PATCH", headers=headers, body=patch)
        if code not in (200, 204):
            raise SupabaseError(f"update failed HTTP {code}: {data}")
        return data

    def delete(self, key_value: str) -> Any:
        url = self.client.table_url(self.table) + "?" + urllib.parse.urlencode(
            {f"{self.primary_key}": f"eq.{key_value}"}
        )
        headers = _headers(self.client.key)
        headers["Prefer"] = "return=representation"
        code, data = _http_json(url, method="DELETE", headers=headers, body=None)
        if code not in (200, 204):
            raise SupabaseError(f"delete failed HTTP {code}: {data}")
        return data


def get_supabase_client_from_settings(settings: Optional[Settings] = None) -> SupabaseClient:
    s = settings or Settings()
    return SupabaseClient(url=s.supabase_url, key=s.supabase_key)


def supabase_or_json_table_store(
    *,
    table: str,
    json_path: Any,
    json_default: Any,
    primary_key: str = "id",
    settings: Optional[Settings] = None,
) -> Any:
    """
    Return a SupabaseTableStore when configured and reachable, else JsonFileStore.
    """
    client = get_supabase_client_from_settings(settings)
    if client.is_configured() and client.ping():
        return SupabaseTableStore(client=client, table=table, primary_key=primary_key)
    return JsonFileStore(path=json_path, default=json_default)


__all__ = [
    "SupabaseClient",
    "SupabaseTableStore",
    "SupabaseError",
    "get_supabase_client_from_settings",
    "supabase_or_json_table_store",
]

