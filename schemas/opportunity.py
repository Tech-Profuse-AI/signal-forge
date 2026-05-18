"""Canonical SignalForge opportunity schema and serializers.

This module is the compatibility boundary for opportunity-shaped data.  It
accepts older nested pipeline records, scanner records, review queue rows, and
already-flat API objects, then emits the single flat shape consumed everywhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from pydantic import BaseModel, Field

from utils.url_validator import normalize_url


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _model_dump(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if _is_mapping(value) else {}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            cleaned = _clean_text(value)
            if cleaned:
                return cleaned
            continue
        if isinstance(value, (int, float, bool)):
            return str(value)
    return ""


def _to_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _to_score(value: Any, fallback: int = 0) -> int:
    return max(0, min(100, _to_int(value, fallback)))


def _to_percent(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if 0 < number <= 1:
        number *= 100
    return max(0, min(100, int(round(number))))


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _source_from(platform: str, record: Dict[str, Any], opportunity: Dict[str, Any]) -> str:
    source = _first_text(
        record.get("source"),
        record.get("community"),
        record.get("channel"),
        record.get("subreddit"),
        record.get("topic"),
        opportunity.get("source"),
        opportunity.get("community"),
        opportunity.get("channel"),
    )
    if source:
        return source

    subreddit = _first_text(record.get("subreddit"), opportunity.get("subreddit"))
    topic = _first_text(record.get("topic"), opportunity.get("topic"))
    author = _first_text(record.get("author"), opportunity.get("author"))
    if platform == "reddit" and subreddit:
        return f"r/{subreddit.replace('r/', '', 1)}"
    if platform == "quora":
        return topic or author
    if platform == "medium":
        return author
    return ""


def _draft_text(record: Dict[str, Any]) -> str:
    draft = record.get("draft")
    draft_obj = _as_dict(draft)
    compliance = _as_dict(record.get("compliance"))

    main = _first_text(
        record.get("final_draft"),
        record.get("draft_text"),
        record.get("safe_draft"),
        compliance.get("safe_draft"),
        draft if isinstance(draft, str) else "",
        draft_obj.get("draft"),
        draft_obj.get("body"),
        draft_obj.get("content"),
    )
    cta = _first_text(record.get("cta"), draft_obj.get("cta"))
    if main and cta and cta.lower() not in main.lower():
        return f"{main}\n\n{cta}"
    return main


def _score_value(record: Dict[str, Any], opportunity: Dict[str, Any]) -> int:
    score = record.get("score")
    score_obj = _as_dict(score)
    scoring_obj = _as_dict(opportunity.get("_scoring"))
    priority_candidate = _first_text(
        record.get("priority_score"),
        score_obj.get("priority_score"),
        scoring_obj.get("priority_score"),
        record.get("score_value"),
        opportunity.get("priority_score"),
    )
    if priority_candidate:
        return _to_score(priority_candidate, 0)

    if (
        "source_score" in record
        or record.get("review_id")
        or isinstance(record.get("draft"), str)
        or "final_draft" in record
    ):
        return _to_score(score if isinstance(score, (int, float, str)) else 0, 0)

    candidate = _first_text(
        score if isinstance(score, (int, float, str)) else "",
    )
    return _to_score(candidate if record is not opportunity else "", 0)


def _source_score(record: Dict[str, Any], opportunity: Dict[str, Any]) -> int:
    score = record.get("source_score")
    if score is not None:
        return _to_int(score, 0)

    raw_score = record.get("score")
    if isinstance(raw_score, Mapping):
        raw_score = opportunity.get("score", 0)
    return _to_int(raw_score if raw_score is not None else opportunity.get("score"), 0)


def _priority_label(record: Dict[str, Any], opportunity: Dict[str, Any]) -> str:
    score = _as_dict(record.get("score"))
    scoring = _as_dict(opportunity.get("_scoring"))
    return _first_text(
        record.get("priority_label"),
        record.get("score_label"),
        score.get("priority_label"),
        scoring.get("priority_label"),
    )


def _intent_label(record: Dict[str, Any]) -> str:
    intent = record.get("intent")
    intent_obj = _as_dict(intent)
    return _first_text(
        intent if isinstance(intent, str) else "",
        record.get("intent_label"),
        intent_obj.get("intent"),
        intent_obj.get("label"),
    )


def _confidence(record: Dict[str, Any]) -> int:
    intent = _as_dict(record.get("intent"))
    score = _as_dict(record.get("score"))
    return _to_percent(
        _first_text(
            record.get("confidence"),
            record.get("intent_confidence"),
            intent.get("confidence"),
            score.get("confidence"),
        )
    )


def _status(record: Dict[str, Any], opportunity: Dict[str, Any], override: Optional[str]) -> str:
    status = _first_text(
        override,
        record.get("status"),
        record.get("review_status"),
        record.get("approval_mode"),
        record.get("pipeline_state"),
        opportunity.get("pipeline_state"),
        record.get("review_state"),
    ).lower()
    return status or "pending"


def _pipeline_state(record: Dict[str, Any], opportunity: Dict[str, Any], override: Optional[str]) -> str:
    return _first_text(
        override,
        record.get("pipeline_state"),
        opportunity.get("pipeline_state"),
        record.get("state"),
    ).lower()


def _created_at(record: Dict[str, Any], opportunity: Dict[str, Any]) -> str:
    explicit = _first_text(
        record.get("created_at"),
        record.get("createdAt"),
        record.get("dequeued_at"),
        opportunity.get("created_at"),
        opportunity.get("published_at"),
    )
    if explicit:
        return explicit

    created_utc = _to_int(opportunity.get("created_utc"), 0)
    if created_utc > 0:
        return datetime.fromtimestamp(created_utc, tz=timezone.utc).replace(microsecond=0).isoformat()

    return _utc_timestamp()


class Opportunity(BaseModel):
    """The flat SignalForge opportunity object returned by every public boundary."""

    id: str = ""
    opportunity_id: str = ""
    review_id: str = ""
    platform: str = "unknown"
    title: str = ""
    url: str = ""
    url_valid: bool = False
    draft: str = ""
    score: int = 0
    status: str = "pending"

    priority_label: str = ""
    source_score: int = 0
    intent: str = ""
    confidence: int = 0
    source: str = ""
    summary: str = ""
    body: str = ""
    author: str = ""
    community: str = ""
    subreddit: str = ""
    topic: str = ""
    tags: List[str] = Field(default_factory=list)
    signals: List[str] = Field(default_factory=list)
    opportunity_signals: List[str] = Field(default_factory=list)

    created_at: str = ""
    updated_at: str = ""
    pipeline_state: str = ""
    review_state: str = ""
    tone: str = ""
    cta: str = ""
    reasoning: str = ""
    compliance_approved: bool = False
    risk_level: str = ""
    violations: List[str] = Field(default_factory=list)
    recommendation: str = ""
    can_mutate: bool = False


class PipelineStatus(BaseModel):
    """Flat pipeline status response with normalized live opportunities."""

    running: bool = False
    last_run: str = ""
    last_query: str = ""
    current_stage: str = ""
    items_found_so_far: int = 0
    partial_results: Dict[str, Any] = Field(default_factory=dict)
    live_opportunities: List[Opportunity] = Field(default_factory=list)
    timings: Dict[str, Any] = Field(default_factory=dict)


def normalize_opportunity(
    payload: Any,
    *,
    status: Optional[str] = None,
    pipeline_state: Optional[str] = None,
    can_mutate: Optional[bool] = None,
) -> Opportunity:
    """Return an :class:`Opportunity` from any known SignalForge payload."""

    record = _as_dict(payload)
    opportunity = _as_dict(record.get("opportunity"))
    if not opportunity:
        opportunity = record

    platform = _first_text(record.get("platform"), opportunity.get("platform")).lower() or "unknown"
    raw_url = _first_text(
        record.get("url"),
        record.get("thread_url"),
        record.get("question_url"),
        opportunity.get("url"),
        opportunity.get("link"),
        opportunity.get("thread_url"),
        opportunity.get("question_url"),
    )
    cleaned_url, url_valid = normalize_url(raw_url, platform)

    review_id = _first_text(record.get("review_id"))
    opportunity_id = _first_text(
        record.get("opportunity_id"),
        opportunity.get("id") if opportunity is not record else "",
        record.get("id") if not review_id else "",
    )
    canonical_id = _first_text(
        review_id,
        record.get("id"),
        opportunity_id,
        cleaned_url,
    )

    draft_obj = _as_dict(record.get("draft"))
    compliance = _as_dict(record.get("compliance"))
    body = _first_text(record.get("body"), opportunity.get("body"), opportunity.get("summary"))
    summary = _first_text(
        record.get("summary"),
        record.get("description"),
        _as_dict(record.get("knowledge")).get("summary"),
        opportunity.get("summary"),
        body,
    )

    subreddit = _first_text(record.get("subreddit"), opportunity.get("subreddit"))
    topic = _first_text(record.get("topic"), opportunity.get("topic"))
    community = _first_text(record.get("community"), opportunity.get("community"), subreddit, topic)
    now = _utc_timestamp()
    created_at = _created_at(record, opportunity)
    signals = [
        str(item)
        for item in _as_list(
            record.get("signals")
            or record.get("opportunity_signals")
            or opportunity.get("opportunity_signals")
        )
    ]
    normalized = Opportunity(
        id=canonical_id,
        opportunity_id=opportunity_id or canonical_id,
        review_id=review_id,
        platform=platform,
        title=_first_text(record.get("title"), opportunity.get("title"), opportunity.get("query")) or "Untitled opportunity",
        url=cleaned_url if url_valid else "",
        url_valid=bool(url_valid),
        draft=_draft_text(record),
        score=_score_value(record, opportunity),
        status=_status(record, opportunity, status),
        priority_label=_priority_label(record, opportunity),
        source_score=_source_score(record, opportunity),
        intent=_intent_label(record),
        confidence=_confidence(record),
        source=_source_from(platform, record, opportunity),
        summary=summary,
        body=body,
        author=_first_text(record.get("author"), opportunity.get("author")),
        community=community,
        subreddit=subreddit,
        topic=topic,
        tags=[str(item) for item in _as_list(record.get("tags") or opportunity.get("tags"))],
        signals=signals,
        opportunity_signals=signals,
        created_at=created_at,
        updated_at=_first_text(record.get("updated_at"), now),
        pipeline_state=_pipeline_state(record, opportunity, pipeline_state),
        review_state=_first_text(record.get("review_state")),
        tone=_first_text(record.get("tone"), draft_obj.get("tone")),
        cta=_first_text(record.get("cta"), draft_obj.get("cta")),
        reasoning=_first_text(record.get("reasoning"), draft_obj.get("reasoning")),
        compliance_approved=bool(record.get("compliance_approved", compliance.get("approved", False))),
        risk_level=_first_text(record.get("risk_level"), compliance.get("risk_level")),
        violations=[str(item) for item in _as_list(record.get("violations") or compliance.get("violations"))],
        recommendation=_first_text(record.get("recommendation"), compliance.get("recommendation")),
        can_mutate=bool(can_mutate) if can_mutate is not None else bool(review_id),
    )
    return normalized


def serialize_opportunity(
    payload: Any,
    *,
    status: Optional[str] = None,
    pipeline_state: Optional[str] = None,
    can_mutate: Optional[bool] = None,
) -> Dict[str, Any]:
    """Serialize any opportunity payload to the canonical flat dict."""

    return _model_dump(
        normalize_opportunity(
            payload,
            status=status,
            pipeline_state=pipeline_state,
            can_mutate=can_mutate,
        )
    )


def serialize_opportunity_list(
    payloads: Iterable[Any],
    *,
    status: Optional[str] = None,
    pipeline_state: Optional[str] = None,
    can_mutate: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    return [
        serialize_opportunity(
            item,
            status=status,
            pipeline_state=pipeline_state,
            can_mutate=can_mutate,
        )
        for item in payloads
    ]


__all__ = [
    "Opportunity",
    "PipelineStatus",
    "normalize_opportunity",
    "serialize_opportunity",
    "serialize_opportunity_list",
]
