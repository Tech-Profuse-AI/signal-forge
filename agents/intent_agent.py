"""
SignalForge IntentAgent — Phase 3.

Classifies discovered opportunities into actionable intent categories
using the LLM provider abstraction (BaseLLMProvider).

Supported intents:
  - buying_intent      — user actively looking for tools/products
  - problem_intent     — user facing workflow pain
  - hiring_intent      — looking for people/agencies/tools
  - competitor_mention  — mentions competitor tools/platforms
  - feature_request    — wants missing functionality
  - churn_risk         — frustration with current tools
  - ignore             — not actionable

Never calls Gemini (or any LLM) directly — always through
providers.llm_provider.BaseLLMProvider.generate().
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from providers.llm_provider import BaseLLMProvider

logger = logging.getLogger("signalforge.intent_agent")

# ── Constants ────────────────────────────────────────────────────────

VALID_INTENTS = frozenset([
    "buying_intent",
    "problem_intent",
    "hiring_intent",
    "competitor_mention",
    "feature_request",
    "churn_risk",
    "ignore",
])

_FALLBACK_RESULT: Dict[str, Any] = {
    "intent": "ignore",
    "confidence": 0.0,
    "reasoning": "Failed to classify — falling back to ignore.",
    "business_relevance": "none",
    "recommended_action": "skip",
}

# ── Classification prompt ────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an intent classification engine for SignalForge, a social media \
engagement platform. Your task is to analyse a Reddit post and classify \
it into exactly ONE intent category.

## Intent categories

| Intent              | Meaning                                       |
|---------------------|-----------------------------------------------|
| buying_intent       | User actively looking for tools or products   |
| problem_intent      | User facing workflow pain                     |
| hiring_intent       | Looking for people, agencies, or tools to hire|
| competitor_mention  | Mentions competitor tools or platforms        |
| feature_request     | Wants missing functionality                   |
| churn_risk          | Frustration with current tools                |
| ignore              | Not actionable                                |

## Rules

1. Choose the SINGLE most dominant intent.
2. Assign a confidence score between 0.0 and 1.0.
3. Provide brief reasoning (1-2 sentences).
4. State the business relevance for a social media engagement tool vendor.
5. Recommend ONE action: respond, monitor, escalate, skip.
6. Output ONLY valid JSON — no markdown fences, no commentary.

## Output schema (strict)

{
  "intent": "<one of the 7 intents above>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<1-2 sentence explanation>",
  "business_relevance": "<why this matters to us>",
  "recommended_action": "<respond|monitor|escalate|skip>"
}
"""


def _build_classification_prompt(opportunity: Dict[str, Any]) -> str:
    """Build the full prompt for a single opportunity classification."""
    title = opportunity.get("title", "")
    body = opportunity.get("body", "")
    signals = opportunity.get("opportunity_signals", [])
    subreddit = opportunity.get("subreddit", "")
    score = opportunity.get("score", 0)

    user_message = (
        f"Classify this Reddit post:\n\n"
        f"Subreddit: r/{subreddit}\n"
        f"Score: {score}\n"
        f"Title: {title}\n"
        f"Body: {body}\n"
        f"Pre-detected signals: {', '.join(signals) if signals else 'none'}\n\n"
        f"Respond with ONLY the JSON object."
    )

    return f"{_SYSTEM_PROMPT}\n\n{user_message}"


# ── IntentAgent ──────────────────────────────────────────────────────

