"""Semantic relevance and product-fit gates for discovered opportunities."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "into",
    "is",
    "it",
    "its",
    "my",
    "need",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "this",
    "to",
    "us",
    "we",
    "with",
    "you",
    "your",
}

_SYNONYMS = {
    "ai": {"ai", "artificial", "intelligence", "gpt", "llm", "agent", "agents", "chatgpt"},
    "automation": {"automation", "automate", "automating", "automated", "zapier", "n8n", "make", "webhook", "trigger"},
    "workflow": {"workflow", "workflows", "process", "pipeline", "operations", "ops", "system"},
    "business": {"business", "businesses", "company", "companies", "team", "teams", "startup", "saas", "agency"},
    "social": {"social", "media", "reddit", "linkedin", "community", "engagement", "comments", "content"},
    "lead": {"lead", "leads", "prospect", "prospects", "outreach", "sales", "pipeline", "qualification"},
    "scale": {"scale", "scaling", "growth", "growing", "bottleneck", "bottlenecks"},
}

_BUSINESS_CONTEXT_TERMS = {
    "agency",
    "business",
    "client",
    "clients",
    "company",
    "founder",
    "lead",
    "leads",
    "marketing",
    "operations",
    "outreach",
    "pipeline",
    "product",
    "sales",
    "saas",
    "startup",
    "team",
    "workflow",
}

_PAIN_OR_BUYING_TERMS = {
    "alternative",
    "annoying",
    "best",
    "bottleneck",
    "bottlenecks",
    "broken",
    "challenge",
    "compare",
    "comparison",
    "doesnt",
    "frustrated",
    "help",
    "inefficient",
    "issue",
    "manual",
    "problem",
    "recommend",
    "recommendation",
    "repetitive",
    "scale",
    "slow",
    "struggle",
    "struggling",
    "stuck",
    "tedious",
    "tool",
    "tools",
    "waste",
    "wish",
}

_NOISE_TOPICS: Dict[str, Sequence[str]] = {
    "politics": (
        "biden",
        "campaign",
        "congress",
        "election",
        "government",
        "minister",
        "politics",
        "president",
        "senate",
        "trump",
        "vote",
    ),
    "gaming": (
        "xbox",
        "playstation",
        "nintendo",
        "minecraft",
        "fortnite",
        "game",
        "gaming",
        "steam",
        "fps",
        "rpg",
    ),
    "meme": (
        "lol",
        "lmao",
        "meme",
        "shitpost",
        "upvote",
        "karma",
        "funny",
        "joke",
    ),
    "student_exam": (
        "assignment",
        "college",
        "exam",
        "homework",
        "paper",
        "school",
        "student",
        "syllabus",
        "university",
    ),
    "news": (
        "breaking",
        "headline",
        "lawsuit",
        "press",
        "rumor",
        "stock",
        "trading",
    ),
}

_CAPABILITY_TERMS: Dict[str, Sequence[str]] = {
    "social_media_workflows": (
        "social",
        "media",
        "reddit",
        "community",
        "engagement",
        "comments",
        "conversation",
        "content",
        "reply",
        "responses",
    ),
    "outreach": (
        "outreach",
        "cold",
        "email",
        "linkedin",
        "reply",
        "sequence",
        "prospect",
    ),
    "automation": (
        "automation",
        "automate",
        "automating",
        "workflow",
        "manual",
        "repetitive",
        "pipeline",
        "n8n",
        "zapier",
    ),
    "saas_scaling": (
        "saas",
        "startup",
        "founder",
        "scale",
        "scaling",
        "growth",
        "client",
        "clients",
    ),
    "lead_generation": (
        "lead",
        "leads",
        "prospect",
        "prospects",
        "sales",
        "qualification",
        "pipeline",
    ),
}


@dataclass(frozen=True)
class RelevanceResult:
    score: float
    accepted: bool
    reason: str
    noise_topic: str = ""


def filter_by_semantic_relevance(
    posts: Iterable[Dict[str, Any]],
    original_intent: str,
    *,
    threshold: float = 0.24,
) -> List[Dict[str, Any]]:
    """Return posts that match the user's original search intent."""
    gate = SemanticRelevanceFilter(original_intent, threshold=threshold)
    out: List[Dict[str, Any]] = []
    for post in posts:
        result = gate.score(post)
        if not result.accepted:
            continue
        fit_score, matches = company_capability_fit(post)
        enriched = {
            **post,
            "semantic_relevance_score": result.score,
            "semantic_relevance_reason": result.reason,
            "knowledge_fit_score": fit_score,
            "knowledge_capability_matches": matches,
        }
        out.append(enriched)
    return out


