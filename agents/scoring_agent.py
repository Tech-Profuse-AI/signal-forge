"""
SignalForge OpportunityScoringAgent -- Phase 4.

Prioritises classified opportunities by business value using a
weighted scoring formula across calibrated dimensions:

  1. Intent weight     -- how valuable is this intent type?
  2. Confidence mult   -- how confident was the LLM classification?
  3. Engagement weight  -- platform-normalised community validation
  4. Signal boost      -- bonus for high-value opportunity signals
  5. Urgency boost     -- bonus for urgency language
  6. Source quality     -- platform/source credibility calibration

Priority labels (based on final score 0-100):
  hot    -- 80+
  warm   -- 60-79
  cold   -- 30-59
  ignore -- below 30
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("signalforge.scoring_agent")


# -- Scoring configuration ------------------------------------------------

@dataclass
class ScoringConfig:
    """Tunable weights and thresholds for opportunity scoring."""

    # 1. Intent weights (0-100 base contribution)
    intent_weights: Dict[str, float] = field(default_factory=lambda: {
        "buying_intent": 40.0,
        "churn_risk": 38.0,
        "problem_intent": 32.0,
        "hiring_intent": 28.0,
        "competitor_mention": 26.0,
        "feature_request": 25.0,
        "ignore": 0.0,
    })

    # 2. Confidence multiplier range
    #    Final intent contribution = intent_weight * lerp(conf_min, conf_max, confidence)
    confidence_min_mult: float = 0.4
    confidence_max_mult: float = 1.0

    # 3. Engagement weight -- platform score mapped to bounded points
    engagement_max_points: float = 20.0
    engagement_score_cap: int = 300  # scores above this get max points
    engagement_platform_caps: Dict[str, int] = field(default_factory=lambda: {
        "reddit": 300,
        "quora": 80,
        "medium": 100,
        "unknown": 100,
    })
    engagement_platform_max_points: Dict[str, float] = field(default_factory=lambda: {
        "reddit": 20.0,
        "quora": 16.0,
        "medium": 14.0,
        "unknown": 12.0,
    })

    # 4. Signal boost -- each matching signal adds points (max 20)
    signal_boost_values: Dict[str, float] = field(default_factory=lambda: {
        "help_request": 5.0,
        "pain_point": 6.0,
        "recommendation_request": 5.0,
        "bottleneck": 4.0,
    })
    signal_boost_cap: float = 20.0

    # 5. Urgency boost -- flat bonus if urgency words detected (max 10)
    urgency_words: List[str] = field(default_factory=lambda: [
        "urgent", "asap", "need now", "stuck", "frustrated",
        "desperately", "immediately", "critical", "blocking",
        "time-sensitive", "deadline",
    ])
    urgency_bonus: float = 10.0

    # 6. Knowledge fit -- deterministic scanner-side match to company capabilities
    knowledge_fit_max_points: float = 12.0

    # 7. Source quality -- calibrate platform/source reliability and richness
    source_quality_max_points: float = 8.0
    source_platform_weights: Dict[str, float] = field(default_factory=lambda: {
        "reddit": 1.0,
        "quora": 0.9,
        "medium": 0.82,
        "unknown": 0.55,
    })

    # Priority label thresholds
    hot_threshold: float = 80.0
    warm_threshold: float = 60.0
    cold_threshold: float = 30.0


# -- Scoring engine -------------------------------------------------------

class OpportunityScoringAgent:
    """
    Scores and ranks classified opportunities by business value.

    Usage::

        agent = OpportunityScoringAgent()
        result = agent.score(opportunity_with_intent)
        ranked = agent.sort_by_priority(scored_list)
    """

    def __init__(self, config: Optional[ScoringConfig] = None) -> None:
        self.config = config or ScoringConfig()
        self._stats: Counter = Counter()
        logger.info(
            "OpportunityScoringAgent initialised -- "
            "hot>=%.0f, warm>=%.0f, cold>=%.0f",
            self.config.hot_threshold,
            self.config.warm_threshold,
            self.config.cold_threshold,
        )

    # -- Public API --------------------------------------------------------

    def score(self, opportunity: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score a single opportunity.

        Args:
            opportunity: Dict containing at minimum:
                - intent (str)
                - confidence (float)
                Optionally: score, opportunity_signals, title, body

        Returns:
            Dict with priority_score, priority_label,
            scoring_breakdown, recommended_action.
        """
        breakdown = self._compute_breakdown(opportunity)
        total = min(100.0, sum(breakdown.values()))
        label = self._label_from_score(total)
        action = self._action_from_label(label)

        self._stats[label] += 1

        post_id = opportunity.get("id", "unknown")
        logger.info(
            "Scored [%s] -> %.1f (%s) -- %s",
            post_id, total, label,
            opportunity.get("title", "")[:50],
        )

        return {
            "priority_score": round(total, 2),
            "priority_label": label,
            "scoring_breakdown": {k: round(v, 2) for k, v in breakdown.items()},
            "recommended_action": action,
        }

    def score_batch(
        self, opportunities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Score a batch of opportunities.

        Returns a list of scoring results in the same order as input.
        """
        logger.info("Batch scoring starting -- %d items", len(opportunities))
        results: List[Dict[str, Any]] = []

        for opp in opportunities:
            results.append(self.score(opp))

        self._log_distribution()
        return results

    def sort_by_priority(
        self, opportunities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Score all opportunities and return them sorted by priority
        (highest first). Each item gets a ``_scoring`` key with the
        full scoring result attached.
        """
        scored: List[Dict[str, Any]] = []

        for opp in opportunities:
            result = self.score(opp)
            enriched = {**opp, "_scoring": result}
            scored.append(enriched)

        scored.sort(
            key=lambda x: x["_scoring"]["priority_score"],
            reverse=True,
        )

        self._log_distribution()
        self._log_top_opportunities(scored)
        return scored

    # -- Scoring computation -----------------------------------------------

    def _compute_breakdown(self, opp: Dict[str, Any]) -> Dict[str, float]:
        """Compute individual scoring components."""
        intent = opp.get("intent", "ignore")
        confidence = float(opp.get("confidence", 0.0))
        if confidence > 1.0:
            confidence = confidence / 100.0
        confidence = max(0.0, min(1.0, confidence))
        platform = str(opp.get("platform", "unknown") or "unknown").lower()
        source_score = self._to_int(opp.get("source_score", opp.get("score", 0)))
        signals = opp.get("opportunity_signals") or opp.get("signals", [])
        title = opp.get("title", "")
        body = opp.get("body", "")

        # 1. Intent weight
        base_weight = self.config.intent_weights.get(intent, 0.0)

        # 2. Confidence multiplier
        conf_range = self.config.confidence_max_mult - self.config.confidence_min_mult
        conf_mult = self.config.confidence_min_mult + (conf_range * confidence)
        intent_score = base_weight * conf_mult

        # 3. Engagement weight
        engagement = self._compute_engagement(source_score, platform)

        # 4. Signal boost
        signal_boost = self._compute_signal_boost(signals)

        # 5. Urgency boost
        urgency = self._compute_urgency(title, body)

        # 6. Knowledge-aware product fit boost
        knowledge_fit = self._compute_knowledge_fit(opp)

        # 7. Source/platform quality calibration
        source_quality = self._compute_source_quality(opp, platform)

        return {
            "intent_score": intent_score,
            "engagement_score": engagement,
            "signal_boost": signal_boost,
            "urgency_boost": urgency,
            "knowledge_fit_boost": knowledge_fit,
            "source_quality_boost": source_quality,
        }

    def _compute_engagement(self, source_score: int, platform: str = "reddit") -> float:
        """Map platform-specific source score to engagement points."""
        if source_score <= 0:
            return 0.0
        platform_key = str(platform or "unknown").lower()
        cap = self.config.engagement_platform_caps.get(
            platform_key,
            self.config.engagement_score_cap,
        )
        max_points = self.config.engagement_platform_max_points.get(
            platform_key,
            self.config.engagement_max_points,
        )
        ratio = min(source_score / max(cap, 1), 1.0)
        return ratio * max_points

    def _compute_signal_boost(self, signals: List[str]) -> float:
        """Sum boost values for matching signals, capped."""
        total = 0.0
        for sig in signals:
            total += self.config.signal_boost_values.get(sig, 0.0)
        return min(total, self.config.signal_boost_cap)

    def _compute_urgency(self, title: str, body: str) -> float:
        """Return urgency bonus if urgency words are detected."""
        text = f"{title} {body}".lower()
        for word in self.config.urgency_words:
            if word in text:
                return self.config.urgency_bonus
        return 0.0

    def _compute_knowledge_fit(self, opportunity: Dict[str, Any]) -> float:
        raw_score = opportunity.get("knowledge_fit_score", 0.0)
        try:
            fit_score = float(raw_score)
        except (TypeError, ValueError):
            fit_score = 0.0

        matches = opportunity.get("knowledge_capability_matches", [])
        if isinstance(matches, list) and matches:
            fit_score = max(fit_score, min(1.0, 0.18 * len(matches)))

        return max(0.0, min(1.0, fit_score)) * self.config.knowledge_fit_max_points

    def _compute_source_quality(self, opportunity: Dict[str, Any], platform: str) -> float:
        """Reward sources that are reliable, identifiable, and content-rich."""
        platform_key = str(platform or "unknown").lower()
        quality = self.config.source_platform_weights.get(
            platform_key,
            self.config.source_platform_weights.get("unknown", 0.55),
        )

        if opportunity.get("url_valid", True) is False:
            quality -= 0.3

        if self._has_source_context(opportunity):
            quality += 0.08

        author = str(opportunity.get("author", "") or "").strip().lower()
        if author and author not in {"[unknown]", "unknown", "unknown author", "[deleted]"}:
            quality += 0.04

        body_len = len(str(opportunity.get("body", "") or "").strip())
        if body_len >= 500:
            quality += 0.06
        elif body_len < 80:
            quality -= 0.06

        try:
            relevance = float(opportunity.get("semantic_relevance_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            relevance = 0.0
        if relevance > 0:
            quality += min(0.12, relevance * 0.12)

        return max(0.0, min(1.0, quality)) * self.config.source_quality_max_points

    @staticmethod
    def _has_source_context(opportunity: Dict[str, Any]) -> bool:
        for key in ("source", "subreddit", "topic", "community", "channel"):
            if str(opportunity.get(key, "") or "").strip():
                return True
        tags = opportunity.get("tags", [])
        return isinstance(tags, list) and bool(tags)

    @staticmethod
    def _to_int(value: Any, fallback: int = 0) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return fallback

    # -- Label & action mapping --------------------------------------------

    def _label_from_score(self, score: float) -> str:
        if score >= self.config.hot_threshold:
            return "hot"
        if score >= self.config.warm_threshold:
            return "warm"
        if score >= self.config.cold_threshold:
            return "cold"
        return "ignore"

    @staticmethod
    def _action_from_label(label: str) -> str:
        return {
            "hot": "respond_immediately",
            "warm": "respond_soon",
            "cold": "monitor",
            "ignore": "skip",
        }.get(label, "skip")

    # -- Stats & logging ---------------------------------------------------

    def _log_distribution(self) -> None:
        total = sum(self._stats.values())
        if total == 0:
            return

        logger.info("--- Priority Distribution (%d total) ---", total)
        for label in ["hot", "warm", "cold", "ignore"]:
            count = self._stats.get(label, 0)
            pct = (count / total) * 100
            bar = "#" * int(pct / 5)
            logger.info("  %-8s %3d (%5.1f%%) %s", label, count, pct, bar)

    def _log_top_opportunities(
        self, scored: List[Dict[str, Any]], top_n: int = 5
    ) -> None:
        logger.info("--- Top %d Opportunities ---", min(top_n, len(scored)))
        for i, item in enumerate(scored[:top_n]):
            sc = item["_scoring"]
            logger.info(
                "  #%d [%s] %.1f (%s) -- %s",
                i + 1,
                item.get("id", "?"),
                sc["priority_score"],
                sc["priority_label"],
                item.get("title", "")[:50],
            )

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def reset_stats(self) -> None:
        self._stats.clear()

    def __repr__(self) -> str:
        return (
            f"<OpportunityScoringAgent scored={sum(self._stats.values())}>"
        )
