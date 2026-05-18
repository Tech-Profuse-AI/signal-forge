"""Intent-driven search query extraction for scanner platforms.

The scanner used to normalize a query by splitting it into tokens and then
searching individual words.  That creates broad, low-intent searches like
``ai`` or ``workflow``.  This module keeps the public ``normalize_*`` helpers
for compatibility, but they now return semantic opportunity phrases only.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional, Sequence


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

_INTENT_PREFIX_RE = re.compile(
    r"^\s*(?:i am|i'm|we are|we're)?\s*"
    r"(?:looking for|need(?:ing)?|want(?:ing)?|searching for|find(?:ing)?|"
    r"recommend(?:ing)?|research(?:ing)?|interested in)\s+",
    re.IGNORECASE,
)

_STOPWORDS = {
    "a",
    "about",
    "all",
    "also",
    "an",
    "and",
    "any",
    "anyone",
    "are",
    "around",
    "as",
    "at",
    "be",
    "best",
    "can",
    "company",
    "companies",
    "do",
    "does",
    "for",
    "from",
    "get",
    "getting",
    "good",
    "has",
    "have",
    "help",
    "how",
    "i",
    "in",
    "is",
    "it",
    "looking",
    "me",
    "my",
    "need",
    "needs",
    "of",
    "on",
    "our",
    "people",
    "please",
    "recommend",
    "recommendation",
    "recommendations",
    "should",
    "someone",
    "some",
    "team",
    "teams",
    "that",
    "the",
    "their",
    "this",
    "to",
    "use",
    "using",
    "users",
    "want",
    "way",
    "ways",
    "we",
    "what",
    "where",
    "which",
    "who",
    "with",
}

_GENERIC_STANDALONE_TERMS = {
    "ai",
    "automation",
    "automate",
    "workflow",
    "workflows",
    "business",
    "businesses",
    "tool",
    "tools",
    "software",
    "productivity",
    "startup",
    "startups",
    "saas",
    "marketing",
    "sales",
    "process",
    "processes",
}

_CATEGORY_KEYWORDS: Dict[str, Sequence[str]] = {
    "social_media_workflows": (
        "social",
        "media",
        "reddit",
        "community",
        "engagement",
        "content",
        "caption",
        "post",
        "comments",
    ),
    "outreach": (
        "outreach",
        "cold",
        "email",
        "linkedin",
        "prospect",
        "reply",
        "sequence",
    ),
    "lead_generation": (
        "lead",
        "leads",
        "prospect",
        "pipeline",
        "qualification",
        "sales",
    ),
    "saas_scaling": (
        "saas",
        "startup",
        "startups",
        "founder",
        "scale",
        "scaling",
        "client",
        "clients",
    ),
    "workflow_automation": (
        "workflow",
        "workflows",
        "automation",
        "automate",
        "automating",
        "manual",
        "repetitive",
        "process",
        "operations",
        "ops",
    ),
    "ai_agents": (
        "ai",
        "agent",
        "agents",
        "llm",
        "gpt",
        "chatgpt",
        "autonomous",
    ),
}

_PLATFORM_BASE_CONFIDENCE = {
    "reddit": 0.88,
    "quora": 0.86,
    "medium": 0.84,
    "generic": 0.82,
}


@dataclass(frozen=True)
class QueryCandidate:
    """A scored semantic query candidate."""

    text: str
    confidence: float
    relevance_category: str
    platform_suitability: Dict[str, float]
    source_intent: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @property
    def is_executable(self) -> bool:
        return bool(self.text) and not is_generic_standalone_query(self.text)


class QueryIntentExtractor:
    """Build compact, intent-preserving search plans from natural language."""

    def __init__(self, min_confidence: float = 0.58) -> None:
        self.min_confidence = min_confidence

    def extract(
        self,
        query: str,
        *,
        platform: Optional[str] = None,
        max_queries: int = 5,
        min_confidence: Optional[float] = None,
    ) -> List[QueryCandidate]:
        """Return 3-5 semantic query candidates for the user intent."""
        clean = _clean_query(query)
        if not clean:
            return []

        target_platform = (platform or "generic").lower()
        confidence_floor = (
            self.min_confidence if min_confidence is None else min_confidence
        )
        categories = _infer_categories(clean)
        primary_category = categories[0] if categories else "workflow_automation"
        base_phrase = _intent_phrase(clean, primary_category)

        raw_candidates = self._platform_templates(
            base_phrase=base_phrase,
            clean_query=clean,
            categories=categories,
            platform=target_platform,
        )

        candidates: List[QueryCandidate] = []
        seen: set[str] = set()
        for text, confidence, category in raw_candidates:
            display = _display_query(text)
            key = display.lower()
            if key in seen or is_generic_standalone_query(display):
                continue
            seen.add(key)
            suitability = _platform_suitability(category, target_platform)
            candidate = QueryCandidate(
                text=display,
                confidence=round(max(0.0, min(1.0, confidence)), 2),
                relevance_category=category,
                platform_suitability=suitability,
                source_intent=_display_query(base_phrase),
            )
            if candidate.confidence >= confidence_floor and candidate.is_executable:
                candidates.append(candidate)
            if len(candidates) >= max_queries:
                break

        return candidates

    def texts(
        self,
        query: str,
        *,
        platform: Optional[str] = None,
        max_queries: int = 5,
        min_confidence: Optional[float] = None,
    ) -> List[str]:
        return [
            item.text
            for item in self.extract(
                query,
                platform=platform,
                max_queries=max_queries,
                min_confidence=min_confidence,
            )
        ]

    def _platform_templates(
        self,
        *,
        base_phrase: str,
        clean_query: str,
        categories: Sequence[str],
        platform: str,
    ) -> List[tuple[str, float, str]]:
        if platform == "reddit":
            return self._reddit_templates(base_phrase, categories)
        if platform == "quora":
            return self._quora_templates(base_phrase, categories)
        if platform == "medium":
            return self._medium_templates(base_phrase, categories)
        return self._generic_templates(base_phrase, clean_query, categories)

    def _generic_templates(
        self,
        base_phrase: str,
        clean_query: str,
        categories: Sequence[str],
    ) -> List[tuple[str, float, str]]:
        primary = categories[0] if categories else "workflow_automation"
        candidates = [
            (f"{base_phrase} for businesses", 0.9, "buying_intent"),
            (_automation_phrase(base_phrase), 0.86, "workflow_automation"),
            (_pain_phrase(base_phrase), 0.82, "pain_point"),
            (_startup_struggle_phrase(base_phrase), 0.78, "saas_scaling"),
        ]
        if "lead_generation" in categories:
            candidates.insert(1, ("lead generation workflow automation pain points", 0.86, "lead_generation"))
        if "social_media_workflows" in categories:
            candidates.insert(1, ("social media engagement workflow bottlenecks", 0.86, "social_media_workflows"))
        if primary == "ai_agents":
            candidates.append(("AI agent implementation struggles for startups", 0.76, "ai_agents"))
        return candidates

    def _reddit_templates(
        self,
        base_phrase: str,
        categories: Sequence[str],
    ) -> List[tuple[str, float, str]]:
        candidates = [
            (_manual_problem_phrase(base_phrase), 0.9, "pain_point"),
            (_client_workflow_phrase(base_phrase), 0.87, "workflow_automation"),
            (f"{base_phrase} for SaaS", 0.84, "saas_scaling"),
            (_founder_bottleneck_phrase(base_phrase), 0.8, "saas_scaling"),
        ]
        if "social_media_workflows" in categories:
            candidates[:0] = [
                ("manual social media engagement workflow problems", 0.91, "social_media_workflows"),
                ("reddit engagement automation bottlenecks", 0.86, "social_media_workflows"),
            ]
        if "lead_generation" in categories or "outreach" in categories:
            candidates[:0] = [
                ("manual lead generation outreach workflow problems", 0.91, "lead_generation"),
                ("SaaS outbound automation struggles", 0.84, "outreach"),
            ]
        if "ai_agents" in categories:
            candidates.append(("AI automation implementation pain points", 0.79, "ai_agents"))
        return candidates

    def _quora_templates(
        self,
        base_phrase: str,
        categories: Sequence[str],
    ) -> List[tuple[str, float, str]]:
        candidates = [
            (f"how to implement {base_phrase} in business operations", 0.89, "workflow_automation"),
            (_best_tool_phrase(base_phrase), 0.86, "buying_intent"),
            (_implementation_problem_phrase(base_phrase), 0.83, "pain_point"),
            (_inefficiency_phrase(base_phrase), 0.78, "workflow_automation"),
        ]
        if "social_media_workflows" in categories:
            candidates[:0] = [
                ("how to automate social media engagement workflows", 0.9, "social_media_workflows"),
                ("best tools for monitoring Reddit conversations for business", 0.84, "buying_intent"),
            ]
        if "lead_generation" in categories or "outreach" in categories:
            candidates[:0] = [
                ("how to automate lead generation outreach workflows", 0.9, "lead_generation"),
                ("best outreach automation tools for B2B SaaS", 0.84, "buying_intent"),
            ]
        return candidates

    def _medium_templates(
        self,
        base_phrase: str,
        categories: Sequence[str],
    ) -> List[tuple[str, float, str]]:
        candidates = [
            (f"{base_phrase} case study", 0.88, "case_study"),
            (f"operational {base_phrase} architecture", 0.84, "workflow_automation"),
            (_productivity_system_phrase(base_phrase), 0.8, "workflow_automation"),
            (_lessons_learned_phrase(base_phrase), 0.77, "pain_point"),
        ]
        if "social_media_workflows" in categories:
            candidates[:0] = [
                ("social media workflow automation case study", 0.9, "social_media_workflows"),
                ("community engagement automation architecture", 0.84, "social_media_workflows"),
            ]
        if "lead_generation" in categories or "outreach" in categories:
            candidates[:0] = [
                ("AI lead generation automation case study", 0.9, "lead_generation"),
                ("B2B outreach automation workflow architecture", 0.84, "outreach"),
            ]
        return candidates


def normalize_query(query: str, *, max_terms: int = 5) -> str:
    """Return the highest-confidence semantic query for compatibility."""
    del max_terms
    candidates = QueryIntentExtractor().extract(str(query or ""), max_queries=1)
    if candidates:
        return candidates[0].text
    clean = _display_query(_clean_query(query))
    return "" if is_generic_standalone_query(clean) else clean


def normalize_queries(queries: Iterable[str] | str | None) -> List[str]:
    """Normalize and deduplicate scanner queries without token expansion."""
    if not queries:
        return []
    if isinstance(queries, str):
        queries = [queries]

    extractor = QueryIntentExtractor()
    out: List[str] = []
    for query in queries:
        for candidate in extractor.extract(str(query), max_queries=5):
            if candidate.text not in out:
                out.append(candidate.text)
            if len(out) >= 5:
                break
    return out


def platform_query_candidates(
    queries: Iterable[str] | str | None,
    *,
    platform: str,
    max_queries: int = 5,
    min_confidence: float = 0.58,
) -> List[QueryCandidate]:
    """Return platform-specific scored query candidates."""
    if not queries:
        return []
    if isinstance(queries, str):
        queries = [queries]

    extractor = QueryIntentExtractor(min_confidence=min_confidence)
    out: List[QueryCandidate] = []
    seen: set[str] = set()
    for query in queries:
        for candidate in extractor.extract(
            str(query),
            platform=platform,
            max_queries=max_queries,
            min_confidence=min_confidence,
        ):
            key = candidate.text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(candidate)
            if len(out) >= max_queries:
                return out
    return out


def platform_queries(
    queries: Iterable[str] | str | None,
    *,
    platform: str,
    max_queries: int = 5,
    min_confidence: float = 0.58,
) -> List[str]:
    """Return executable platform-specific query texts."""
    return [
        candidate.text
        for candidate in platform_query_candidates(
            queries,
            platform=platform,
            max_queries=max_queries,
            min_confidence=min_confidence,
        )
    ]


def is_generic_standalone_query(query: str) -> bool:
    """Reject broad one-word searches like ``ai`` or ``automation``."""
    tokens = _TOKEN_PATTERN.findall(str(query or "").lower())
    return len(tokens) == 1 and tokens[0] in _GENERIC_STANDALONE_TERMS


def query_plan_summary(candidates: Sequence[QueryCandidate]) -> List[Dict[str, object]]:
    """Small helper for logs, API payloads, and tests."""
    return [candidate.to_dict() for candidate in candidates]


def _clean_query(query: str) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    text = re.sub(r"https?://\S+", " ", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^A-Za-z0-9\s./+-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _INTENT_PREFIX_RE.sub("", text).strip()
    return text


def _intent_phrase(clean_query: str, primary_category: str) -> str:
    tokens = _TOKEN_PATTERN.findall(clean_query.lower())
    meaningful = [token for token in tokens if token not in _STOPWORDS]
    if len(meaningful) >= 2:
        return " ".join(meaningful[:6])

    if not meaningful:
        return "workflow automation"

    token = meaningful[0]
    if token not in _GENERIC_STANDALONE_TERMS:
        return token

    category_defaults = {
        "social_media_workflows": "social media workflow automation",
        "outreach": "outreach workflow automation",
        "lead_generation": "lead generation workflow automation",
        "saas_scaling": "SaaS workflow automation",
        "ai_agents": "AI agent workflow automation",
        "workflow_automation": "business workflow automation",
    }
    return category_defaults.get(primary_category, "business workflow automation")


def _infer_categories(clean_query: str) -> List[str]:
    text = clean_query.lower()
    tokens = set(_TOKEN_PATTERN.findall(text))
    scored: List[tuple[int, str]] = []
    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in tokens or keyword in text)
        if score:
            scored.append((score, category))

    scored.sort(key=lambda item: (-item[0], item[1]))
    categories = [category for _, category in scored]
    if "workflow_automation" not in categories:
        categories.append("workflow_automation")
    return categories


def _platform_suitability(category: str, platform: str) -> Dict[str, float]:
    base = {
        "reddit": 0.68,
        "quora": 0.68,
        "medium": 0.68,
    }
    if category in {"pain_point", "saas_scaling", "social_media_workflows", "outreach"}:
        base["reddit"] += 0.2
    if category in {"buying_intent", "workflow_automation", "lead_generation"}:
        base["quora"] += 0.18
    if category in {"case_study", "workflow_automation", "ai_agents"}:
        base["medium"] += 0.18
    if platform in base:
        base[platform] = max(base[platform], _PLATFORM_BASE_CONFIDENCE.get(platform, 0.82))
    return {key: round(min(value, 1.0), 2) for key, value in base.items()}


def _display_query(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    replacements = {
        " ai ": " AI ",
        " ai": " AI",
        "ai ": "AI ",
        " saas ": " SaaS ",
        " saas": " SaaS",
        "saas ": "SaaS ",
        " b2b ": " B2B ",
        " b2b": " B2B",
        "b2b ": "B2B ",
        " crm ": " CRM ",
        " crm": " CRM",
        "crm ": "CRM ",
    }
    padded = f" {cleaned} "
    for needle, repl in replacements.items():
        padded = padded.replace(needle, repl)
    return re.sub(r"\s+", " ", padded).strip()


def _automation_phrase(base_phrase: str) -> str:
    if "workflow" in base_phrase.lower():
        return "automating repetitive business workflows"
    return f"automating repetitive {base_phrase} tasks"


def _pain_phrase(base_phrase: str) -> str:
    if "ai" in base_phrase.lower() and "automation" in base_phrase.lower():
        return "AI automation pain points"
    return f"{base_phrase} pain points"


def _startup_struggle_phrase(base_phrase: str) -> str:
    if "workflow" in base_phrase.lower():
        return "startup workflow automation struggles"
    return f"startup {base_phrase} struggles"


def _manual_problem_phrase(base_phrase: str) -> str:
    if "workflow" in base_phrase.lower():
        return "manual workflow problems"
    return f"manual {base_phrase} problems"


def _client_workflow_phrase(base_phrase: str) -> str:
    if "workflow" in base_phrase.lower():
        return "automating client workflows"
    return f"automating client {base_phrase}"


def _founder_bottleneck_phrase(base_phrase: str) -> str:
    return f"{base_phrase} bottlenecks for founders"


def _best_tool_phrase(base_phrase: str) -> str:
    return f"best {base_phrase} tools for SaaS operations"


def _implementation_problem_phrase(base_phrase: str) -> str:
    return f"{base_phrase} implementation problems"


def _inefficiency_phrase(base_phrase: str) -> str:
    return f"manual workflow inefficiencies in {base_phrase}"


def _productivity_system_phrase(base_phrase: str) -> str:
    return f"productivity systems for {base_phrase}"


def _lessons_learned_phrase(base_phrase: str) -> str:
    return f"{base_phrase} lessons learned"