class SemanticRelevanceFilter:
    """Fast deterministic semantic gate for scanner results."""

    def __init__(self, original_intent: str, *, threshold: float = 0.24) -> None:
        self.original_intent = str(original_intent or "").strip()
        self.threshold = threshold
        self._intent_terms = _expand_terms(_tokens(self.original_intent))
        self._intent_phrases = _phrases(self.original_intent)

    def score(self, post: Dict[str, Any]) -> RelevanceResult:
        text = _post_text(post)
        if not text:
            return RelevanceResult(0.0, False, "empty_text")

        noise_topic = _noise_topic(text)
        post_terms = _expand_terms(_tokens(text))
        if not post_terms:
            return RelevanceResult(0.0, False, "empty_terms")

        overlap = self._intent_terms & post_terms
        coverage = len(overlap) / max(len(self._intent_terms), 1)
        density = len(overlap) / math.sqrt(max(len(post_terms), 1))

        phrase_hits = sum(1 for phrase in self._intent_phrases if phrase in text)
        phrase_score = min(0.2, phrase_hits * 0.08)

        business_score = min(
            0.25,
            len(post_terms & _BUSINESS_CONTEXT_TERMS) * 0.035,
        )
        pain_score = min(0.25, len(post_terms & _PAIN_OR_BUYING_TERMS) * 0.04)
        fit_score, _ = company_capability_fit(post)

        score = (
            coverage * 0.4
            + density * 0.2
            + phrase_score
            + business_score
            + pain_score
            + fit_score * 0.18
        )

        if noise_topic:
            strong_business_match = (
                len(post_terms & _BUSINESS_CONTEXT_TERMS) >= 2
                and len(post_terms & _PAIN_OR_BUYING_TERMS) >= 1
            )
            if not strong_business_match:
                return RelevanceResult(
                    round(min(score, 1.0), 3),
                    False,
                    f"noise_topic:{noise_topic}",
                    noise_topic,
                )
            score -= 0.12

        accepted = score >= self.threshold
        reason = "semantic_match" if accepted else "semantic_score_below_threshold"
        return RelevanceResult(round(min(max(score, 0.0), 1.0), 3), accepted, reason, noise_topic)


def company_capability_fit(post: Dict[str, Any] | str) -> Tuple[float, List[str]]:
    """Estimate how strongly SignalForge capabilities fit the opportunity."""
    if isinstance(post, str):
        text = post
    else:
        text = _post_text(post)
    terms = set(_tokens(text))

    matches: List[str] = []
    raw_score = 0.0
    for capability, keywords in _CAPABILITY_TERMS.items():
        hit_count = sum(1 for keyword in keywords if keyword in terms or keyword in text)
        if hit_count:
            matches.append(capability)
            raw_score += min(0.22, 0.07 * hit_count)

    return round(min(raw_score, 1.0), 3), matches


def _post_text(post: Dict[str, Any]) -> str:
    tags = post.get("tags", []) or []
    if isinstance(tags, str):
        tag_text = tags
    else:
        tag_text = " ".join(str(tag) for tag in tags if tag)
    parts = [
        post.get("title", ""),
        post.get("body", ""),
        post.get("summary", ""),
        post.get("topic", ""),
        post.get("subreddit", ""),
        tag_text,
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _tokens(text: str) -> List[str]:
    tokens: List[str] = []
    for raw in _TOKEN_PATTERN.findall(str(text or "").lower()):
        token = _stem(raw)
        if len(token) <= 2 or token in _STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _expand_terms(tokens: Iterable[str]) -> set[str]:
    terms = set(tokens)
    for token in list(terms):
        for key, synonyms in _SYNONYMS.items():
            if token == key or token in synonyms:
                terms.update(_stem(item) for item in synonyms)
    return terms


def _phrases(text: str) -> List[str]:
    lowered = str(text or "").lower()
    tokens = _tokens(lowered)
    phrases: List[str] = []
    if len(tokens) >= 2:
        for idx in range(len(tokens) - 1):
            phrases.append(f"{tokens[idx]} {tokens[idx + 1]}")
    if len(tokens) >= 3:
        for idx in range(len(tokens) - 2):
            phrases.append(f"{tokens[idx]} {tokens[idx + 1]} {tokens[idx + 2]}")
    return phrases


def _noise_topic(text: str) -> str:
    terms = set(_tokens(text))
    for topic, keywords in _NOISE_TOPICS.items():
        if any(keyword in terms or keyword in text for keyword in keywords):
            return topic
    return ""


def _stem(token: str) -> str:
    token = token.lower().replace("'", "")
    replacements = {
        "doesn": "doesnt",
        "workflows": "workflow",
        "processes": "process",
        "companies": "company",
        "businesses": "business",
    }
    if token in replacements:
        return replacements[token]
    for suffix in ("ing", "ers", "ies", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            if suffix == "ies":
                return token[: -len(suffix)] + "y"
            return token[: -len(suffix)]
    return token