class IntentAgent:
    """
    Classifies opportunity posts into intent categories via LLM.

    Usage::

        from providers.llm_provider import get_llm_provider
        llm = get_llm_provider("gemini", api_key="...")
        agent = IntentAgent(llm)

        result = agent.classify(opportunity_dict)
        results = agent.classify_batch(list_of_opportunities)
    """

    def __init__(self, llm: BaseLLMProvider) -> None:
        if not isinstance(llm, BaseLLMProvider):
            raise TypeError(
                f"llm must be a BaseLLMProvider instance, got {type(llm).__name__}"
            )
        self._llm = llm
        self._stats: Counter = Counter()
        logger.info("IntentAgent initialised — llm=%s", self._llm)

    # ── Public API ────────────────────────────────────────────────────

    def classify(self, opportunity: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify a single opportunity into an intent category.

        Args:
            opportunity: Dict with at least 'title' and 'body' keys.
                         Optionally 'opportunity_signals', 'subreddit', 'score'.

        Returns:
            Dict with keys: intent, confidence, reasoning,
            business_relevance, recommended_action.
        """
        post_id = opportunity.get("id", "unknown")
        prompt = _build_classification_prompt(opportunity)

        try:
            raw_response = self._llm.generate(prompt)
            result = self._parse_and_validate(raw_response)

            # Retry once if parsing produced fallback (ignore with 0.0 confidence)
            if result["intent"] == "ignore" and result["confidence"] == 0.0:
                logger.info("Retrying classification for [%s] after parse failure", post_id)
                raw_response = self._llm.generate(prompt)
                result = self._parse_and_validate(raw_response)
        except Exception as exc:
            logger.error(
                "Classification failed for [%s]: %s — using fallback",
                post_id, exc,
            )
            result = dict(_FALLBACK_RESULT)

        # Track stats
        self._stats[result["intent"]] += 1

        logger.info(
            "Classified [%s] -> %s (%.2f) — %s",
            post_id,
            result["intent"],
            result["confidence"],
            opportunity.get("title", "")[:50],
        )

        return result

    def classify_batch(
        self, opportunities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Classify a batch of opportunities sequentially.

        Returns a list of result dicts in the same order as input.
        Logs an intent distribution summary at the end.
        """
        logger.info("Batch classification starting — %d items", len(opportunities))
        results: List[Dict[str, Any]] = []

        for opp in opportunities:
            result = self.classify(opp)
            results.append(result)

        self._log_distribution()
        return results

    # ── Parsing & Validation ──────────────────────────────────────────

    def _parse_and_validate(self, raw: str) -> Dict[str, Any]:
        """
        Parse the LLM response as JSON, validate fields, and return
        a clean result dict. Falls back to ignore on any failure.
        """
        from providers.json_utils import extract_json

        try:
            data = extract_json(raw)
        except ValueError as exc:
            logger.warning("JSON extraction failed: %s — raw: %s", exc, raw[:200])
            return dict(_FALLBACK_RESULT)

        # Validate intent
        intent = data.get("intent", "").strip().lower()
        if intent not in VALID_INTENTS:
            logger.warning(
                "Invalid intent '%s' — falling back to ignore", intent
            )
            intent = "ignore"

        # Validate confidence
        try:
            confidence = float(data.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.0

        return {
            "intent": intent,
            "confidence": confidence,
            "reasoning": str(data.get("reasoning", "")),
            "business_relevance": str(data.get("business_relevance", "")),
            "recommended_action": str(data.get("recommended_action", "skip")),
        }

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove ```json ... ``` wrappers that LLMs sometimes add."""
        from providers.json_utils import strip_code_fences
        return strip_code_fences(text)

    # ── Stats & Logging ───────────────────────────────────────────────

    def _log_distribution(self) -> None:
        """Log the cumulative intent distribution."""
        total = sum(self._stats.values())
        if total == 0:
            return

        logger.info("--- Intent Distribution (%d total) ---", total)
        for intent in sorted(VALID_INTENTS):
            count = self._stats.get(intent, 0)
            pct = (count / total) * 100
            bar = "#" * int(pct / 5)
            logger.info("  %-20s %3d (%5.1f%%) %s", intent, count, pct, bar)

    @property
    def stats(self) -> Dict[str, int]:
        """Return a copy of the cumulative intent counts."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Clear cumulative intent statistics."""
        self._stats.clear()

    def __repr__(self) -> str:
        return f"<IntentAgent llm={self._llm} classified={sum(self._stats.values())}>"
