"""
SignalForge -- REST API.

FastAPI application that wraps the existing SignalForge pipeline,
exposing review-queue management, pipeline execution, and metrics
via a lightweight JSON API.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from utils.url_validator import validate_and_clean

# -- Ensure project root is on sys.path --------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from workflows.review_queue import ReviewQueue  # noqa: E402
from run_signalforge import run_pipeline          # noqa: E402

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
    allow_origins=["*"],
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


def _get_queue() -> ReviewQueue:
    """Return a fresh ReviewQueue instance (reads latest data on each call)."""
    return ReviewQueue(queue_path=str(_queue_path))


# ======================================================================
# Request / Response models
# ======================================================================

class StatusUpdate(BaseModel):
    status: str  # "posted" | "skipped" | "copied"


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
    opp = record.get("opportunity", {})
    draft_obj = record.get("draft", {})
    intent_obj = record.get("intent", {})
    score_obj = record.get("score", {})
    knowledge_obj = record.get("knowledge", {})

    # Flatten draft text
    draft_text = record.get("final_draft", "")
    if isinstance(draft_obj, dict):
        draft_text = draft_text or draft_obj.get("draft", "")
    elif isinstance(draft_obj, str) and not draft_text:
        draft_text = draft_obj

    # Flatten intent label
    intent_label = ""
    confidence_value = 0
    if isinstance(intent_obj, dict):
        intent_label = intent_obj.get("intent", "")
        try:
            raw_confidence = float(intent_obj.get("confidence", 0))
            confidence_value = int(raw_confidence * 100 if raw_confidence <= 1 else raw_confidence)
        except (ValueError, TypeError):
            confidence_value = 0

    # Flatten score
    score_value = 0
    if isinstance(score_obj, dict):
        try:
            score_value = int(score_obj.get("priority_score", 0))
        except (ValueError, TypeError):
            pass

    # Clean and validate URL
    raw_url = opp.get("url", opp.get("link", ""))
    platform = opp.get("platform", "unknown")
    cleaned_url, url_valid = validate_and_clean(raw_url, platform)
    source = (
        opp.get("source")
        or (f"r/{opp.get('subreddit')}" if opp.get("subreddit") else "")
        or opp.get("topic")
        or opp.get("author")
        or ""
    )
    summary = ""
    if isinstance(knowledge_obj, dict):
        summary = knowledge_obj.get("summary", "")
    summary = record.get("summary", "") or opp.get("summary", "") or summary or opp.get("body", "")

    return {
        "id": record.get("review_id", ""),
        "platform": platform,
        "title": opp.get("title", opp.get("query", "")),
        "url": cleaned_url,
        "url_valid": url_valid,
        "draft": draft_text,
        "intent": intent_label,
        "score": score_value,
        "confidence": confidence_value,
        "approval_mode": record.get("review_status", "pending"),
        "status": record.get("review_status", record.get("status", "pending")),
        "source": source,
        "summary": summary,
        "created_at": record.get("created_at", ""),
    }


@app.get("/items/pending")
def list_pending_items():
    queue = _get_queue()
    all_items = queue.items

    # Filter to pending + approved
    filtered = [
        item for item in all_items
        if (item.get("review_status") or item.get("status") or "").lower()
        in ("pending", "approved")
    ]

    # Group by platform
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in filtered:
        summary = _item_summary(item)
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
            summary = _item_summary(record)
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
    allowed = {"posted", "skipped", "copied"}
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

    record["review_status"] = body.status
    record["status"] = body.status
    queue._save_store(store)

    return _item_summary(record)


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

    record["final_draft"] = body.draft
    # Also update the nested draft dict for consistency
    if isinstance(record.get("draft"), dict):
        record["draft"]["draft"] = body.draft
    queue._save_store(store)

    return _item_summary(record)


# ======================================================================
# POST /pipeline/run
# ======================================================================

def _run_pipeline_background(query: str) -> None:
    global _pipeline_running, _pipeline_last_run, _pipeline_last_query
    global _pipeline_current_stage, _pipeline_items_found

    def _progress_cb(stage: str, items_found: int):
        global _pipeline_current_stage, _pipeline_items_found
        with _pipeline_lock:
            _pipeline_current_stage = stage
            _pipeline_items_found = items_found

    try:
        run_pipeline(query, live=True, progress_callback=_progress_cb)
    finally:
        with _pipeline_lock:
            _pipeline_running = False
            _pipeline_current_stage = None
            _pipeline_items_found = 0
            _pipeline_last_run = (
                datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            )
            _pipeline_last_query = query


@app.post("/pipeline/run")
def trigger_pipeline(body: PipelineRunRequest):
    global _pipeline_running, _pipeline_last_query

    with _pipeline_lock:
        if _pipeline_running:
            raise HTTPException(
                status_code=409,
                detail="Pipeline is already running.",
            )
        _pipeline_running = True
        _pipeline_last_query = body.query

    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(body.query,),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "query": body.query}


# ======================================================================
# GET /pipeline/status
# ======================================================================

@app.get("/pipeline/status")
def pipeline_status():
    with _pipeline_lock:
        return {
            "running": _pipeline_running,
            "last_run": _pipeline_last_run,
            "last_query": _pipeline_last_query,
            "current_stage": _pipeline_current_stage,
            "items_found_so_far": _pipeline_items_found,
        }


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
        platform = (item.get("opportunity", {}).get("platform", "unknown")).lower()
        created = item.get("created_at", "")

        # Count pending
        if status in ("pending", "approved"):
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
