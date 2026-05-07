"""
SignalForge Phase 19 — Learning Loop.

Reads persisted analytics (``outputs/analytics.json``) and derives adaptive
recommendations compatible with ``ScoringConfig`` / ``OpportunityScoringAgent``
weight and threshold fields. Does not mutate scoring, drafting, analytics, or
publisher code — consumers may apply recommendations explicitly.
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional

from agents.scoring_agent import ScoringConfig

logger = logging.getLogger("signalforge.learning")

DEFAULT_INTENT_WEIGHTS = ScoringConfig().intent_weights
DEFAULT_HOT = ScoringConfig().hot_threshold
DEFAULT_WARM = ScoringConfig().warm_threshold
DEFAULT_COLD = ScoringConfig().cold_threshold

_MIN_INTENT_SAMPLES = 3
_MIN_PLATFORM_SAMPLES = 3
_WEIGHT_DELTA_CAP = 6.0
_THRESHOLD_DELTA_CAP = 8.0


class LearningAgent:
    """
    Load analytics history, infer patterns, emit recommendations, persist state.

    Recommendations use structures that map cleanly onto ``ScoringConfig``:
    ``intent_weight_deltas`` adjust ``intent_weights``; ``threshold_deltas``
    adjust ``hot_threshold`` / ``warm_threshold`` / ``cold_threshold``.
    """

    def __init__(
        self,
        analytics_path: Optional[str] = None,
        learning_state_path: Optional[str] = None,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        self._analytics_path = Path(analytics_path) if analytics_path else root / "outputs" / "analytics.json"
        self._learning_state_path = (
            Path(learning_state_path)
            if learning_state_path
            else root / "outputs" / "learning_state.json"
        )
        self._learning_state_path.parent.mkdir(parents=True, exist_ok=True)

        self._payload: Optional[Dict[str, Any]] = None
        self._patterns: Dict[str, Any] = {}
        self._recommendations: Optional[Dict[str, Any]] = None

        logger.info(
            "LearningAgent initialised analytics=%s learning_state=%s",
            self._analytics_path,
            self._learning_state_path,
        )

    def load_analytics(self) -> Dict[str, Any]:
        """Load ``analytics.json`` produced by ``AnalyticsAgent.save_report``."""
        if not self._analytics_path.is_file():
            self._payload = {}
            logger.warning("Analytics file not found: %s", self._analytics_path)
            return deepcopy(self._payload)

        try:
            raw = json.loads(self._analytics_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid analytics JSON: {self._analytics_path}") from exc

        if not isinstance(raw, dict):
            raise ValueError("Analytics root must be an object")

        self._payload = raw
        return deepcopy(self._payload)

    def learn(self) -> Dict[str, Any]:
        """
        Compute pattern summaries from loaded analytics (loads file if needed).
        """
        if self._payload is None:
            self.load_analytics()

        review_events = (self._payload or {}).get("review_events", [])
        publish_events = (self._payload or {}).get("publish_events", [])
        report = (self._payload or {}).get("report", {})

        if not isinstance(review_events, list):
            review_events = []
        if not isinstance(publish_events, list):
            publish_events = []
        if not isinstance(report, dict):
            report = {}

        patterns = {
            "intent_performance": self._intent_performance(review_events, publish_events),
            "platform_performance": self._platform_performance(review_events, publish_events),
            "source_performance": self._source_performance(review_events, publish_events),
            "score_quality": self._score_quality(review_events),
            "drafting_edit_patterns": self._drafting_edit_patterns(review_events),
            "aggregate_report": report,
            "counts": {
                "review_events": len(review_events),
                "publish_events": len(publish_events),
            },
        }
        self._patterns = patterns
        return deepcopy(patterns)

    def generate_recommendations(self) -> Dict[str, Any]:
        """
        Build the Phase 19 recommendation object (includes ``confidence``).
        Call :meth:`learn` first if patterns are empty.
        """
        if not self._patterns:
            self.learn()

        confidence = self._compute_confidence()
        score_adj = self._recommend_score_adjustments()
        platform_adj = self._recommend_platform_priorities()
        intent_adj = self._recommend_intent_priorities()
        drafting = self._recommend_drafting_insights()

        rec = {
            "score_weight_adjustments": score_adj,
            "platform_priority_adjustments": platform_adj,
            "intent_priority_adjustments": intent_adj,
            "drafting_insights": drafting,
            "confidence": confidence,
        }
        self._recommendations = rec
        return deepcopy(rec)

    def save_learning_state(self) -> Path:
        """
        Persist recommendations and metadata.

        Phase 25: when Supabase is configured and reachable, also upserts the
        latest learning state into the `learning_state` table. JSON persistence
        remains for backward compatibility.
        """
        if self._recommendations is None:
            self.generate_recommendations()

        out = {
            "updated_at": self._timestamp(),
            **deepcopy(self._recommendations or {}),
            "patterns_summary": {
                k: self._patterns.get(k)
                for k in (
                    "intent_performance",
                    "platform_performance",
                    "score_quality",
                    "counts",
                )
                if k in self._patterns
            },
        }

        # Supabase best-effort
        try:
            from storage.supabase_store import (  # noqa: PLC0415
                SupabaseTableStore,
                get_supabase_client_from_settings,
            )

            client = get_supabase_client_from_settings()
            if client.is_configured() and client.ping():
                store = SupabaseTableStore(client=client, table="learning_state", primary_key="id")
                store.save([{"id": "latest", "updated_at": out["updated_at"], "record": out}])
        except Exception:
            pass

        self._learning_state_path.write_text(
            json.dumps(out, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        logger.info("Learning state saved to %s", self._learning_state_path)
        return self._learning_state_path

    # ------------------------------------------------------------------ #
    # Pattern extraction
    # ------------------------------------------------------------------ #

    def _intent_performance(
        self,
        review_events: List[Dict[str, Any]],
        publish_events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        per: DefaultDict[str, Counter[str]] = defaultdict(Counter)
        publish_by_intent: DefaultDict[str, Counter[str]] = defaultdict(Counter)

        for evt in review_events:
            intent = self._intent_label(evt.get("intent"))
            status = str(evt.get("review_status", "")).lower()
            if status:
                per[intent][status] += 1

        for evt in publish_events:
            intent = self._intent_label_from_opportunity(evt.get("opportunity", {}))
            ok = evt.get("publish_result", {}).get("success") is True
            publish_by_intent[intent]["success" if ok else "failure"] += 1

        out: Dict[str, Any] = {}
        for intent, ctr in per.items():
            total = sum(ctr.values())
            approved = ctr.get("approved", 0)
            out[intent] = {
                "reviews": dict(ctr),
                "review_total": total,
                "approval_rate": _safe_div(approved, total),
            }

        for intent, ctr in publish_by_intent.items():
            if intent not in out:
                out[intent] = {"reviews": {}, "review_total": 0, "approval_rate": 0.0}
            tot_pub = sum(ctr.values())
            out[intent]["publish_total"] = tot_pub
            out[intent]["publish_success_rate"] = _safe_div(
                ctr.get("success", 0), tot_pub
            )

        return out

    def _platform_performance(
        self,
        review_events: List[Dict[str, Any]],
        publish_events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        per: DefaultDict[str, Counter[str]] = defaultdict(Counter)
        pub: DefaultDict[str, Counter[str]] = defaultdict(Counter)

        for evt in review_events:
            plat = _platform_key(evt.get("opportunity", {}))
            status = str(evt.get("review_status", "")).lower()
            if status:
                per[plat][status] += 1

        for evt in publish_events:
            plat = str(
                evt.get("publish_result", {}).get("platform") or "unknown"
            ).lower()
            ok = evt.get("publish_result", {}).get("success") is True
            pub[plat]["success" if ok else "failure"] += 1

        out: Dict[str, Any] = {}
        all_platforms = set(per.keys()) | set(pub.keys())
        for plat in all_platforms:
            ctr = per.get(plat, Counter())
            total_r = sum(ctr.values())
            approved = ctr.get("approved", 0)
            pctr = pub.get(plat, Counter())
            total_p = sum(pctr.values())
            out[plat] = {
                "review_outcomes": dict(ctr),
                "review_total": total_r,
                "approval_rate": _safe_div(approved, total_r),
                "publish_outcomes": dict(pctr),
                "publish_total": total_p,
                "publish_success_rate": _safe_div(pctr.get("success", 0), total_p),
            }
        return out

    def _source_performance(
        self,
        review_events: List[Dict[str, Any]],
        publish_events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        per: DefaultDict[str, Counter[str]] = defaultdict(Counter)
        pub: DefaultDict[str, Counter[str]] = defaultdict(Counter)

        for evt in review_events:
            src = _source_key(evt.get("opportunity", {}))
            status = str(evt.get("review_status", "")).lower()
            if status:
                per[src][status] += 1

        for evt in publish_events:
            src = _source_key(evt.get("opportunity", {}))
            ok = evt.get("publish_result", {}).get("success") is True
            pub[src]["success" if ok else "failure"] += 1

        out: Dict[str, Any] = {}
        for src in set(per.keys()) | set(pub.keys()):
            ctr = per.get(src, Counter())
            total_r = sum(ctr.values())
            pctr = pub.get(src, Counter())
            total_p = sum(pctr.values())
            out[src] = {
                "review_outcomes": dict(ctr),
                "review_total": total_r,
                "approval_rate": _safe_div(ctr.get("approved", 0), total_r),
                "publish_outcomes": dict(pctr),
                "publish_total": total_p,
                "publish_success_rate": _safe_div(pctr.get("success", 0), total_p),
            }
        return out

    def _score_quality(self, review_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        buckets: DefaultDict[str, Counter[str]] = defaultdict(Counter)
        scores_approved: List[float] = []
        scores_rejected: List[float] = []

        for evt in review_events:
            status = str(evt.get("review_status", "")).lower()
            score_obj = evt.get("score", {})
            if not isinstance(score_obj, dict):
                continue
            ps = score_obj.get("priority_score")
            try:
                val = float(ps)
            except (TypeError, ValueError):
                continue
            label = str(score_obj.get("priority_label", "")).lower() or _bucket_by_thresholds(
                val, DEFAULT_HOT, DEFAULT_WARM, DEFAULT_COLD
            )
            buckets[label][status] += 1
            if status == "approved":
                scores_approved.append(val)
            elif status == "rejected":
                scores_rejected.append(val)

        global_median = _median(
            [float(e.get("score", {}).get("priority_score", 0)) for e in review_events
             if isinstance(e.get("score"), dict) and _is_number(e.get("score", {}).get("priority_score"))]
        )

        low_score_approved = sum(
            1
            for evt in review_events
            if str(evt.get("review_status", "")).lower() == "approved"
            and isinstance(evt.get("score"), dict)
            and _is_number(evt["score"].get("priority_score"))
            and float(evt["score"]["priority_score"]) < global_median
        )
        low_score_total = sum(
            1
            for evt in review_events
            if str(evt.get("review_status", "")).lower() == "approved"
            and isinstance(evt.get("score"), dict)
            and _is_number(evt["score"].get("priority_score"))
        )

        return {
            "by_priority_label": {k: dict(v) for k, v in buckets.items()},
            "median_priority_score": global_median,
            "approved_score_median": _median(scores_approved),
            "rejected_score_median": _median(scores_rejected),
            "low_score_approval_share": _safe_div(low_score_approved, low_score_total),
        }

    def _drafting_edit_patterns(self, review_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        edited: List[Dict[str, Any]] = []
        approved: List[Dict[str, Any]] = []

        for evt in review_events:
            status = str(evt.get("review_status", "")).lower()
            if status == "edited":
                edited.append(evt)
            elif status == "approved":
                approved.append(evt)

        def _stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
            wcs: List[int] = []
            tones: Counter[str] = Counter()
            cta_yes = 0
            for evt in rows:
                d = evt.get("draft", {})
                if not isinstance(d, dict):
                    continue
                text = str(d.get("draft", ""))
                wcs.append(len(text.split()))
                tone = str(d.get("tone", "") or "unknown").lower()
                tones[tone] += 1
                if str(d.get("cta", "")).strip():
                    cta_yes += 1
            n = len(rows)
            return {
                "count": n,
                "avg_word_count": round(_mean(wcs), 2) if wcs else 0.0,
                "tone_distribution": dict(tones),
                "cta_present_rate": _safe_div(cta_yes, n) if n else 0.0,
            }

        edited_s = _stats(edited)
        approved_s = _stats(approved)

        patterns: List[str] = []
        if edited_s["count"] and approved_s["count"]:
            if edited_s["avg_word_count"] + 5 < approved_s["avg_word_count"]:
                patterns.append(
                    "Edited drafts tend to shorten replies vs approved-as-is drafts; "
                    "bias toward tighter copy in generation."
                )
            elif edited_s["avg_word_count"] > approved_s["avg_word_count"] + 5:
                patterns.append(
                    "Editors often expand drafts; consider richer detail in first pass."
                )

        return {
            "edited_draft_stats": edited_s,
            "approved_draft_stats": approved_s,
            "inferred_patterns": patterns,
            "note": (
                "Analytics events store pre-review ``draft`` only; "
                "final human text after edit is not in analytics.json."
            ),
        }

    # ------------------------------------------------------------------ #
    # Recommendations
    # ------------------------------------------------------------------ #

    def _recommend_score_adjustments(self) -> Dict[str, Any]:
        perf = self._patterns.get("intent_performance", {})
        score_q = self._patterns.get("score_quality", {})

        intent_deltas: Dict[str, float] = {}
        rationale: List[str] = []

        global_approval = _global_review_approval_rate(
            (self._payload or {}).get("review_events", [])
        )

        for intent, row in perf.items():
            if intent == "unknown":
                continue
            n = int(row.get("review_total", 0))
            if n < _MIN_INTENT_SAMPLES:
                continue
            rate = float(row.get("approval_rate", 0.0))
            pub_n = int(row.get("publish_total", 0))
            pub_ok = float(row.get("publish_success_rate", 0.0))

            delta = 0.0
            publish_supports_boost = pub_n == 0 or (pub_n >= 2 and pub_ok >= 0.55)
            publish_supports_cut = pub_n == 0 or (pub_n >= 2 and pub_ok <= 0.45)

            if rate >= global_approval + 0.12 and publish_supports_boost:
                delta = min(_WEIGHT_DELTA_CAP, 3.0 + (rate - global_approval) * 10.0)
                rationale.append(
                    f"Intent '{intent}' shows strong approval ({rate:.2f}); "
                    f"bump intent weight (publish data {'neutral' if pub_n == 0 else 'supportive'})."
                )
            elif rate <= global_approval - 0.12 and n >= _MIN_INTENT_SAMPLES and publish_supports_cut:
                delta = -min(_WEIGHT_DELTA_CAP, 3.0 + (global_approval - rate) * 10.0)
                rationale.append(
                    f"Intent '{intent}' underperforms on approval ({rate:.2f}); reduce weight."
                )

            if intent in DEFAULT_INTENT_WEIGHTS and delta != 0.0:
                intent_deltas[intent] = round(delta, 3)

        threshold_deltas: Dict[str, float] = {}
        low_share = float(score_q.get("low_score_approval_share", 0.0))
        if low_share >= 0.55 and score_q.get("median_priority_score", 0) > 0:
            thr = min(5.0, max(1.0, (low_share - 0.5) * 20.0))
            threshold_deltas["warm_threshold"] = -round(thr, 3)
            threshold_deltas["cold_threshold"] = -round(thr, 3)
            rationale.append(
                "Many approvals carry below-median model scores; relax warm/cold thresholds slightly."
            )

        appr_med = score_q.get("approved_score_median")
        rej_med = score_q.get("rejected_score_median")
        if (
            isinstance(appr_med, (int, float))
            and isinstance(rej_med, (int, float))
            and rej_med > float(appr_med) + 10.0
        ):
            rationale.append(
                "Rejections skew higher-scored than approvals; review scoring features or "
                "human criteria before raising weights."
            )

        return {
            "intent_weight_deltas": intent_deltas,
            "threshold_deltas": threshold_deltas,
            "baseline_reference": {
                "default_intent_weights": dict(DEFAULT_INTENT_WEIGHTS),
                "default_hot_threshold": DEFAULT_HOT,
                "default_warm_threshold": DEFAULT_WARM,
                "default_cold_threshold": DEFAULT_COLD,
            },
            "application_notes": (
                "Merge intent_weight_deltas into ScoringConfig.intent_weights. "
                "Add threshold_deltas to hot/warm/cold thresholds (clamp 0-100). "
                "OpportunityScoringAgent itself is unchanged — apply in your runner."
            ),
            "rationale": rationale,
        }

    def _recommend_platform_priorities(self) -> Dict[str, Any]:
        plat = self._patterns.get("platform_performance", {})
        multipliers: Dict[str, float] = {}
        rationale: List[str] = []

        pub_rates = [
            (p, float(row.get("publish_success_rate", 0.0)), int(row.get("publish_total", 0)))
            for p, row in plat.items()
        ]
        avg_pub = (
            sum(r for _, r, n in pub_rates if n > 0) / max(1, sum(1 for _, _, n in pub_rates if n > 0))
        )

        for p, row in plat.items():
            n_rev = int(row.get("review_total", 0))
            n_pub = int(row.get("publish_total", 0))
            appr = float(row.get("approval_rate", 0.0))
            ps = float(row.get("publish_success_rate", 0.0))

            mult = 1.0
            if n_pub >= _MIN_PLATFORM_SAMPLES and ps >= avg_pub + 0.15:
                mult += min(0.25, (ps - avg_pub))
                rationale.append(f"Platform '{p}' publish success strong ({ps:.2f}); prioritise.")
            elif n_pub >= _MIN_PLATFORM_SAMPLES and ps <= avg_pub - 0.15:
                mult -= min(0.2, (avg_pub - ps))
                rationale.append(f"Platform '{p}' publish success weak ({ps:.2f}); deprioritise.")

            if n_rev >= _MIN_PLATFORM_SAMPLES and appr >= 0.75:
                mult += 0.05
            elif n_rev >= _MIN_PLATFORM_SAMPLES and appr <= 0.35:
                mult -= 0.05

            mult = max(0.5, min(1.5, round(mult, 3)))
            if mult != 1.0:
                multipliers[p] = mult

        return {
            "platform_multipliers": multipliers,
            "rationale": rationale,
            "application_notes": (
                "Use multipliers to rank or schedule opportunities post-score; "
                "not applied inside OpportunityScoringAgent by default."
            ),
        }

    def _recommend_intent_priorities(self) -> Dict[str, Any]:
        perf = self._patterns.get("intent_performance", {})
        multipliers: Dict[str, float] = {}
        rationale: List[str] = []

        approvals = [
            (i, float(row.get("approval_rate", 0.0)), int(row.get("review_total", 0)))
            for i, row in perf.items()
            if i != "unknown"
        ]
        mean_appr = (
            sum(r for _, r, n in approvals if n > 0) / max(1, sum(1 for _, _, n in approvals if n > 0))
        )

        for intent, row in perf.items():
            if intent == "unknown":
                continue
            n = int(row.get("review_total", 0))
            if n < _MIN_INTENT_SAMPLES:
                continue
            rate = float(row.get("approval_rate", 0.0))
            pub_rate = float(row.get("publish_success_rate", 0.0))
            pub_n = int(row.get("publish_total", 0))

            mult = 1.0
            if rate >= mean_appr + 0.1:
                mult += min(0.2, (rate - mean_appr) * 0.5)
                rationale.append(f"Intent '{intent}' approval above mean ({rate:.2f}); raise priority.")
            elif rate <= mean_appr - 0.1:
                mult -= min(0.2, (mean_appr - rate) * 0.5)
                rationale.append(f"Intent '{intent}' approval below mean ({rate:.2f}); lower priority.")

            if pub_n >= 2 and pub_rate >= 0.75:
                mult += 0.05

            mult = max(0.55, min(1.45, round(mult, 3)))
            if mult != 1.0:
                multipliers[intent] = mult

        return {
            "intent_multipliers": multipliers,
            "rationale": rationale,
            "application_notes": (
                "Combine with score_weight_adjustments: weights change the model, "
                "multipliers help ordering and capacity allocation."
            ),
        }

    def _recommend_drafting_insights(self) -> Dict[str, Any]:
        base = self._patterns.get("drafting_edit_patterns", {})
        return {
            "edited_vs_approved": {
                "edited": base.get("edited_draft_stats", {}),
                "approved": base.get("approved_draft_stats", {}),
            },
            "inferred_patterns": base.get("inferred_patterns", []),
            "note": base.get("note", ""),
        }

    def _compute_confidence(self) -> float:
        payload = self._payload or {}
        review_events = payload.get("review_events", [])
        publish_events = payload.get("publish_events", [])
        if not isinstance(review_events, list):
            review_events = []
        if not isinstance(publish_events, list):
            publish_events = []

        n_rev = len(review_events)
        n_pub = len(publish_events)
        n_total = n_rev + n_pub

        size_factor = min(1.0, n_total / 24.0) if n_total else 0.0

        status_counts = Counter(
            str(e.get("review_status", "")).lower()
            for e in review_events
            if str(e.get("review_status", "")).lower() in ("approved", "rejected", "edited")
        )
        if status_counts:
            consistency = 1.0 - _normalized_entropy(status_counts)
        elif n_pub > 0:
            pub_counts = Counter(
                "success" if e.get("publish_result", {}).get("success") is True else "failure"
                for e in publish_events
            )
            consistency = 1.0 - _normalized_entropy(pub_counts)
        else:
            consistency = 0.0

        conf = 0.55 * size_factor + 0.45 * consistency
        return round(max(0.0, min(1.0, conf)), 4)

    @staticmethod
    def _intent_label(intent_obj: Any) -> str:
        if isinstance(intent_obj, dict):
            lab = str(intent_obj.get("intent", "") or "").strip().lower()
            return lab or "unknown"
        return "unknown"

    @staticmethod
    def _intent_label_from_opportunity(opportunity: Any) -> str:
        if isinstance(opportunity, dict) and isinstance(opportunity.get("intent"), dict):
            lab = str(opportunity["intent"].get("intent", "") or "").strip().lower()
            if lab:
                return lab
        return "unknown"

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _platform_key(opportunity: Dict[str, Any]) -> str:
    if not isinstance(opportunity, dict):
        return "unknown"
    for key in ("platform", "source"):
        val = opportunity.get(key, "")
        if val:
            return str(val).lower().strip() or "unknown"
    return "unknown"


def _source_key(opportunity: Dict[str, Any]) -> str:
    return _platform_key(opportunity)


def _safe_div(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return round(num / den, 4)


def _is_number(x: Any) -> bool:
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    m = len(s) // 2
    if len(s) % 2:
        return float(s[m])
    return (float(s[m - 1]) + float(s[m])) / 2.0


def _mean(values: List[int]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _bucket_by_thresholds(score: float, hot: float, warm: float, cold: float) -> str:
    if score >= hot:
        return "hot"
    if score >= warm:
        return "warm"
    if score >= cold:
        return "cold"
    return "ignore"


def _normalized_entropy(counter: Counter) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    k = sum(1 for c in counter.values() if c > 0)
    if k <= 1:
        return 0.0
    h = 0.0
    for c in counter.values():
        if c <= 0:
            continue
        p = c / total
        h -= p * math.log(p + 1e-12, 2)
    max_h = math.log(k, 2)
    if max_h <= 0:
        return 0.0
    return min(1.0, h / max_h)


def _global_review_approval_rate(review_events: List[Dict[str, Any]]) -> float:
    ctr: Counter[str] = Counter()
    for evt in review_events:
        s = str(evt.get("review_status", "")).lower()
        if s in ("approved", "rejected", "edited"):
            ctr[s] += 1
    total = sum(ctr.values())
    return _safe_div(ctr.get("approved", 0), total)


__all__ = ["LearningAgent"]
