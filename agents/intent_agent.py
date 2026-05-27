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

INTENT_ALIASES = {
    "engage": "problem_intent",
    "opportunity": "problem_intent",
    "respond": "problem_intent",
    "actionable": "problem_intent",
}

ACTIONABLE_SIGNALS = frozenset([
    "pain_point",
    "bottleneck",
    "help_request",
    "recommendation_request",
])

BUYING_PATTERNS = (
    "recommend",
    "looking for",
    "any tool",
    "tool for",
    "best tool",
    "which tool",
    "alternative",
    "budget",
    "software",
    "platform",
)

CHURN_PATTERNS = (
    "frustrated with",
    "fed up",
    "switch from",
    "switching from",
    "migrating from",
    "current tool",
    "current platform",
    "doesn't handle",
    "doesnt handle",
)

WORKFLOW_PROBLEM_PATTERNS = (
    "workflow",
    "manual process",
    "manual",
    "automation",
    "automate",
    "bottleneck",
    "scaling",
    "at scale",
    "doesn't scale",
    "doesnt scale",
    "can't keep up",
    "cant keep up",
    "operational",
    "too much time",
    "takes too long",
    "time consuming",
    "repetitive",
    "pain point",
    "frustrat",
    "stuck",
    "unsustainable",
)

_FALLBACK_RESULT: Dict[str, Any] = {
    "intent": "ignore",
    "confidence": 0.0,
    "reasoning": "Failed to classify — falling back to ignore.",
    "business_relevance": "none",
    "recommended_action": "skip",
}

# ── Classification prompt ────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an intent classification engine for SignalForge, an opportunity \
discovery and engagement platform. Your task is to analyse a Reddit or Quora \
discussion and classify it into exactly ONE intent category.

## Intent categories

| Intent              | Meaning                                       |
|---------------------|-----------------------------------------------|
| buying_intent       | User actively looking for tools or products   |
| problem_intent      | User facing workflow pain                     |
| hiring_intent       | Looking for people, agencies, or tools to hire|
| competitor_mention  | Mentions competitor tools or platforms        |
| feature_request     | Wants missing functionality                   |
| churn_risk          | Frustration with current tools                |
| ignore              | Unrelated, spam, meme, news, or no actionable pain/ask |

## Rules

1. Choose the SINGLE most dominant intent.
2. Assign a confidence score between 0.0 and 1.0.
3. Provide brief reasoning (1-2 sentences).
4. State the business relevance for a vendor that solves social listening,
   community engagement, workflow automation, or operations bottlenecks.
5. Recommend ONE action: respond, monitor, escalate, skip.
6. Treat pre-detected signals as strong positive evidence. If signals include
   pain_point, bottleneck, help_request, or recommendation_request, prefer an
   actionable intent over ignore unless the post is clearly spam or unrelated.
7. Workflow frustrations, manual processes, automation pain, scaling struggles,
   and operational bottlenecks are actionable. Classify them as problem_intent
   or churn_risk, not ignore.
8. Help or recommendation requests about tools, processes, or ways to solve a
   work problem are actionable. Classify them as buying_intent or
   problem_intent and usually recommend respond.
9. Use skip only when the selected intent is ignore.
10. Output ONLY valid JSON - no markdown fences, no commentary.

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
    platform = opportunity.get("platform") or opportunity.get("source") or "reddit"
    score = opportunity.get("source_score", opportunity.get("score", 0))

    user_message = (
        f"Classify this Reddit/Quora opportunity:\n\n"
        f"Platform: {platform}\n"
        f"Subreddit: r/{subreddit}\n"
        f"Score: {score}\n"
        f"Title: {title}\n"
        f"Body: {body}\n"
        f"Pre-detected signals: {', '.join(signals) if signals else 'none'}\n\n"
        f"Respond with ONLY the JSON object."
    )

    return f"{_SYSTEM_PROMPT}\n\n{user_message}"


def _normalise_signals(raw: Any) -> set[str]:
    """Return scanner signals as normalized lowercase labels."""
    if raw is None:
        return set()
    if isinstance(raw, str):
        values = re.split(r"[,;\s]+", raw)
    elif isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        return set()

    return {
        str(value).strip().lower()
        for value in values
        if str(value).strip()
    }


