"""
SignalForge Phase 23 — Scheduler and Automation Engine.

Persists minimal recurring tasks in JSON and executes the existing pipeline
runner without duplicating pipeline logic.

Storage is abstracted behind a small TaskStore interface so the JSON file
can later be swapped for Supabase without changing the scheduler behavior.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol
from uuid import uuid4

from agents.analytics_agent import AnalyticsAgent
from agents.learning_agent import LearningAgent

logger = logging.getLogger("signalforge.scheduler")

SUPPORTED_FREQUENCIES = frozenset({"hourly", "daily", "weekly"})
MAX_RETRIES = 3


class TaskStore(Protocol):
    def load(self) -> List[Dict[str, Any]]: ...

    def save(self, tasks: List[Dict[str, Any]]) -> None: ...


@dataclass(frozen=True)
class JsonFileTaskStore:
    path: Path

    def load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"scheduled tasks store is not valid JSON: {self.path}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            raise ValueError(f"scheduled tasks store is malformed: {self.path}")
        tasks = data["tasks"]
        return tasks if isinstance(tasks, list) else []

    def save(self, tasks: List[Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": _timestamp(),
            "tasks": tasks,
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )


@dataclass(frozen=True)
class JsonFailureLog:
    path: Path

    def append(self, entry: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing: List[Dict[str, Any]] = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("failures"), list):
                    existing = list(data["failures"])
            except json.JSONDecodeError:
                existing = []
        existing.append(entry)
        self.path.write_text(
            json.dumps({"updated_at": _timestamp(), "failures": existing}, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )


class TaskScheduler:
    """
    Minimal recurring task scheduler for SignalForge.

    The scheduler triggers an injected pipeline executor. By default it uses
    ``run_signalforge.run_pipeline`` which already orchestrates the core
    SignalForge graph and review queue.
    """

    def __init__(
        self,
        *,
        store: Optional[TaskStore] = None,
        failures: Optional[JsonFailureLog] = None,
        outputs_dir: Optional[str] = None,
        pipeline_executor: Optional[Callable[[str], Dict[str, Any]]] = None,
        analytics_factory: Callable[[], AnalyticsAgent] = AnalyticsAgent,
        learning_factory: Callable[[], LearningAgent] = LearningAgent,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        explicit_outputs_dir = outputs_dir is not None
        out_dir = Path(outputs_dir) if outputs_dir else root / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)

        if store is not None:
            self._store = store
        elif _should_use_supabase_store(explicit_outputs_dir=explicit_outputs_dir):
            # Phase 25: prefer Supabase-backed scheduled_tasks if configured.
            try:
                from storage.supabase_store import (  # noqa: PLC0415
                    SupabaseTableStore,
                    get_supabase_client_from_settings,
                )

                client = get_supabase_client_from_settings()
                if client.is_configured() and client.ping():
                    self._store = SupabaseTaskStore(
                        table_store=SupabaseTableStore(
                            client=client,
                            table="scheduled_tasks",
                            primary_key="id",
                        )
                    )
                else:
                    self._store = JsonFileTaskStore(out_dir / "scheduled_tasks.json")
            except Exception:
                self._store = JsonFileTaskStore(out_dir / "scheduled_tasks.json")
        else:
            self._store = JsonFileTaskStore(out_dir / "scheduled_tasks.json")
        self._failures = failures or JsonFailureLog(out_dir / "scheduled_task_failures.json")
        self._analytics_factory = analytics_factory
        self._learning_factory = learning_factory

        if pipeline_executor is None:
            # Default: reuse the existing Phase 10 runner (no pipeline logic duplication).
            from run_signalforge import run_pipeline

            self._pipeline_executor = run_pipeline
        else:
            self._pipeline_executor = pipeline_executor

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    def schedule_task(self, query: str, frequency: str) -> Dict[str, Any]:
        freq = _clean_text(frequency).lower()
        if freq not in SUPPORTED_FREQUENCIES:
            raise ValueError(f"frequency must be one of {sorted(SUPPORTED_FREQUENCIES)}")
        q = _clean_text(query)
        if not q:
            raise ValueError("query must be a non-empty string")

        tasks = self._store.load()
        task_id = f"task-{uuid4().hex[:12]}"
        now = _now()
        task = {
            "id": task_id,
            "query": q,
            "frequency": freq,
            "next_run": _format_dt(_next_run(now, freq)),
            "retry_count": 0,
            "active": True,
        }
        tasks.append(task)
        self._store.save(tasks)
        return dict(task)

    def list_tasks(self) -> List[Dict[str, Any]]:
        return [dict(t) for t in self._store.load()]

    def cancel_task(self, task_id: str) -> bool:
        tid = _clean_text(task_id)
        tasks = self._store.load()
        changed = False
        for task in tasks:
            if task.get("id") == tid:
                task["active"] = False
                changed = True
        if changed:
            self._store.save(tasks)
        return changed

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_scheduled_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run one task and update persistence.

        Returns a dict with:
            success: bool
            task_id: str
            status: str
            retries_used: int
        """
        task_id = str(task.get("id", ""))
        frequency = str(task.get("frequency", ""))
        query = str(task.get("query", ""))

        tasks = self._store.load()
        live = next((t for t in tasks if t.get("id") == task_id), None)
        if live is None:
            raise KeyError(f"Task not found: {task_id}")
        if not live.get("active", False):
            return {
                "success": False,
                "task_id": task_id,
                "status": "skipped: task inactive",
                "retries_used": int(live.get("retry_count", 0) or 0),
            }

        now = _now()
        success = False
        status = "error: unknown"
        try:
            self._pipeline_executor(query)
            success = True
            status = "ok"
            live["retry_count"] = 0
            live["next_run"] = _format_dt(_next_run(now, frequency))
        except Exception as exc:  # noqa: BLE001
            live["retry_count"] = int(live.get("retry_count", 0) or 0) + 1
            status = f"error: execution failed — {exc}"
            self._failures.append({
                "task_id": task_id,
                "query": query,
                "frequency": frequency,
                "run_at": _timestamp(),
                "retry_count": int(live["retry_count"]),
                "error": str(exc),
            })
            if int(live["retry_count"]) >= MAX_RETRIES:
                live["active"] = False
                live["next_run"] = _format_dt(_next_run(now, frequency))
                status = f"failed: max retries reached ({MAX_RETRIES})"
            else:
                live["next_run"] = _format_dt(now + timedelta(minutes=10))

        # Persist task updates
        self._store.save(tasks)

        # Analytics + learning hooks (best-effort; no hard failures)
        try:
            self._track_execution_in_analytics(
                success=success,
                frequency=frequency,
                task_id=task_id,
                query=query,
                status=status,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analytics tracking failed: %s", exc)

        if success:
            try:
                self._trigger_learning_update()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Learning update failed: %s", exc)

        return {
            "success": success,
            "task_id": task_id,
            "status": status,
            "retries_used": int(live.get("retry_count", 0) or 0),
        }

    def run_all_pending(self) -> List[Dict[str, Any]]:
        tasks = self._store.load()
        now = _now()
        results: List[Dict[str, Any]] = []
        for task in tasks:
            if not task.get("active", False):
                continue
            next_run = _parse_dt(str(task.get("next_run", "")))
            if next_run is None or next_run <= now:
                results.append(self.run_scheduled_task(task))
        return results

    # ------------------------------------------------------------------
    # Internal: analytics + learning integration
    # ------------------------------------------------------------------

    def _track_execution_in_analytics(
        self,
        *,
        success: bool,
        frequency: str,
        task_id: str,
        query: str,
        status: str,
    ) -> None:
        """
        Reuse AnalyticsAgent's existing publish-event schema to track scheduler runs.

        This does not change AnalyticsAgent; it stores a publish_result dict with
        the existing keys and a platform value of 'scheduler'.
        """
        analytics = self._analytics_factory()
        item = {
            "opportunity": {
                "id": task_id,
                "platform": "scheduler",
                "source": "scheduler",
                "query": query,
            },
            "draft": {
                "title": f"scheduled:{frequency}",
                "draft": query,
            },
        }
        publish_result = {
            "success": bool(success),
            "platform": "scheduler",
            "published_url": None,
            "status": f"{status} (frequency={frequency})",
        }
        analytics.track_publish(item, publish_result)
        analytics.save_report()

    def _trigger_learning_update(self) -> None:
        learning = self._learning_factory()
        learning.save_learning_state()


class SupabaseTaskStore:
    """
    TaskStore implementation backed by Supabase table `scheduled_tasks`.

    Stores tasks as individual rows (schema-preserving). TaskScheduler logic
    remains unchanged; only storage is swapped.
    """

    def __init__(self, table_store: Any) -> None:
        self._table = table_store

    def load(self) -> List[Dict[str, Any]]:
        rows = self._table.load()
        tasks: List[Dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                # Row may include additional Supabase fields; keep minimal schema.
                tasks.append({
                    "id": row.get("id", ""),
                    "query": row.get("query", ""),
                    "frequency": row.get("frequency", ""),
                    "next_run": row.get("next_run", ""),
                    "retry_count": int(row.get("retry_count", 0) or 0),
                    "active": bool(row.get("active", False)),
                })
        return tasks

    def save(self, tasks: List[Dict[str, Any]]) -> None:
        rows: List[Dict[str, Any]] = []
        for task in tasks:
            if isinstance(task, dict):
                rows.append({
                    "id": task.get("id", ""),
                    "query": task.get("query", ""),
                    "frequency": task.get("frequency", ""),
                    "next_run": task.get("next_run", ""),
                    "retry_count": int(task.get("retry_count", 0) or 0),
                    "active": bool(task.get("active", False)),
                })
        self._table.save(rows)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _timestamp() -> str:
    return _now().isoformat()


def _format_dt(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _parse_dt(text: str) -> Optional[datetime]:
    raw = _clean_text(text)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _next_run(now: datetime, frequency: str) -> datetime:
    freq = _clean_text(frequency).lower()
    if freq == "hourly":
        return now + timedelta(hours=1)
    if freq == "daily":
        return now + timedelta(days=1)
    if freq == "weekly":
        return now + timedelta(weeks=1)
    return now + timedelta(days=1)


def _clean_text(text: str) -> str:
    return " ".join(str(text).split()).strip()


def _should_use_supabase_store(*, explicit_outputs_dir: bool) -> bool:
    backend = os.environ.get("SIGNALFORGE_SCHEDULER_BACKEND", "").strip().lower()
    if backend in {"supabase", "remote"}:
        return True
    if backend in {"json", "local", "file"}:
        return False
    return not explicit_outputs_dir


__all__ = [
    "TaskScheduler",
    "TaskStore",
    "JsonFileTaskStore",
    "SUPPORTED_FREQUENCIES",
    "MAX_RETRIES",
]
