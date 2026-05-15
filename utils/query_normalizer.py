"""Query normalization helpers for scanner search terms."""

from __future__ import annotations

import re
from typing import Iterable, List


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

_KEEP_WORDS = {
    "ai",
    "agent",
    "agents",
    "automation",
    "automate",
    "automating",
    "content",
    "crm",
    "engagement",
    "lead",
    "marketing",
    "media",
    "moderation",
    "productivity",
    "reddit",
    "sales",
    "scheduling",
    "social",
    "tool",
    "tools",
    "workflow",
    "workflows",
}


def normalize_query(query: str, *, max_terms: int = 5) -> str:
    """Reduce conversational search text into scanner-friendly keywords."""
    text = str(query or "").strip().lower()
    if not text:
        return ""

    text = re.sub(r"https?://\S+", " ", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # If the user phrased the query as intent, keep the object of intent.
    intent_match = re.search(
        r"\b(?:looking for|need(?:ing)?|want(?:ing)?|searching for|recommend(?:ing)?)\b\s+(.+)",
        text,
    )
    if intent_match:
        text = intent_match.group(1).strip()

    tokens = [token for token in re.split(r"[\s-]+", text) if token]
    kept: List[str] = []
    for token in tokens:
        if token in _KEEP_WORDS or token not in _STOPWORDS:
            if token not in kept:
                kept.append(token)
        if len(kept) >= max_terms:
            break

    if not kept:
        kept = [token for token in tokens if token not in _STOPWORDS][:max_terms]

    return " ".join(kept) if kept else text


def normalize_queries(queries: Iterable[str] | str | None) -> List[str]:
    """Normalize and deduplicate a list of scanner queries."""
    if not queries:
        return []
    if isinstance(queries, str):
        queries = [queries]

    out: List[str] = []
    for query in queries:
        normalised = normalize_query(str(query))
        if normalised and normalised not in out:
            out.append(normalised)
        tokens = normalised.split()
        if len(tokens) > 2:
            if "social" in tokens and "media" in tokens and "social media" not in out:
                out.append("social media")
            for token in tokens:
                if token in _KEEP_WORDS and token not in {"tool", "tools"}:
                    if token not in out:
                        out.append(token)
                if len(out) >= 5:
                    break
    return out
