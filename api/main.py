"""
SignalForge -- REST API.

FastAPI application that wraps the existing SignalForge pipeline,
exposing review-queue management, pipeline execution, and metrics
via a lightweight JSON API.
"""

from __future__ import annotations

import sys
import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# -- Ensure project root is on sys.path --------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from workflows.review_queue import ReviewQueue  # noqa: E402
from run_signalforge import run_pipeline          # noqa: E402
from api.serializers import (                       # noqa: E402
    opportunity_response,
    opportunity_list_response,
    pipeline_status_response,
)

logger = logging.getLogger("signalforge.api")


def _cors_allowed_origins() -> List[str]:
    values: List[str] = []
    raw_allowed = os.getenv("CORS_ALLOWED_ORIGINS", "")
    frontend_url = os.getenv("FRONTEND_URL", "")

    for raw in (raw_allowed, frontend_url):
        for origin in raw.split(","):
            cleaned = origin.strip().rstrip("/")
            if cleaned and cleaned not in values:
                values.append(cleaned)

    if not values:
        logger.warning(
            "CORS_ALLOWED_ORIGINS/FRONTEND_URL not set; allowing all origins."
        )
        return ["*"]

    return values

# ======================================================================
# App + CORS
# ======================================================================

app = FastAPI(
    title="SignalForge API",
    description="REST API for the SignalForge agentic pipeline.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================================================
# Shared state
# ======================================================================

_queue_path = PROJECT_ROOT / "outputs" / ".review_queue.json"

# Pipeline background-run state
_pipeline_lock = threading.Lock()
_pipeline_running = False
_pipeline_last_run: Optional[str] = None
_pipeline_last_query: Optional[str] = None
_pipeline_current_stage: Optional[str] = None
_pipeline_items_found: int = 0
_pipeline_partial_results: Dict[str, Dict[str, Any]] = {}
_pipeline_live_opportunities: Dict[str, Dict[str, Any]] = {}
_pipeline_timings: Dict[str, Any] = {}
_pipeline_event_condition = threading.Condition()
_pipeline_events: deque[Dict[str, Any]] = deque(maxlen=500)
_pipeline_event_seq = 0


def _get_queue() -> ReviewQueue:
    """Return a fresh ReviewQueue instance (reads latest data on each call)."""
    return ReviewQueue(queue_path=str(_queue_path))


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pipeline_status_snapshot_unlocked() -> Dict[str, Any]:
    return pipeline_status_response({
        "running": _pipeline_running,
        "last_run": _pipeline_last_run,
        "last_query": _pipeline_last_query,
        "current_stage": _pipeline_current_stage,
        "items_found_so_far": _pipeline_items_found,
        "partial_results": dict(_pipeline_partial_results),
        "live_opportunities": list(_pipeline_live_opportunities.values()),
        "timings": dict(_pipeline_timings),
    })


def _append_pipeline_event(event_type: str, payload: Dict[str, Any]) -> None:
    global _pipeline_event_seq
    with _pipeline_event_condition:
        _pipeline_event_seq += 1
        _pipeline_events.append({
            "id": _pipeline_event_seq,
            "type": event_type,
            "timestamp": _utc_timestamp(),
            "payload": payload,
        })
        _pipeline_event_condition.notify_all()


def _format_sse(event: Dict[str, Any]) -> str:
    event_type = str(event.get("type", "message"))
    event_id = str(event.get("id", ""))
    data = json.dumps(event, ensure_ascii=False, default=str)
    return f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"


def _pipeline_event_type(stage: str, payload: Optional[Dict[str, Any]]) -> str:
    event_name = payload.get("event") if isinstance(payload, dict) else ""
    if event_name == "opportunity_state":
        return "opportunity_state"
    if event_name == "platform_batch":
        return "platform_batch"
    if event_name == "pipeline_complete" or stage == "complete":
        return "pipeline_complete"
    if stage == "failed":
        return "pipeline_error"
    return "pipeline_status"


def _public_pipeline_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Normalize URL-bearing pipeline event payloads before SSE/API exposure."""
    if not isinstance(payload, dict):
        return payload

    event_name = payload.get("event")
    if event_name == "opportunity_state":
        serialized = opportunity_response(payload, can_mutate=False)
        out = {"event": "opportunity_state", **serialized}
        if payload.get("timings"):
            out["timings"] = payload["timings"]
        return out

    is_platform_batch = (
        payload.get("platform")
        and (event_name == "platform_batch" or "items" in payload)
    )
    if is_platform_batch:
        platform = str(payload.get("platform", "")).lower()
        items = payload.get("items", [])
        if not isinstance(items, list):
            items = []
        previews = opportunity_list_response(
            (
                {**item, "platform": item.get("platform", platform)}
                for item in items
                if isinstance(item, dict)
            ),
            can_mutate=False,
        )
        return {
            **payload,
            "event": "platform_batch",
            "platform": platform,
            "count": len(previews),
            "items": previews,
        }

    return dict(payload)


def _live_opportunity_key(payload: Dict[str, Any]) -> str:
    opportunity = payload.get("opportunity", {})
    if not isinstance(opportunity, dict):
        opportunity = payload
    platform = str(payload.get("platform") or opportunity.get("platform") or "unknown").lower()
    opportunity_id = str(
        payload.get("opportunity_id")
        or opportunity.get("opportunity_id")
        or opportunity.get("id")
        or ""
    ).strip()
    url = str(opportunity.get("url") or payload.get("url") or "").strip().lower()
    if opportunity_id:
        return f"{platform}:{opportunity_id}"
    if url:
        return f"url:{url}"
    return f"{platform}:{len(_pipeline_live_opportunities) + 1}"


def _source_from_opportunity(opportunity: Dict[str, Any]) -> str:
    return (
        opportunity.get("source")
        or (f"r/{opportunity.get('subreddit')}" if opportunity.get("subreddit") else "")
        or opportunity.get("topic")
        or opportunity.get("author")
        or ""
    )


def _merge_live_opportunity_unlocked(payload: Dict[str, Any]) -> None:
    opportunity = payload.get("opportunity", {})
    if not isinstance(opportunity, dict):
        opportunity = payload

    key = _live_opportunity_key(payload)
    pipeline_state = str(payload.get("pipeline_state") or opportunity.get("pipeline_state") or "").lower()
    if pipeline_state == "dropped":
        _pipeline_live_opportunities.pop(key, None)
        return

    existing = _pipeline_live_opportunities.get(key, {})
    now = _utc_timestamp()
    merged_payload = {
        **existing,
        **payload,
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
        "pipeline_state": pipeline_state,
        "status": "approved" if pipeline_state == "approved" else pipeline_state,
        "opportunity": {
            **opportunity,
            "source": _source_from_opportunity(opportunity) or existing.get("source", ""),
            "pipeline_state": pipeline_state,
        },
    }
    record = opportunity_response(merged_payload, can_mutate=False)
    if not record.get("url") or record.get("url_valid") is not True:
        _pipeline_live_opportunities.pop(key, None)
        logger.info(
            "Live URL gate dropped platform=%s id=%s",
            record.get("platform", "unknown"),
            record.get("id", ""),
        )
        return
    if payload.get("timings"):
        record["timings"] = payload["timings"]

    _pipeline_live_opportunities[key] = record


# ======================================================================
# Request / Response models
# ======================================================================

class StatusUpdate(BaseModel):
    status: str  # "approved" | "rejected" | "posted" | "skipped" | "copied"


class DraftUpdate(BaseModel):
    draft: str


class PipelineRunRequest(BaseModel):
    query: str


# ======================================================================
# GET /health
# ======================================================================

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


# ======================================================================
# GET /items/pending
# ======================================================================

def _item_summary(record: Dict[str, Any]) -> Dict[str, Any]:
    """Project a queue record into the public API shape."""
    summary = opportunity_response(record, can_mutate=True)
    if not summary.get("url") or summary.get("url_valid") is not True:
        logger.info(
            "API URL gate dropped item id=%s platform=%s",
            record.get("review_id") or record.get("id", ""),
            summary.get("platform", "unknown"),
        )
    return summary


def _require_item_summary(record: Dict[str, Any], item_id: str) -> Dict[str, Any]:
    summary = _item_summary(record)
    if not summary.get("url") or summary.get("url_valid") is not True:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' has no usable URL.")
    return summary


@app.get("/items/pending")
def list_pending_items():
    queue = _get_queue()
    all_items = queue.items

    # Filter to active publishing queue states.
    filtered = [
        item for item in all_items
        if (item.get("review_status") or item.get("status") or "").lower()
        in ("pending", "approved", "approved_for_posting", "copied")
    ]

    # Group by platform
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in filtered:
        summary = _item_summary(item)
        if not summary.get("url") or summary.get("url_valid") is not True:
            continue
        platform = summary["platform"]
        grouped.setdefault(platform, []).append(summary)

    # Return flat list (grouped info is encoded in each item's platform field)
    result: List[Dict[str, Any]] = []
    for platform_items in grouped.values():
        result.extend(platform_items)

    return result


# ======================================================================
# GET /items/{item_id}
# ======================================================================

@app.get("/items/{item_id}")
def get_item(item_id: str):
    queue = _get_queue()
    for record in queue.items:
        if record.get("review_id") == item_id:
            summary = _require_item_summary(record, item_id)
            # Include full draft text (final_draft takes precedence)
            final_draft = record.get("final_draft", "")
            if final_draft:
                summary["draft"] = final_draft
            return summary

    raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found.")


# ======================================================================
# PATCH /items/{item_id}/status
# ======================================================================

@app.patch("/items/{item_id}/status")
def update_item_status(item_id: str, body: StatusUpdate):
    allowed = {"approved", "rejected", "posted", "skipped", "copied"}
    if body.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Status must be one of: {', '.join(sorted(allowed))}",
        )

    queue = _get_queue()
    store = queue._load_store()
    record = queue._find_record(store["items"], item_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found.")
    _require_item_summary(record, item_id)

    now = _utc_timestamp()
    record["review_status"] = body.status
    record["status"] = body.status
    record["updated_at"] = now
    if body.status in {"approved", "rejected"}:
        record["reviewer_action"] = "approve" if body.status == "approved" else "reject"
        record["reviewed_at"] = now
    queue._save_store(store)

    return _require_item_summary(record, item_id)


# ======================================================================
# PATCH /items/{item_id}/draft
# ======================================================================

@app.patch("/items/{item_id}/draft")
def update_item_draft(item_id: str, body: DraftUpdate):
    queue = _get_queue()
    store = queue._load_store()
    record = queue._find_record(store["items"], item_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found.")
    _require_item_summary(record, item_id)

    record["final_draft"] = body.draft
    record["draft"] = body.draft
    # Also update the nested draft dict for consistency
    if isinstance(record.get("draft"), dict):
        record["draft"]["draft"] = body.draft
    queue._save_store(store)

    return _require_item_summary(record, item_id)


# ======================================================================
# POST /pipeline/run
# ======================================================================

def _run_pipeline_background(query: str) -> None:
    global _pipeline_running, _pipeline_last_run, _pipeline_last_query
    global _pipeline_current_stage, _pipeline_items_found
    global _pipeline_partial_results, _pipeline_timings

    def _progress_cb(stage: str, items_found: int, payload: Optional[Dict[str, Any]] = None):
        global _pipeline_current_stage, _pipeline_items_found, _pipeline_partial_results
        global _pipeline_timings
        event_payload: Dict[str, Any]
        public_payload = _public_pipeline_payload(payload)
        with _pipeline_lock:
            _pipeline_current_stage = stage
            if isinstance(public_payload, dict) and public_payload.get("event") == "opportunity_state":
                _merge_live_opportunity_unlocked(public_payload)
                _pipeline_items_found = max(
                    _pipeline_items_found,
                    len(_pipeline_live_opportunities),
                )
            else:
                _pipeline_items_found = max(_pipeline_items_found, items_found)

            if isinstance(public_payload, dict) and public_payload.get("timings"):
                _pipeline_timings = dict(public_payload.get("timings", {}))

            is_platform_batch = (
                isinstance(public_payload, dict)
                and public_payload.get("platform")
                and (public_payload.get("event") == "platform_batch" or "items" in public_payload)
            )
            if is_platform_batch:
                platform = str(public_payload.get("platform", "")).lower()
                items = public_payload.get("items", [])
                if isinstance(items, list):
                    previews = items[:5]
                else:
                    previews = []
                _pipeline_partial_results[platform] = {
                    "count": int(public_payload.get("count", 0) or 0),
                    "items": previews,
                    "error": public_payload.get("error", ""),
                    "elapsed_ms": public_payload.get("elapsed_ms"),
                }
            snapshot = _pipeline_status_snapshot_unlocked()

        event_payload = {
            "stage": stage,
            "items_found": items_found,
            "data": public_payload or {},
            "status": snapshot,
        }
        _append_pipeline_event(
            _pipeline_event_type(stage, public_payload),
            event_payload,
        )

    failed_error = ""
    try:
        run_pipeline(query, live=True, progress_callback=_progress_cb)
    except Exception as exc:
        failed_error = str(exc)
        logger.exception("Pipeline background run failed")
    finally:
        with _pipeline_lock:
            _pipeline_running = False
            _pipeline_current_stage = "failed" if failed_error else "complete"
            _pipeline_items_found = max(
                _pipeline_items_found,
                len(_pipeline_live_opportunities),
            )
            _pipeline_last_run = _utc_timestamp()
            _pipeline_last_query = query
            snapshot = _pipeline_status_snapshot_unlocked()

        event_type = "pipeline_error" if failed_error else "pipeline_complete"
        _append_pipeline_event(
            event_type,
            {
                "stage": _pipeline_current_stage,
                "items_found": _pipeline_items_found,
                "error": failed_error,
                "status": snapshot,
            },
        )


@app.post("/pipeline/run")
def trigger_pipeline(body: PipelineRunRequest):
    global _pipeline_running, _pipeline_last_query, _pipeline_partial_results
    global _pipeline_current_stage, _pipeline_items_found, _pipeline_timings

    with _pipeline_lock:
        if _pipeline_running:
            raise HTTPException(
                status_code=409,
                detail="Pipeline is already running.",
            )
        _pipeline_running = True
        _pipeline_last_query = body.query
        _pipeline_current_stage = "queued"
        _pipeline_items_found = 0
        _pipeline_partial_results = {}
        _pipeline_live_opportunities.clear()
        _pipeline_timings = {}
        snapshot = _pipeline_status_snapshot_unlocked()

    with _pipeline_event_condition:
        _pipeline_events.clear()

    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(body.query,),
        daemon=True,
    )
    thread.start()

    _append_pipeline_event(
        "pipeline_status",
        {
            "stage": "queued",
            "items_found": 0,
            "status": snapshot,
        },
    )

    return {"status": "started", "query": body.query}


# ======================================================================
# GET /pipeline/status
# ======================================================================

@app.get("/pipeline/status")
def pipeline_status():
    with _pipeline_lock:
        return _pipeline_status_snapshot_unlocked()


@app.get("/pipeline/events")
def pipeline_events():
    def event_stream():
        last_sent = 0
        with _pipeline_lock:
            initial_status = _pipeline_status_snapshot_unlocked()
        yield _format_sse({
            "id": 0,
            "type": "pipeline_status",
            "timestamp": _utc_timestamp(),
            "payload": {"status": initial_status},
        })

        while True:
            with _pipeline_event_condition:
                events = [
                    event for event in list(_pipeline_events)
                    if int(event.get("id", 0)) > last_sent
                ]
                if not events:
                    _pipeline_event_condition.wait(timeout=15)
                    events = [
                        event for event in list(_pipeline_events)
                        if int(event.get("id", 0)) > last_sent
                    ]

            if events:
                for event in events:
                    last_sent = int(event.get("id", last_sent))
                    yield _format_sse(event)
            else:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ======================================================================
# GET /metrics
# ======================================================================

@app.get("/metrics")
def metrics():
    queue = _get_queue()
    all_items = queue.items

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    total_pending = 0
    posted_today = 0
    skipped_today = 0
    by_platform: Dict[str, int] = {}

    for item in all_items:
        status = (item.get("review_status") or item.get("status") or "").lower()
        summary = opportunity_response(item, can_mutate=True)
        platform = summary.get("platform", "unknown").lower()
        created = item.get("created_at", "")

        # Count active queue items
        if status in ("pending", "approved", "approved_for_posting", "copied"):
            total_pending += 1

        # Count posted/skipped today
        if today_str in created:
            if status == "posted":
                posted_today += 1
            elif status == "skipped":
                skipped_today += 1

        # Aggregate by platform (all statuses)
        by_platform[platform] = by_platform.get(platform, 0) + 1

    return {
        "total_pending": total_pending,
        "posted_today": posted_today,
        "skipped_today": skipped_today,
        "by_platform": by_platform,
    }


# ======================================================================
# Uvicorn runner
# ======================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
