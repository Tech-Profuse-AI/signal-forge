"""
SignalForge ComplianceAgent -- Phase 7.

Validates drafted replies for promotional risk, spam patterns, unsafe
claims, platform safety, and tone safety before human review or publishing.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List

logger = logging.getLogger("signalforge.compliance_agent")

VALID_RISK_LEVELS = frozenset(["safe", "review", "reject"])
_REQUIRED_KEYS = ("draft", "tone", "cta", "reasoning")

_VIOLATION_SEVERITY = {
    "invalid_input": 3,
    "hard_sell_language": 3,
    "unsafe_claims": 3,
    "platform_unsafe_language": 3,
    "aggressive_or_manipulative_tone": 3,
    "misleading_claims": 3,
    "excessive_product_mention": 1,
    "exaggerated_claims": 2,
    "spammy_repetition": 2,
    "unnatural_cta": 2,
}

_HARD_SELL_PATTERNS = (
    r"\bbuy now\b",
    r"\bbuy(?:\s+\w+){0,3}\s+now\b",
    r"\bsign up now\b",
    r"\bbook a demo\b",
    r"\bcontact sales\b",
    r"\bstart (?:your )?free trial\b",
    r"\brequest a demo\b",
    r"\bact now\b",
    r"\blimited time\b",
)

_UNSAFE_CLAIM_PATTERNS = (
    r"\bguarantee(?:d|s)?\b",
    r"\b100%\b",
    r"\b10x\b",
    r"\bdouble your\b",
    r"\binstantly\b",
    r"\bovernight\b",
    r"\bnever fails?\b",
    r"\balways works?\b",
    r"\bwill definitely\b",
)

_PLATFORM_SAFETY_PATTERNS = (
    r"\bdm me\b",
    r"\bmessage me\b",
    r"\bclick here\b",
    r"\buse my link\b",
    r"\bin my bio\b",
)

_AGGRESSIVE_TONE_PATTERNS = (
    r"\byou(?:'d| would) be crazy\b",
    r"\bonly an idiot\b",
    r"\bno excuses\b",
    r"\byou must\b",
    r"\bmust buy\b",
    r"\bcan'?t afford not to\b",
    r"\bdon'?t miss out\b",
)

_MISLEADING_CLAIM_PATTERNS = (
    r"\b#1\b",
    r"\bnumber one\b",
    r"\bno[- ]risk\b",
    r"\bproven to\b",
    r"\bzero effort\b",
)

_EXAGGERATED_CLAIM_PATTERNS = (
    r"\bindustry-leading\b",
    r"\bbest-in-class\b",
    r"\bworld-class\b",
    r"\brevolutionary\b",
    r"\bgame-changing\b",
    r"\bunmatched\b",
)

_UNNATURAL_CTA_PATTERNS = (
    r"\bcheck us out\b",
    r"\bworth checking out now\b",
    r"\breach out today\b",
    r"\blet'?s hop on a call\b",
    r"\bget started today\b",
)

_SANITIZE_REPLACEMENTS = (
    (r"\bbuy now\b", "consider whether it fits your workflow"),
    (r"\bbuy(?:\s+\w+){0,3}\s+now\b", "consider whether a tool like this fits your workflow"),
    (r"\bsign up now\b", "consider trying an option that fits your workflow"),
    (r"\bsign up\b", "try"),
    (r"\bbook a demo\b", "take a closer look"),
    (r"\bcontact sales\b", "compare a few options"),
    (r"\brequest a demo\b", "take a closer look"),
    (r"\bstart (?:your )?free trial\b", "try it if it seems relevant"),
    (r"\bact now\b", "when you have time"),
    (r"\blimited time\b", "when relevant"),
    (r"\bdm me\b", "I can share more detail here"),
    (r"\bmessage me\b", "I can share more detail here"),
    (r"\bclick here\b", "take a closer look"),
    (r"\buse my link\b", "take a closer look"),
    (r"\bin my bio\b", "here in the thread"),
    (r"\bguarantee(?:d|s)?\b", "can help"),
    (r"\b100%\b", "more reliably"),
    (r"\b10x\b", "meaningfully"),
    (r"\bdouble your\b", "improve your"),
    (r"\binstantly\b", "more quickly"),
    (r"\bovernight\b", "over time"),
    (r"\bnever fails?\b", "is often reliable"),
    (r"\balways works?\b", "often works"),
    (r"\bwill definitely\b", "can"),
    (
        r"\bconsider whether a tool like this fits your workflow and take a closer "
        r"look because it can help meaningfully better results over time\b",
        "a tool like this may be worth considering if it can help improve results over time",
    ),
    (r"\bcan help meaningfully better results\b", "can help improve results"),
    (r"\bmeaningfully better results\b", "better results"),
    (
        r"\bi can share more detail here if you want the fastest setup\b",
        "If helpful, I can share more detail here",
    ),
    (
        r"\bi can share more detail here if more detail would be useful\b",
        "If helpful, I can share more detail here",
    ),
    (r"\bif you want the fastest setup\b", "if more detail would be useful"),
    (r"\bindustry-leading\b", "well-suited"),
    (r"\bbest-in-class\b", "solid"),
    (r"\bworld-class\b", "useful"),
    (r"\brevolutionary\b", "practical"),
    (r"\bgame-changing\b", "helpful"),
    (r"\bunmatched\b", "strong"),
    (r"\byou(?:'d| would) be crazy\b", "it may be worth considering"),
    (r"\bonly an idiot\b", "it may be easy to miss"),
    (r"\bno excuses\b", ""),
    (r"\byou must\b", "you may want to"),
    (r"\bmust buy\b", "may be worth considering"),
    (r"\bcan'?t afford not to\b", "may be worth evaluating"),
    (r"\bdon'?t miss out\b", "if it seems relevant"),
    (r"\b#1\b", "a strong"),
    (r"\bnumber one\b", "a strong"),
    (r"\bno[- ]risk\b", "lower-risk"),
    (r"\bproven to\b", "can"),
    (r"\bzero effort\b", "less manual effort"),
)

_SAFE_FALLBACK_DRAFT = (
    "A safer version would focus on the user's problem first, offer one or "
    "two practical next steps, and keep any product mention brief and "
    "optional rather than promotional."
)


class ComplianceAgent:
    """Rule-based compliance validator for drafted replies."""

    def __init__(self) -> None:
        self._stats: Counter = Counter()
        logger.info("ComplianceAgent initialised")

    def validate(self, draft_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a single drafted reply and return a safer version when needed.
        """
        if not self._is_valid_input(draft_data):
            result = self._build_result(
                risk_level="reject",
                violations=["invalid_input"],
                safe_draft=_SAFE_FALLBACK_DRAFT,
                recommendation=(
                    "Reject the original payload and rebuild the draft because "
                    "the compliance input was incomplete."
                ),
            )
            self._stats[result["risk_level"]] += 1
            return result

        violations = self._detect_violations(draft_data)
        risk_level = self._risk_level_from_violations(violations)
        safe_draft = self._compose_safe_draft(draft_data, risk_level, violations)
        recommendation = self._recommendation_for(risk_level)

        result = self._build_result(
            risk_level=risk_level,
            violations=violations,
            safe_draft=safe_draft,
            recommendation=recommendation,
        )
        self._stats[risk_level] += 1

        logger.info(
            "Validated draft - risk=%s, approved=%s, violations=%s",
            result["risk_level"],
            result["approved"],
            ", ".join(result["violations"]) if result["violations"] else "none",
        )
        return result

    def validate_batch(self, drafts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate a batch of drafted replies."""
        if not isinstance(drafts, list):
            raise TypeError(f"drafts must be a list, got {type(drafts).__name__}")

        logger.info("Batch compliance validation starting - %d items", len(drafts))
        results = [self.validate(item) for item in drafts]
        self._log_distribution()
        return results

    def _detect_violations(self, draft_data: Dict[str, Any]) -> List[str]:
        draft = self._clean_text(str(draft_data.get("draft", "")))
        cta = self._clean_text(str(draft_data.get("cta", "")))
        combined = f"{draft} {cta}".strip()
        lowered = combined.lower()

        violations: List[str] = []

        if self._count_product_mentions(combined) > 1:
            violations.append("excessive_product_mention")
        if self._matches_any(lowered, _HARD_SELL_PATTERNS):
            violations.append("hard_sell_language")
        if self._matches_any(lowered, _UNSAFE_CLAIM_PATTERNS):
            violations.append("unsafe_claims")
        if self._matches_any(lowered, _PLATFORM_SAFETY_PATTERNS):
            violations.append("platform_unsafe_language")
        if self._matches_any(lowered, _AGGRESSIVE_TONE_PATTERNS):
            violations.append("aggressive_or_manipulative_tone")
        if self._matches_any(lowered, _MISLEADING_CLAIM_PATTERNS):
            violations.append("misleading_claims")
        if self._matches_any(lowered, _EXAGGERATED_CLAIM_PATTERNS):
            violations.append("exaggerated_claims")
        if cta and self._matches_any(cta.lower(), _UNNATURAL_CTA_PATTERNS):
            violations.append("unnatural_cta")
        if self._has_repetitive_phrasing(combined):
            violations.append("spammy_repetition")

        return violations

    def _risk_level_from_violations(self, violations: List[str]) -> str:
        if not violations:
            return "safe"

        severities = [_VIOLATION_SEVERITY.get(item, 1) for item in violations]
        if max(severities) >= 3:
            return "reject"
        return "review"

    def _compose_safe_draft(
        self,
        draft_data: Dict[str, Any],
        risk_level: str,
        violations: List[str],
    ) -> str:
        draft = self._clean_text(str(draft_data.get("draft", "")))
        cta = self._clean_text(str(draft_data.get("cta", "")))

        if risk_level == "safe":
            return self._join_draft_and_cta(draft, cta)

        safe_main = self._sanitize_text(draft)
        safe_main = self._limit_product_mentions(safe_main)
        safe_main = self._dedupe_sentences(safe_main)
        safe_main = self._strip_empty_fragments(safe_main)

        safe_cta = self._soften_cta(cta, risk_level)
        combined = self._join_draft_and_cta(safe_main, safe_cta)

        if len(combined.split()) < 12 or self._contains_high_risk_language(combined):
            combined = self._fallback_from_original(draft, violations)

        return combined

    def _soften_cta(self, cta: str, risk_level: str) -> str:
        cta = self._clean_text(cta)
        if not cta:
            return ""

        softened = self._sanitize_text(cta)
        softened = self._limit_product_mentions(softened)
        lowered = softened.lower()
        had_unnatural_cta = self._matches_any(cta.lower(), _UNNATURAL_CTA_PATTERNS)

        if self._matches_any(lowered, _HARD_SELL_PATTERNS + _PLATFORM_SAFETY_PATTERNS):
            softened = ""

        if not softened:
            return ""

        if had_unnatural_cta:
            softened = "If helpful, it may be worth comparing a few options."
            return self._ensure_terminal_punctuation(softened)

        if not lowered.startswith(("if helpful", "if useful", "if it helps")):
            if risk_level == "review":
                softened = f"If helpful, {softened[:1].lower()}{softened[1:]}"
            else:
                softened = "If helpful, I can share more detail here."

        return self._ensure_terminal_punctuation(softened)

    def _sanitize_text(self, text: str) -> str:
        cleaned = self._clean_text(text)
        for pattern, replacement in _SANITIZE_REPLACEMENTS:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"\b(\w+)(?:\s+\1\b){1,}", r"\1", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
        cleaned = re.sub(r"([.!?]){2,}", r"\1", cleaned)
        return self._clean_text(cleaned)

    def _fallback_from_original(self, draft: str, violations: List[str]) -> str:
        cleaned = self._sanitize_text(draft)
        cleaned = self._limit_product_mentions(cleaned)
        if len(cleaned.split()) >= 12 and not self._contains_high_risk_language(cleaned):
            return self._ensure_terminal_punctuation(cleaned)

        if "unsafe_claims" in violations or "hard_sell_language" in violations:
            return (
                "A safer version would focus on the user's problem first, offer "
                "practical next steps, and mention any tool only if it clearly "
                "helps with the workflow being discussed."
            )

        return _SAFE_FALLBACK_DRAFT

    @staticmethod
    def _build_result(
        risk_level: str,
        violations: List[str],
        safe_draft: str,
        recommendation: str,
    ) -> Dict[str, Any]:
        return {
            "approved": risk_level == "safe",
            "risk_level": risk_level,
            "violations": violations,
            "safe_draft": safe_draft,
            "recommendation": recommendation,
        }

    @staticmethod
    def _recommendation_for(risk_level: str) -> str:
        return {
            "safe": "Draft is clean and can move forward as-is.",
            "review": (
                "Minor promotional tone detected. Use the softened version before "
                "human review."
            ),
            "reject": (
                "Reject the original draft as written and use the safer rewrite "
                "before any further review."
            ),
        }[risk_level]

    @staticmethod
    def _is_valid_input(draft_data: Any) -> bool:
        if not isinstance(draft_data, dict):
            return False
        for key in _REQUIRED_KEYS:
            if key not in draft_data:
                return False
        return bool(str(draft_data.get("draft", "")).strip())

    @staticmethod
    def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _contains_high_risk_language(text: str) -> bool:
        lowered = text.lower()
        return ComplianceAgent._matches_any(
            lowered,
            _HARD_SELL_PATTERNS + _UNSAFE_CLAIM_PATTERNS + _PLATFORM_SAFETY_PATTERNS,
        )

    @staticmethod
    def _count_product_mentions(text: str) -> int:
        return len(re.findall(r"\bsignalforge\b", text, flags=re.IGNORECASE))

    @staticmethod
    def _has_repetitive_phrasing(text: str) -> bool:
        normalised = re.sub(r"\s+", " ", text).strip().lower()
        if not normalised:
            return False

        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", normalised)
            if sentence.strip()
        ]
        if len(sentences) != len(set(sentences)):
            return True

        phrases = re.findall(r"\b\w+\s+\w+\s+\w+\b", normalised)
        counts = Counter(phrases)
        return any(count >= 2 for count in counts.values())

    @staticmethod
    def _join_draft_and_cta(draft: str, cta: str) -> str:
        draft = ComplianceAgent._ensure_terminal_punctuation(
            ComplianceAgent._sentence_case(ComplianceAgent._clean_text(draft))
        )
        cta = ComplianceAgent._ensure_terminal_punctuation(
            ComplianceAgent._sentence_case(ComplianceAgent._clean_text(cta))
        )
        if not cta or cta.lower() in draft.lower():
            return draft
        if not draft:
            return cta
        return f"{draft} {cta}"

    @staticmethod
    def _limit_product_mentions(text: str) -> str:
        count = 0

        def replacer(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return "SignalForge" if count == 1 else "the tool"

        return re.sub(r"\bsignalforge\b", replacer, text, flags=re.IGNORECASE)

    @staticmethod
    def _dedupe_sentences(text: str) -> str:
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", text)
            if sentence.strip()
        ]
        seen = set()
        unique: List[str] = []
        for sentence in sentences:
            key = sentence.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(sentence)
        return " ".join(unique) if unique else text

    @staticmethod
    def _strip_empty_fragments(text: str) -> str:
        cleaned = re.sub(r"\s{2,}", " ", text)
        cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
        cleaned = re.sub(r"\(\s*\)", "", cleaned)
        return ComplianceAgent._clean_text(cleaned)

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", str(text)).strip()

    @staticmethod
    def _ensure_terminal_punctuation(text: str) -> str:
        text = ComplianceAgent._clean_text(text)
        if not text:
            return text
        if text[-1] not in ".!?":
            return text + "."
        return text

    @staticmethod
    def _sentence_case(text: str) -> str:
        text = ComplianceAgent._clean_text(text)
        if not text:
            return text
        return text[:1].upper() + text[1:]

    def _log_distribution(self) -> None:
        total = sum(self._stats.values())
        if total == 0:
            return

        logger.info("--- Compliance Distribution (%d total) ---", total)
        for risk_level in ["safe", "review", "reject"]:
            logger.info("  %-8s %3d", risk_level, self._stats.get(risk_level, 0))

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def reset_stats(self) -> None:
        self._stats.clear()

    def __repr__(self) -> str:
        return (
            f"<ComplianceAgent validated={sum(self._stats.values())}>"
        )
