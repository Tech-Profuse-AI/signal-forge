"""API serialization helpers for the canonical SignalForge schema."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from schemas.opportunity import PipelineStatus, serialize_opportunity


def opportunity_response(item: Dict[str, Any], *, can_mutate: bool = False) -> Dict[str, Any]:
    """Serialize one item into the flat public opportunity shape."""

    return serialize_opportunity(item, can_mutate=can_mutate)


def opportunity_list_response(
    items: Iterable[Dict[str, Any]],
    *,
    can_mutate: bool = False,
) -> List[Dict[str, Any]]:
    """Serialize many items into the flat public opportunity shape."""

    out: List[Dict[str, Any]] = []
    for item in items:
        serialized = opportunity_response(item, can_mutate=can_mutate)
        if serialized.get("url") and serialized.get("url_valid") is True:
            out.append(serialized)
    return out


def pipeline_status_response(status: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize the pipeline status snapshot with normalized live objects."""

    partial_results: Dict[str, Any] = {}
    raw_partial = status.get("partial_results")
    if isinstance(raw_partial, dict):
        for platform, value in raw_partial.items():
            record = value if isinstance(value, dict) else {}
            items = record.get("items", [])
            if not isinstance(items, list):
                items = []
            partial_results[str(platform).lower()] = {
                "count": int(record.get("count", 0) or 0),
                "items": opportunity_list_response(items, can_mutate=False),
                "error": str(record.get("error") or ""),
                "elapsed_ms": record.get("elapsed_ms"),
            }

    live = []
    for item in status.get("live_opportunities", []):
        if not isinstance(item, dict):
            continue
        serialized = serialize_opportunity(item, can_mutate=False)
        if serialized.get("url") and serialized.get("url_valid") is True:
            live.append(serialized)
    out = PipelineStatus(
        running=bool(status.get("running", False)),
        last_run=str(status.get("last_run") or ""),
        last_query=str(status.get("last_query") or ""),
        current_stage=str(status.get("current_stage") or ""),
        items_found_so_far=int(status.get("items_found_so_far") or 0),
        partial_results=partial_results,
        live_opportunities=live,
        timings=status.get("timings") if isinstance(status.get("timings"), dict) else {},
    )
    if hasattr(out, "model_dump"):
        return out.model_dump()
    return out.dict()


__all__ = [
    "opportunity_response",
    "opportunity_list_response",
    "pipeline_status_response",
]
