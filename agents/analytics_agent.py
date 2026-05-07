"""
SignalForge Phase 18 — Analytics Agent.

Tracks human review outcomes and publisher results using the same nested
payload shapes as ``ReviewQueue`` records and ``PublisherRouter.publish``
return dicts. Aggregates rates, platform mix, intents, and sources without
changing the review queue or publisher modules.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("signalforge.analytics")

_REVIEW_OUTCOME_STATUSES = frozenset({"approved", "rejected", "edited"})


class AnalyticsAgent:
    """
    In-memory analytics with optional persistence to ``outputs/analytics.json``.

    Review snapshots mirror queue record fields (``opportunity``, ``draft``,
    ``compliance``, ``intent``, ``score``, ``review_id``, ``review_status``).
    Publish rows store the exact ``publish_result`` dict from the publisher
    layer alongside the routed ``opportunity`` / ``draft`` context.
    """

    def __init__(self, output_path: Optional[str] = None) -> None:
        root = Path(__file__).resolve().parents[1]
        default = root / "outputs" / "analytics.json"
        self._output_path = Path(output_path) if output_path else default
        self._output_path.parent.mkdir(parents=True, exist_ok=True)

        self._review_events: List[Dict[str, Any]] = []
        self._publish_events: List[Dict[str, Any]] = []

        logger.info("AnalyticsAgent initialised - persist_path=%s", self._output_path)

    @property
    def review_events(self) -> List[Dict[str, Any]]:
        return deepcopy(self._review_events)

    @property
    def publish_events(self) -> List[Dict[str, Any]]:
        return deepcopy(self._publish_events)

    def track_review(self, item: Dict[str, Any], status: str) -> None:
        """Record a completed review outcome (approved / rejected / edited)."""
        if not isinstance(item, dict):
            raise TypeError(f"item must be a dict, got {type(item).__name__}")

        normalized = " ".join(str(status).split()).strip().lower()
        if normalized not in _REVIEW_OUTCOME_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_REVIEW_OUTCOME_STATUSES)}, got {status!r}"
            )

        event: Dict[str, Any] = {
            "review_status": normalized,
            "tracked_at": self._timestamp(),
            "review_id": self._clean_text(str(item.get("review_id", ""))),
            "opportunity": deepcopy(item.get("opportunity", {}))
            if isinstance(item.get("opportunity"), dict)
            else {},
            "draft": deepcopy(item.get("draft", {}))
            if isinstance(item.get("draft"), dict)
            else {},
            "compliance": deepcopy(item.get("compliance", {}))
            if isinstance(item.get("compliance"), dict)
            else {},
            "intent": deepcopy(item.get("intent", {}))
            if isinstance(item.get("intent"), dict)
            else {},
            "score": deepcopy(item.get("score", {}))
            if isinstance(item.get("score"), dict)
            else {},
        }
        self._review_events.append(event)
        logger.debug("track_review review_id=%s status=%s", event["review_id"], normalized)

    def track_publish(self, item: Dict[str, Any], publish_result: Dict[str, Any]) -> None:
        """Record a publish attempt using the publisher result dict verbatim."""
        if not isinstance(item, dict):
            raise TypeError(f"item must be a dict, got {type(item).__name__}")
        if not isinstance(publish_result, dict):
            raise TypeError(
                f"publish_result must be a dict, got {type(publish_result).__name__}"
            )

        required = ("success", "platform", "published_url", "status")
        missing = [key for key in required if key not in publish_result]
        if missing:
            raise ValueError(
                f"publish_result missing keys {missing}; expected publisher output shape."
            )

        event = {
            "tracked_at": self._timestamp(),
            "opportunity": deepcopy(item.get("opportunity", {}))
            if isinstance(item.get("opportunity"), dict)
            else {},
            "draft": deepcopy(item.get("draft", {}))
            if isinstance(item.get("draft"), dict)
            else {},
            "publish_result": deepcopy(publish_result),
        }
        self._publish_events.append(event)
        logger.debug(
            "track_publish success=%s platform=%s",
            publish_result.get("success"),
            publish_result.get("platform"),
        )

    def generate_report(self) -> Dict[str, Any]:
        """Compute aggregate analytics from tracked events."""
        review_counts = Counter(
            evt["review_status"]
            for evt in self._review_events
            if evt.get("review_status") in _REVIEW_OUTCOME_STATUSES
        )
        total_reviews = sum(review_counts.values())

        publish_success = sum(
            1
            for evt in self._publish_events
            if evt.get("publish_result", {}).get("success") is True
        )
        publish_failure = sum(
            1
            for evt in self._publish_events
            if evt.get("publish_result", {}).get("success") is not True
        )
        total_publishes = publish_success + publish_failure

        def _rate(numerator: int, denominator: int) -> float:
            if denominator <= 0:
                return 0.0
            return round(numerator / denominator, 6)

        platform_counter: Counter[str] = Counter()
        for evt in self._review_events:
            plat = self._platform_from_opportunity(evt.get("opportunity", {}))
            platform_counter[plat] += 1
        for evt in self._publish_events:
            res = evt.get("publish_result", {})
            plat = str(res.get("platform") or "unknown").lower().strip() or "unknown"
            platform_counter[plat] += 1

        intent_counter: Counter[str] = Counter()
        for evt in self._review_events:
            intent = evt.get("intent", {})
            if isinstance(intent, dict):
                label = str(intent.get("intent", "") or "unknown").strip() or "unknown"
                intent_counter[label] += 1

        source_counter: Counter[str] = Counter()
        for evt in self._review_events:
            src = self._source_from_opportunity(evt.get("opportunity", {}))
            source_counter[src] += 1
        for evt in self._publish_events:
            src = self._source_from_opportunity(evt.get("opportunity", {}))
            source_counter[src] += 1

        top_intents = [
            {"intent": intent, "count": count}
            for intent, count in intent_counter.most_common()
        ]
        top_sources = [
            {"source": source, "count": count}
            for source, count in source_counter.most_common()
        ]

        return {
            "review_outcomes": {
                "approved": review_counts.get("approved", 0),
                "rejected": review_counts.get("rejected", 0),
                "edited": review_counts.get("edited", 0),
            },
            "publish_outcomes": {
                "success": publish_success,
                "failure": publish_failure,
            },
            "rates": {
                "approval_rate": _rate(review_counts.get("approved", 0), total_reviews),
                "rejection_rate": _rate(review_counts.get("rejected", 0), total_reviews),
                "edit_rate": _rate(review_counts.get("edited", 0), total_reviews),
                "publish_success_rate": _rate(publish_success, total_publishes),
            },
            "platform_distribution": dict(platform_counter),
            "top_intents": top_intents,
            "top_sources": top_sources,
            "total_pipeline_volume": len(self._review_events) + len(self._publish_events),
        }

    def save_report(self) -> Path:
        """
        Persist tracked events and the latest aggregate report.

        Phase 25: when Supabase is configured and reachable, also upserts events
        into the `analytics_events` table. JSON persistence remains as a
        backward-compatible sink.
        """
        payload = {
            "updated_at": self._timestamp(),
            "report": self.generate_report(),
            "review_events": deepcopy(self._review_events),
            "publish_events": deepcopy(self._publish_events),
        }

        # Supabase (best-effort; never break local JSON usage)
        try:
            from storage.supabase_store import (  # noqa: PLC0415
                SupabaseTableStore,
                get_supabase_client_from_settings,
            )

            client = get_supabase_client_from_settings()
            if client.is_configured() and client.ping():
                store = SupabaseTableStore(
                    client=client,
                    table="analytics_events",
                    primary_key="event_id",
                )
                rows: List[Dict[str, Any]] = []
                for evt in self._review_events:
                    if isinstance(evt, dict):
                        eid = f"rev-{evt.get('review_id','')}-{evt.get('tracked_at','')}"
                        rows.append({
                            "event_id": eid,
                            "event_type": "review",
                            "tracked_at": evt.get("tracked_at", ""),
                            "record": evt,
                        })
                for evt in self._publish_events:
                    if isinstance(evt, dict):
                        plat = (evt.get("publish_result", {}) or {}).get("platform", "unknown")
                        eid = f"pub-{plat}-{evt.get('tracked_at','')}"
                        rows.append({
                            "event_id": eid,
                            "event_type": "publish",
                            "tracked_at": evt.get("tracked_at", ""),
                            "record": evt,
                        })
                if rows:
                    store.save(rows)
        except Exception:
            pass

        self._output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        logger.info("Analytics saved to %s", self._output_path)
        return self._output_path

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _clean_text(text: str) -> str:
        return " ".join(str(text).split()).strip()

    @staticmethod
    def _platform_from_opportunity(opportunity: Dict[str, Any]) -> str:
        if not isinstance(opportunity, dict):
            return "unknown"
        raw = opportunity.get("platform", "")
        if raw:
            return str(raw).lower().strip() or "unknown"
        raw = opportunity.get("source", "")
        if raw:
            return str(raw).lower().strip() or "unknown"
        return "unknown"

    @staticmethod
    def _source_from_opportunity(opportunity: Dict[str, Any]) -> str:
        if not isinstance(opportunity, dict):
            return "unknown"
        for key in ("source", "platform"):
            val = opportunity.get(key, "")
            if val:
                return str(val).lower().strip() or "unknown"
        return "unknown"


__all__ = ["AnalyticsAgent"]