def _opportunity_text(opportunity: Dict[str, Any]) -> str:
    parts = [
        opportunity.get("title", ""),
        opportunity.get("body", ""),
        opportunity.get("selftext", ""),
        opportunity.get("description", ""),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _has_actionable_evidence(opportunity: Dict[str, Any]) -> bool:
    signals = _normalise_signals(
        opportunity.get("opportunity_signals") or opportunity.get("signals")
    )
    if signals & ACTIONABLE_SIGNALS:
        return True
    return _contains_any(_opportunity_text(opportunity), WORKFLOW_PROBLEM_PATTERNS)


def _infer_actionable_intent(opportunity: Dict[str, Any]) -> str:
    signals = _normalise_signals(
        opportunity.get("opportunity_signals") or opportunity.get("signals")
    )
    text = _opportunity_text(opportunity)

    if "pain_point" in signals and _contains_any(text, CHURN_PATTERNS):
        return "churn_risk"
    if _contains_any(text, CHURN_PATTERNS):
        return "churn_risk"
    if (
        {"help_request", "recommendation_request"} & signals
        and _contains_any(text, BUYING_PATTERNS)
    ):
        return "buying_intent"
    if _contains_any(text, BUYING_PATTERNS) and not (
        {"pain_point", "bottleneck"} & signals
    ):
        return "buying_intent"
    return "problem_intent"


def _confidence_from_actionable_evidence(
    result: Dict[str, Any],
    opportunity: Dict[str, Any],
) -> float:
    signals = _normalise_signals(
        opportunity.get("opportunity_signals") or opportunity.get("signals")
    )
    actionable_count = len(signals & ACTIONABLE_SIGNALS)

    base = 0.68
    if actionable_count >= 2:
        base = 0.76
    elif actionable_count == 1:
        base = 0.70
    if (
        {"pain_point", "bottleneck"} & signals
        and {"help_request", "recommendation_request"} & signals
    ):
        base = max(base, 0.78)

    try:
        original = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        original = 0.0

    if original > 0:
        base = max(base, min(original, 0.82))

    return round(min(base, 0.84), 2)


def _business_relevance_for_intent(intent: str) -> str:
    if intent == "buying_intent":
        return "High - the user is asking for a tool or process recommendation."
    if intent == "churn_risk":
        return "High - the user is frustrated with an existing workflow or tool."
    return "Medium - the user describes workflow or operations pain worth engaging."


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
            raw_intent = self._extract_raw_intent(raw_response)
            result = self._parse_and_validate(raw_response)

            # Retry once if parsing produced fallback (ignore with 0.0 confidence)
            if result["intent"] == "ignore" and result["confidence"] == 0.0:
                logger.info("Retrying classification for [%s] after parse failure", post_id)
                raw_response = self._llm.generate(prompt)
                raw_intent = self._extract_raw_intent(raw_response)
                result = self._parse_and_validate(raw_response)

            result = self._relax_actionable_ignore(opportunity, result, raw_intent)
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

    def _relax_actionable_ignore(
        self,
        opportunity: Dict[str, Any],
        result: Dict[str, Any],
        raw_intent: str,
    ) -> Dict[str, Any]:
        if result.get("intent") != "ignore" or raw_intent != "ignore":
            return result
        if not _has_actionable_evidence(opportunity):
            return result

        intent = _infer_actionable_intent(opportunity)
        confidence = _confidence_from_actionable_evidence(result, opportunity)
        signals = sorted(
            _normalise_signals(
                opportunity.get("opportunity_signals") or opportunity.get("signals")
            )
            & ACTIONABLE_SIGNALS
        )

        logger.info(
            "Relaxed ignore for [%s] -> %s based on actionable signals=%s",
            opportunity.get("id", "unknown"),
            intent,
            signals,
        )

        return {
            "intent": intent,
            "confidence": confidence,
            "reasoning": (
                "Pre-detected opportunity signals indicate an actionable "
                "workflow, pain, bottleneck, help, or recommendation discussion."
            ),
            "business_relevance": _business_relevance_for_intent(intent),
            "recommended_action": "respond",
        }

    @staticmethod
    def _extract_raw_intent(raw: str) -> str:
        from providers.json_utils import extract_json

        try:
            data = extract_json(raw)
        except ValueError:
            return ""
        return str(data.get("intent", "")).strip().lower()

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
        intent = INTENT_ALIASES.get(intent, intent)
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
