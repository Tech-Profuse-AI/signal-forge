"""
SignalForge review queue - Phase 9.

Stores Slack human-review work locally in JSON so pending and reviewed items
survive across runs without adding publishing or analytics concerns.
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict
from uuid import uuid4

from schemas.opportunity import serialize_opportunity

logger = logging.getLogger("signalforge.review_queue")

VALID_REVIEW_STATUSES = frozenset([
    "pending",
    "approved",
    "approved_for_posting",
    "rejected",
    "edited",
])
REVIEW_DECISION_STATUSES = frozenset(["approved", "rejected", "edited"])
_ACTION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "edit": "edited",
}


class ReviewActionResult(TypedDict):
    """Structured review result returned after a human action."""

    review_status: str
    reviewer_action: str
    final_draft: str


class ReviewQueue:
    """JSON-backed queue for human review items."""

    def __init__(
        self,
        queue_path: Optional[str] = None,
        store: Any = None,
        use_supabase: Optional[bool] = None,
    ) -> None:
        default_path = Path(__file__).resolve().with_name(".review_queue.json")
        explicit_queue_path = queue_path is not None
        self._queue_path = Path(queue_path) if queue_path else default_path
        self._queue_path.parent.mkdir(parents=True, exist_ok=True)
        self._store = store
        self._use_supabase = self._resolve_supabase_preference(
            explicit_queue_path=explicit_queue_path,
            use_supabase=use_supabase,
        )
        self._ensure_store()
        
        backend = "Supabase" if (self._store is not None and hasattr(self._store, "table")) else "JSON"
        logger.info("ReviewQueue initialised - backend=%s path=%s", backend, self._queue_path)

    def enqueue(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Add an item to the review queue, defaulting to pending status."""
        if not self._is_valid_item(item):
            raise ValueError(
                "Review queue items must include a valid opportunity, URL, and draft."
            )

        store = self._load_store()
        review_id = self._build_unique_review_id(item, store["items"])
        initial_status = self._clean_text(str(item.get("review_status") or "pending")).lower()
        if initial_status not in VALID_REVIEW_STATUSES:
            initial_status = "pending"

        timestamp = self._timestamp()
        canonical = serialize_opportunity(
            item,
            status=initial_status,
            can_mutate=True,
        )
        final_draft = self._initial_final_draft(item)
        record = {
            **canonical,
            "id": review_id,
            "review_id": review_id,
            "draft": final_draft,
            "final_draft": final_draft,
            "review_status": initial_status,
            "status": initial_status,
            "reviewer_action": self._clean_text(str(item.get("reviewer_action", ""))),
            "review_channel": self._clean_text(str(item.get("review_channel", ""))),
            "reviewer": "",
            "created_at": timestamp,
            "updated_at": timestamp,
            "dequeued_at": "",
            "reviewed_at": timestamp if initial_status != "pending" else "",
        }
        store["items"].append(record)
        self._save_store(store)

        logger.info("Enqueued review item - review_id=%s", review_id)
        return deepcopy(record)

    def dequeue(self) -> Optional[Dict[str, Any]]:
        """
        Return the next pending review item and mark when it was surfaced.

        The item remains in the JSON store so later review decisions can update
        the same record by ``review_id``.
        """
        store = self._load_store()
        for record in store["items"]:
            status = self._clean_text(
                str(record.get("review_status") or record.get("status") or "")
            ).lower()
            if status != "pending":
                continue
            if not record.get("dequeued_at"):
                record["dequeued_at"] = self._timestamp()
                self._save_store(store)
            logger.info("Dequeued review item - review_id=%s", record["review_id"])
            return deepcopy(record)

        logger.info("Dequeue requested but no pending review items were found")
        return None

    def mark_reviewed(self, item: Dict[str, Any]) -> ReviewActionResult:
        """Mark an existing review item as approved, rejected, or edited."""
        if not isinstance(item, dict):
            raise TypeError(f"item must be a dict, got {type(item).__name__}")

        review_id = self._clean_text(str(item.get("review_id", "")))
        action = self._clean_text(
            str(item.get("reviewer_action") or item.get("action") or "")
        ).lower()
        review_status = self._clean_text(str(item.get("review_status", ""))).lower()

        if not review_id:
            raise ValueError("review_id is required to mark a review item.")
        if not review_status:
            review_status = _ACTION_TO_STATUS.get(action, "")
        if review_status not in REVIEW_DECISION_STATUSES:
            raise ValueError(
                "review_status must be one of approved, rejected, or edited."
            )
        if not action:
            action = self._status_to_action(review_status)

        store = self._load_store()
        record = self._find_record(store["items"], review_id)
        if record is None:
            raise KeyError(f"Review item '{review_id}' was not found.")

        final_draft = self._final_draft_for_action(record, item, review_status)
        record["review_status"] = review_status
        record["status"] = review_status
        record["reviewer_action"] = action
        record["final_draft"] = final_draft
        record["draft"] = final_draft
        record["updated_at"] = self._timestamp()
        record["reviewer"] = self._clean_text(str(item.get("reviewer", "")))
        record["reviewed_at"] = record["updated_at"]

        self._save_store(store)
        logger.info(
            "Marked review item - review_id=%s status=%s action=%s",
            review_id,
            review_status,
            action,
        )
        return {
            "review_status": review_status,
            "reviewer_action": action,
            "final_draft": final_draft,
        }

    def handle_action(self, payload: Dict[str, Any]) -> ReviewActionResult:
        """Handle a simplified review-action payload."""
        if not isinstance(payload, dict):
            raise TypeError(f"payload must be a dict, got {type(payload).__name__}")

        action = self._clean_text(str(payload.get("action", ""))).lower()
        if action not in _ACTION_TO_STATUS:
            raise ValueError(
                f"Unsupported review action '{action}'. "
                f"Expected one of: {', '.join(sorted(_ACTION_TO_STATUS))}"
            )

        review_id = self._clean_text(str(payload.get("review_id", "")))
        if not review_id:
            raise ValueError("review_id is required for a review action.")

        return self.mark_reviewed({
            "review_id": review_id,
            "review_status": _ACTION_TO_STATUS[action],
            "reviewer_action": action,
            "final_draft": payload.get("final_draft", ""),
            "edited_draft": payload.get("edited_draft", ""),
            "reviewer": payload.get("reviewer", ""),
        })

    @property
    def items(self) -> List[Dict[str, Any]]:
        """Return a deep copy of all stored review records."""
        return deepcopy(self._load_store()["items"])

    @property
    def stats(self) -> Dict[str, int]:
        """Return queue counts by status."""
        counts = {status: 0 for status in VALID_REVIEW_STATUSES}
        items = self._load_store()["items"]
        for record in items:
            status = self._clean_text(
                str(record.get("review_status") or record.get("status") or "")
            ).lower()
            if status in counts:
                counts[status] += 1

        counts["total"] = len(items)
        return counts

    def _ensure_store(self) -> None:
        # Initialise the store right away to determine if we're using Supabase or JSON
        if self._store is None:
            self._load_store()

        if self._store is not None and hasattr(self._store, "table"):
            # Supabase is active, no need to ensure a local JSON file
            return

        # JSON fallback initialization
        if self._queue_path.exists():
            return
        self._save_store({"items": []})

    def _load_store(self) -> Dict[str, List[Dict[str, Any]]]:
        if self._store is None:
            from storage.base_store import JsonFileStore  # noqa: PLC0415

            if self._use_supabase:
                # Try Supabase-backed store first; fall back to JSON.
                try:
                    from storage.supabase_store import supabase_or_json_table_store  # noqa: PLC0415

                    store = supabase_or_json_table_store(
                        table="review_queue",
                        json_path=self._queue_path,
                        json_default={"items": []},
                        primary_key="review_id",
                    )
                    # Supabase table store returns list[rows]; we store dict payloads in "record".
                    self._store = store
                except Exception:
                    self._store = JsonFileStore(path=self._queue_path, default={"items": []})
            else:
                self._store = JsonFileStore(path=self._queue_path, default={"items": []})

        # Supabase path
        if hasattr(self._store, "table") and getattr(self._store, "table", "") == "review_queue":
            try:
                rows = self._store.load()
                items: List[Dict[str, Any]] = []
                for row in rows:
                    if isinstance(row, dict) and isinstance(row.get("record"), dict):
                        items.append(row["record"])
                return {"items": self._normalize_loaded_items(items)}
            except Exception:
                # Fall through to JSON
                pass

        if not self._queue_path.exists():
            return {"items": []}

        try:
            data = json.loads(self._queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Review queue store is not valid JSON: {self._queue_path}"
            ) from exc

        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError(
                f"Review queue store is malformed: {self._queue_path}"
            )
        return {"items": self._normalize_loaded_items(data["items"])}

    def _save_store(self, store: Dict[str, List[Dict[str, Any]]]) -> None:
        if self._store is not None and hasattr(self._store, "table") and getattr(self._store, "table", "") == "review_queue":
            # Upsert each record into Supabase as {review_id, record}
            try:
                items = store.get("items", [])
                rows = []
                for record in items:
                    if isinstance(record, dict):
                        rid = record.get("review_id", "")
                        if rid:
                            rows.append({"review_id": rid, "record": record})
                self._store.save(rows)
                return
            except Exception:
                # If Supabase save fails, fall back to JSON.
                pass

        self._queue_path.write_text(
            json.dumps(store, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    @staticmethod
    def _find_record(
        items: List[Dict[str, Any]],
        review_id: str,
    ) -> Optional[Dict[str, Any]]:
        for record in items:
            if record.get("review_id") == review_id:
                return record
        return None

    @staticmethod
    def _normalize_loaded_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        safe_items: List[Dict[str, Any]] = []
        for record in items:
            if not isinstance(record, dict):
                continue
            safe_items.append({
                **record,
                **serialize_opportunity(record, can_mutate=True),
            })
        return safe_items

    def _build_unique_review_id(
        self,
        item: Dict[str, Any],
        items: List[Dict[str, Any]],
    ) -> str:
        existing_ids = {self._clean_text(str(entry.get("review_id", ""))) for entry in items}
        base_id = self._clean_text(str(item.get("review_id", "")))
        if not base_id:
            opportunity = item.get("opportunity", {})
            opportunity_id = self._clean_text(
                str(
                    item.get("opportunity_id")
                    or item.get("id")
                    or (
                        opportunity.get("id", "")
                        if isinstance(opportunity, dict)
                        else ""
                    )
                )
            )
            if opportunity_id:
                base_id = f"review-{opportunity_id}"
            else:
                base_id = f"review-{uuid4().hex[:12]}"

        review_id = base_id
        index = 2
        while review_id in existing_ids:
            review_id = f"{base_id}-{index}"
            index += 1
        return review_id

    @staticmethod
    def _initial_final_draft(item: Dict[str, Any]) -> str:
        flat_draft = ReviewQueue._clean_text(
            str(item.get("final_draft") or item.get("draft_text") or "")
        )
        if flat_draft:
            return flat_draft

        if isinstance(item.get("draft"), str):
            draft_text = ReviewQueue._clean_text(str(item.get("draft", "")))
            if draft_text:
                return draft_text

        compliance = item.get("compliance", {})
        draft = item.get("draft", {})

        if isinstance(compliance, dict):
            safe_draft = ReviewQueue._clean_text(str(compliance.get("safe_draft", "")))
            if safe_draft:
                return safe_draft

        if not isinstance(draft, dict):
            return ""

        main = ReviewQueue._clean_text(str(draft.get("draft", "")))
        cta = ReviewQueue._clean_text(str(draft.get("cta", "")))
        if main and cta and cta.lower() not in main.lower():
            return f"{main} {cta}"
        return main

    @staticmethod
    def _final_draft_for_action(
        record: Dict[str, Any],
        item: Dict[str, Any],
        review_status: str,
    ) -> str:
        if review_status == "edited":
            edited = ReviewQueue._clean_text(str(item.get("edited_draft", "")))
            if edited:
                return edited

        provided = ReviewQueue._clean_text(str(item.get("final_draft", "")))
        if provided:
            return provided

        existing = ReviewQueue._clean_text(str(record.get("final_draft", "")))
        if existing:
            return existing

        existing_draft = ReviewQueue._clean_text(str(record.get("draft", "")))
        if existing_draft:
            return existing_draft

        if review_status == "rejected":
            return "Draft rejected for revision before any publishing step."

        return ReviewQueue._initial_final_draft(record)

    @staticmethod
    def _status_to_action(review_status: str) -> str:
        reverse_map = {value: key for key, value in _ACTION_TO_STATUS.items()}
        return reverse_map.get(review_status, review_status)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _clean_text(text: str) -> str:
        return " ".join(str(text).split()).strip()

    @staticmethod
    def _resolve_supabase_preference(
        *,
        explicit_queue_path: bool,
        use_supabase: Optional[bool],
    ) -> bool:
        if use_supabase is not None:
            return bool(use_supabase)

        backend = os.environ.get("SIGNALFORGE_REVIEW_QUEUE_BACKEND", "").strip().lower()
        if backend in {"supabase", "remote"}:
            return True
        if backend in {"json", "local", "file"}:
            return False

        # A caller-provided path is an explicit request for an isolated JSON
        # queue.  This keeps tests, API-local queues, and temporary queues from
        # accidentally reading a globally configured Supabase table.
        return not explicit_queue_path

    @staticmethod
    def _is_valid_item(item: Any) -> bool:
        if not isinstance(item, dict):
            return False

        normalized = serialize_opportunity(item, can_mutate=True)
        return bool(
            normalized.get("title")
            and normalized.get("url")
            and ReviewQueue._initial_final_draft(item)
        )

    def __repr__(self) -> str:
        return f"<ReviewQueue path='{self._queue_path}'>"
