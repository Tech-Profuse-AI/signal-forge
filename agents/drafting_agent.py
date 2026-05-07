"""
SignalForge DraftingAgent -- Phase 6.

Generates human-review-ready Reddit replies from structured opportunity,
intent, scoring, and product-knowledge context using the existing LLM
provider abstraction only.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List

from providers.llm_provider import BaseLLMProvider

logger = logging.getLogger("signalforge.drafting_agent")

VALID_TONES = frozenset(["helpful", "expert", "casual", "professional"])
_REQUIRED_INPUT_KEYS = (
    "opportunity",
    "intent_data",
    "score_data",
    "knowledge_context",
)
_PROMOTIONAL_PATTERNS = (
    r"\bbuy now\b",
    r"\bsign up\b",
    r"\bbook a demo\b",
    r"\bcontact sales\b",
    r"\bstart (?:your )?free trial\b",
    r"\brequest a demo\b",
    r"\bvisit our website\b",
    r"\blimited time\b",
    r"\bact now\b",
)

_SYSTEM_PROMPT = """\
You are the DraftingAgent for SignalForge.

Your task is to write a human-review-ready Reddit reply for a discovered
opportunity using:
- the original opportunity
- its intent classification
- its business priority score
- retrieved product knowledge context

Write like a thoughtful human community member.

Rules:
1. Be conversational, helpful, and Reddit-safe.
2. Solve the user's problem first.
3. Never hard sell.
4. Never sound spammy or automated.
5. Mention SignalForge only if it is naturally useful to the user.
6. Keep the draft short-to-medium length and actionable.
7. Product awareness should inform the advice, but the reply should still
   feel useful even without a product mention.
8. Choose exactly one tone from: helpful, expert, casual, professional.
9. CTA must be optional and low-pressure. Use an empty string if none is needed.
10. Output ONLY valid JSON. No markdown fences and no extra commentary.

