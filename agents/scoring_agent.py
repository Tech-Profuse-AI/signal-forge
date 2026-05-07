"""
SignalForge OpportunityScoringAgent -- Phase 4.

Prioritises classified opportunities by business value using a
weighted scoring formula across four dimensions:

  1. Intent weight     -- how valuable is this intent type?
  2. Confidence mult   -- how confident was the LLM classification?
  3. Engagement weight  -- Reddit score (community validation)
  4. Signal boost      -- bonus for high-value opportunity signals
  5. Urgency boost     -- bonus for urgency language

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

    # 3. Engagement weight -- Reddit score mapped to 0-20 points
    engagement_max_points: float = 20.0
    engagement_score_cap: int = 300  # scores above this get max points

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
        reddit_score = int(opp.get("score", 0))
        signals = opp.get("opportunity_signals", [])
        title = opp.get("title", "")
        body = opp.get("body", "")

        # 1. Intent weight
        base_weight = self.config.intent_weights.get(intent, 0.0)

        # 2. Confidence multiplier
        conf_range = self.config.confidence_max_mult - self.config.confidence_min_mult
        conf_mult = self.config.confidence_min_mult + (conf_range * confidence)
        intent_score = base_weight * conf_mult

        # 3. Engagement weight
        engagement = self._compute_engagement(reddit_score)

        # 4. Signal boost
        signal_boost = self._compute_signal_boost(signals)

        # 5. Urgency boost
        urgency = self._compute_urgency(title, body)

        return {
            "intent_score": intent_score,
            "engagement_score": engagement,
            "signal_boost": signal_boost,
            "urgency_boost": urgency,
        }

    def _compute_engagement(self, reddit_score: int) -> float:
        """Map Reddit score to engagement points (0 to max)."""
        if reddit_score <= 0:
            return 0.0
        cap = self.config.engagement_score_cap
        ratio = min(reddit_score / cap, 1.0)
        return ratio * self.config.engagement_max_points

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