Strict output schema:
{
  "draft": "<main reply>",
  "tone": "<helpful|expert|casual|professional>",
  "cta": "<optional low-pressure CTA or empty string>",
  "reasoning": "<1-2 sentences explaining why this reply fits>"
}
"""

_SAFE_FALLBACK_DRAFT = (
    "That sounds frustrating. A practical next step is to narrow the workflow "
    "into a few clear steps: define what conversations are worth responding to, "
    "capture the recurring pain points, and use a lightweight reply framework "
    "so the team can stay helpful without sounding repetitive."
)


class DraftingAgent:
    """Generate grounded, human-review-ready drafts through the LLM abstraction."""

    def __init__(self, llm: BaseLLMProvider) -> None:
        if not isinstance(llm, BaseLLMProvider):
            raise TypeError(
                f"llm must be a BaseLLMProvider instance, got {type(llm).__name__}"
            )
        self._llm = llm
        self._stats: Counter = Counter()
        logger.info("DraftingAgent initialised - llm=%s", self._llm)

    def generate_draft(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Generate a single draft from the structured Phase 2-5 inputs.
        """
        if not self._is_valid_input_data(input_data):
            logger.warning("Invalid drafting input received - using fallback")
            result = self._fallback_result(
                "Fallback used because the drafting input was incomplete."
            )
            self._stats[result["tone"]] += 1
            return result

        prompt = self._build_prompt(input_data)
        opportunity = input_data["opportunity"]

        try:
            raw_response = self._llm.generate(prompt)
            parsed = self._parse_response(raw_response)
            result = self._validate_output(parsed)

            # Retry once if we got a fallback result from parse failure
            if result["draft"] == _SAFE_FALLBACK_DRAFT:
                logger.info("Retrying draft generation for [%s] after parse failure", opportunity.get("id", "unknown"))
                raw_response = self._llm.generate(prompt)
                parsed = self._parse_response(raw_response)
                retry_result = self._validate_output(parsed)
                if retry_result["draft"] != _SAFE_FALLBACK_DRAFT:
                    result = retry_result
        except Exception as exc:
            logger.error(
                "Draft generation failed for [%s]: %s - using fallback",
                opportunity.get("id", "unknown"),
                exc,
            )
            result = self._fallback_result(
                "Fallback used because the generated draft could not be trusted."
            )

        self._stats[result["tone"]] += 1
        logger.info(
            "Generated draft for [%s] - tone=%s, cta=%s",
            opportunity.get("id", "unknown"),
            result["tone"],
            bool(result["cta"]),
        )
        return result

    def generate_batch(self, inputs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Generate drafts sequentially for a batch of structured inputs."""
        if not isinstance(inputs, list):
            raise TypeError(f"inputs must be a list, got {type(inputs).__name__}")

        logger.info("Batch drafting starting - %d items", len(inputs))
        results: List[Dict[str, str]] = []
        for item in inputs:
            if isinstance(item, dict):
                results.append(self.generate_draft(item))
            else:
                results.append(self._fallback_result(
                    "Fallback used because a batch item was not a valid dict."
                ))

        self._log_distribution()
        return results

    def _build_prompt(self, input_data: Dict[str, Any]) -> str:
        opportunity = input_data["opportunity"]
        intent_data = input_data["intent_data"]
        score_data = input_data["score_data"]
        knowledge_context = input_data["knowledge_context"]

        preferred_tone = self._preferred_tone(opportunity, intent_data, score_data)
        relevant_context = knowledge_context.get("relevant_context", [])[:3]
        context_lines = []
        for item in relevant_context:
            source = str(item.get("source", "unknown"))
            content = self._clean_text(str(item.get("content", "")))
            if content:
                context_lines.append(f"- [{source}] {content}")

        if not context_lines:
            context_lines.append("- No retrieved chunks were available.")

        sources = knowledge_context.get("sources", [])
        source_line = ", ".join(str(source) for source in sources) if sources else "none"

        return (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Opportunity:\n"
            f"- ID: {opportunity.get('id', 'unknown')}\n"
            f"- Subreddit: r/{opportunity.get('subreddit', '')}\n"
            f"- Title: {self._clean_text(str(opportunity.get('title', '')))}\n"
            f"- Body: {self._clean_text(str(opportunity.get('body', '')))}\n"
            f"- Signals: {', '.join(opportunity.get('opportunity_signals', []) or ['none'])}\n\n"
            f"Intent classification:\n"
            f"- Intent: {intent_data.get('intent', '')}\n"
            f"- Confidence: {intent_data.get('confidence', 0.0)}\n"
            f"- Business relevance: {self._clean_text(str(intent_data.get('business_relevance', '')))}\n"
            f"- Recommended action: {intent_data.get('recommended_action', '')}\n\n"
            f"Opportunity score:\n"
            f"- Priority score: {score_data.get('priority_score', 0.0)}\n"
            f"- Priority label: {score_data.get('priority_label', '')}\n"
            f"- Recommended action: {score_data.get('recommended_action', '')}\n\n"
            f"Retrieved product knowledge summary:\n"
            f"- Summary: {self._clean_text(str(knowledge_context.get('summary', '')))}\n"
            f"- Sources: {source_line}\n"
            f"- Relevant chunks:\n"
            f"{chr(10).join(context_lines)}\n\n"
            f"Preferred tone: {preferred_tone}\n\n"
            f"Write the JSON response now."
        )

    def _parse_response(self, raw_response: str) -> Dict[str, str]:
        from providers.json_utils import extract_json
        data = extract_json(raw_response)

        return {
            "draft": self._clean_text(str(data.get("draft", ""))),
            "tone": self._clean_text(str(data.get("tone", ""))).lower(),
            "cta": self._clean_text(str(data.get("cta", ""))),
            "reasoning": self._clean_text(str(data.get("reasoning", ""))),
        }

    def _validate_output(self, result: Dict[str, str]) -> Dict[str, str]:
        draft = result["draft"]
        tone = result["tone"] if result["tone"] in VALID_TONES else "helpful"
        cta = result["cta"]
        reasoning = result["reasoning"] or (
            "The reply focuses on the user's problem first and stays low-pressure."
        )

        if not draft:
            logger.warning("Draft validation failed - empty draft")
            return self._fallback_result(
                "Fallback used because the model returned an empty draft."
            )

        if len(draft) < 60 or len(draft.split()) < 12:
            logger.warning("Draft validation failed - draft too short")
            return self._fallback_result(
                "Fallback used because the generated draft was too short."
            )

        if self._is_too_promotional(draft, cta):
            logger.warning("Draft validation failed - draft too promotional")
            return self._fallback_result(
                "Fallback used because the generated draft was too promotional."
            )

        return {
            "draft": draft,
            "tone": tone,
            "cta": cta,
            "reasoning": reasoning,
        }

    def _preferred_tone(
        self,
        opportunity: Dict[str, Any],
        intent_data: Dict[str, Any],
        score_data: Dict[str, Any],
    ) -> str:
        intent = str(intent_data.get("intent", "")).lower()
        label = str(score_data.get("priority_label", "")).lower()
        subreddit = str(opportunity.get("subreddit", "")).lower()

        if intent == "hiring_intent":
            return "professional"
        if intent in {"buying_intent", "competitor_mention"} or label == "hot":
            return "expert"
        if subreddit in {"casualconversation", "community", "startups"}:
            return "casual"
        return "helpful"

    @staticmethod
    def _is_valid_input_data(input_data: Any) -> bool:
        if not isinstance(input_data, dict):
            return False
        for key in _REQUIRED_INPUT_KEYS:
            if key not in input_data or not isinstance(input_data[key], dict):
                return False

        opportunity = input_data["opportunity"]
        if not opportunity.get("title") and not opportunity.get("body"):
            return False
        return True

    @staticmethod
    def _is_too_promotional(draft: str, cta: str) -> bool:
        combined = f"{draft} {cta}".lower()
        if combined.count("signalforge") > 1:
            return True
        return any(re.search(pattern, combined) for pattern in _PROMOTIONAL_PATTERNS)

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        return text.strip()

    @staticmethod
    def _fallback_result(reason: str) -> Dict[str, str]:
        return {
            "draft": _SAFE_FALLBACK_DRAFT,
            "tone": "helpful",
            "cta": "",
            "reasoning": reason,
        }

    def _log_distribution(self) -> None:
        total = sum(self._stats.values())
        if total == 0:
            return

        logger.info("--- Draft Tone Distribution (%d total) ---", total)
        for tone in sorted(VALID_TONES):
            count = self._stats.get(tone, 0)
            logger.info("  %-12s %3d", tone, count)

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def reset_stats(self) -> None:
        self._stats.clear()

    def __repr__(self) -> str:
        return f"<DraftingAgent llm={self._llm} drafted={sum(self._stats.values())}>"

