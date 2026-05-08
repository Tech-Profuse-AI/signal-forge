"""
SignalForge Quora Scanner Agent.

Orchestrates the full Quora discovery pipeline:
  1. Fetch questions via QuoraProvider (mock or live)
  2. Normalise into the unified schema
  3. Deduplicate via CacheManager
  4. Filter via OpportunityFilter
  5. Extract & annotate opportunity signals

Quora-specific signals detected:
  - help_request
  - recommendation_request
  - pain_point
  - hiring_intent
  - bottleneck

Usage::

    # Mock mode (no network)
    scanner = QuoraScannerAgent(force_mock=True)
    results = scanner.scan(["best CRM for startups", "automation workflow"])

    # Live mode
    from providers.quora_provider import QuoraProvider
    provider = QuoraProvider(serp_api_key="YOUR_KEY")
    scanner = QuoraScannerAgent(quora_provider=provider)
    results = scanner.scan(["pain point project management"])
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from agents.opportunity_scanner.cache_manager import CacheManager
from agents.opportunity_scanner.filters import OpportunityFilter, FilterConfig
from providers.quora_provider import QuoraProvider

logger = logging.getLogger("signalforge.quora_scanner")


# ── Quora-specific signal keywords ───────────────────────────────────

_SIGNAL_PATTERNS: Dict[str, List[str]] = {
    "help_request": [
        "how do i", "how to", "help with", "need help", "struggling with",
        "can someone explain", "what is the best way", "is there a way",
        "does anyone know", "how do you", "what should i", "confused about",
        "stuck on", "issue with", "problem with", "how can i",
    ],
    "recommendation_request": [
        "recommend", "suggestion", "best tool", "what tool", "looking for",
        "any good", "what do you use", "alternative to", "which one",
        "comparison", "vs", "better than", "should i use", "worth it",
        "what software", "what service", "top ", "best ",
    ],
    "pain_point": [
        "pain point", "frustrat", "annoying", "broken", "doesn't work",
        "hate that", "wish there was", "rant", "vent", "unsustainable",
        "killing my", "waste of time", "too slow", "too expensive",
        "not working", "failing", "terrible", "awful", "horrible",
        "disadvantage", "drawback", "limitation",
    ],
    "hiring_intent": [
        "hiring", "looking to hire", "job posting", "job opening",
        "we are hiring", "join our team", "freelancer needed",
        "contractor needed", "consultant needed", "seeking a",
        "opening for", "position available",
    ],
    "bottleneck": [
        "bottleneck", "workflow", "automat", "manual process",
        "takes too long", "time consuming", "at scale",
        "can't keep up", "doesn't scale", "inefficient",
        "tedious", "repetitive task", "hours per day",
        "overhead", "slowing us down", "too much time",
    ],
}


def _detect_quora_signals(post: Dict[str, Any]) -> List[str]:
    """
    Detect opportunity signals specific to Quora Q&A format.

    Returns a list of matched signal names.
    """
    text = (
        post.get("title", "") + " " + post.get("body", "")
    ).lower()

    signals: List[str] = []
    for signal_name, keywords in _SIGNAL_PATTERNS.items():
        if any(kw in text for kw in keywords):
            signals.append(signal_name)

    return signals


class QuoraScannerAgent:
    """
    High-level agent that orchestrates Quora opportunity discovery.

    Reuses CacheManager and OpportunityFilter from the Reddit pipeline
    to maintain a consistent cross-platform deduplication and filtering
    strategy.

    Args:
        quora_provider: A QuoraProvider instance. If None, mock mode
                        is activated automatically.
        force_mock:     Force mock mode regardless of provider.
        filter_config:  Custom FilterConfig for OpportunityFilter.
        cache_dir:      Directory for CacheManager persistence.
        cache_filename: JSON filename used by CacheManager.
        keywords:       Default keyword list for scan().
    """

    def __init__(
        self,
        quora_provider: Optional[QuoraProvider] = None,
        force_mock: bool = False,
        filter_config: Optional[FilterConfig] = None,
        cache_dir: Optional[str] = None,
        cache_filename: str = "seen_quora_posts.json",
        keywords: Optional[List[str]] = None,
    ) -> None:
        # ── Provider ──────────────────────────────────────────────────
        if force_mock or quora_provider is None:
            self._provider = QuoraProvider(mock_mode=True)
            self._mode = "mock"
        else:
            self._provider = quora_provider
            self._mode = "live"

        # ── Sub-components ────────────────────────────────────────────
        self._cache = CacheManager(
            cache_dir=cache_dir,
            cache_filename=cache_filename,
            max_age_days=7,
        )
        self._filter = OpportunityFilter(config=filter_config)

        self.default_keywords = keywords or [
            "social media automation",
            "workflow tools",
        ]
        self.stats = {"fetched": 0, "deduped": 0, "filtered": 0, "approved": 0}

        logger.info(
            "QuoraScannerAgent ready — mode=%s, cache=%d seen",
            self._mode, self._cache.size,
        )

    # ── Public API ────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    def scan(
        self,
        keywords: Optional[List[str]] = None,
        limit_per_keyword: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Run the full pipeline: fetch → normalise → deduplicate → filter → signal.

        Args:
            keywords:          Search terms. Uses defaults if None.
            limit_per_keyword: Max results per keyword.

        Returns:
            List of filtered, deduplicated opportunity dicts, each
            annotated with ``"opportunity_signals"``.
        """
        kw = keywords or self.default_keywords
        logger.info("QuoraScannerAgent.scan() — keywords=%s", kw)

        # 1. Fetch
        raw_posts = self._fetch_all(kw, limit_per_keyword)
        self.stats["fetched"] += len(raw_posts)
        logger.info("Raw Quora posts fetched: %d", len(raw_posts))

        # 2. Normalise (provider already normalises; this ensures schema)
        normalised = self._normalise(raw_posts)

        # 3. Deduplicate
        deduped = self._deduplicate(normalised)
        self.stats["deduped"] += len(deduped)
        logger.info("After dedup: %d posts", len(deduped))

        # 4. Filter via OpportunityFilter
        #    Quora posts don't have subreddits — pass through the platform-
        #    agnostic filter then re-detect with Quora-specific signals.
        filtered = self._filter_quora(deduped)
        self.stats["filtered"] += len(filtered)
        logger.info("After filter: %d posts", len(filtered))

        # 5. Mark seen
        new_ids = [p["id"] for p in filtered if p.get("id")]
        self._cache.mark_seen_batch(new_ids)
        self.stats["approved"] += len(filtered)

        return filtered

    def generate_report(
        self, opportunities: List[Dict[str, Any]]
    ) -> str:
        """Build a readable summary of discovered Quora opportunities."""
        if not opportunities:
            return "No Quora opportunities found in this scan."

        lines = [
            f"# Quora Opportunity Scan Report — {len(opportunities)} found",
            "",
        ]
        for i, opp in enumerate(opportunities, 1):
            signals = ", ".join(opp.get("opportunity_signals", []))
            lines.append(f"## {i}. {opp.get('title', 'Untitled')}")
            lines.append(f"- **Platform:** {opp.get('platform', 'quora')}")
            lines.append(f"- **Topic:** {opp.get('topic', '?')}")
            lines.append(f"- **Score:** {opp.get('score', 0)}")
            lines.append(f"- **Signals:** {signals}")
            lines.append(f"- **Author:** {opp.get('author', 'unknown')}")
            lines.append(f"- **URL:** {opp.get('url', '')}")
            preview = opp.get("body", "")[:150]
            if preview:
                lines.append(f"- **Preview:** {preview}…")
            lines.append("")

        return "\n".join(lines)

    # ── Pipeline steps ────────────────────────────────────────────────

    def _fetch_all(
        self, keywords: List[str], limit: int
    ) -> List[Dict[str, Any]]:
        """Fetch posts for every keyword and merge results."""
        all_posts: List[Dict[str, Any]] = []
        for kw in keywords:
            try:
                posts = self._provider.fetch_posts(query=kw, limit=limit)
                all_posts.extend(posts)
                logger.info("Fetched %d posts for query '%s'", len(posts), kw)
            except Exception as exc:
                logger.error("Fetch failed for '%s': %s", kw, exc)
        return all_posts

    def _normalise(
        self, posts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Ensure every post conforms to the canonical Quora schema."""
        out: List[Dict[str, Any]] = []
        for post in posts:
            out.append({
                "id": post.get("id", ""),
                "platform": post.get("platform", "quora"),
                "title": post.get("title", ""),
                "body": post.get("body", ""),
                "url": post.get("url", ""),
                "score": int(post.get("score", 0)),
                "author": post.get("author", ""),
                "topic": post.get("topic", ""),
            })
        return out

    def _deduplicate(
        self, posts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove cross-run and in-batch duplicates by post ID."""
        seen_in_batch: set = set()
        unique: List[Dict[str, Any]] = []
        for post in posts:
            pid = post.get("id", "")
            if not pid:
                unique.append(post)
                continue
            if self._cache.has_seen(pid):
                logger.debug("Skipping already-seen post: %s", pid)
                continue
            if pid in seen_in_batch:
                continue
            seen_in_batch.add(pid)
            unique.append(post)
        return unique

    def _filter_quora(
        self, posts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Apply OpportunityFilter then enrich with Quora-specific signals.

        OpportunityFilter expects a 'subreddit' key for blacklist checks;
        we map Quora's 'topic' into that slot temporarily so the shared
        filter logic works without modification.
        """
        # Temporarily inject 'subreddit' alias so OpportunityFilter works
        bridged = [
            {**p, "subreddit": p.get("topic", "")} for p in posts
        ]

        kept_bridged = self._filter.filter_opportunities(bridged)

        # Re-attach Quora-specific signal detection (overrides Reddit signals)
        kept: List[Dict[str, Any]] = []
        for bp in kept_bridged:
            # Reconstruct original post (drop temporary subreddit key)
            original_id = bp.get("id", "")
            original = next(
                (p for p in posts if p.get("id") == original_id),
                bp,
            )
            quora_signals = _detect_quora_signals(original)
            if not quora_signals:
                # Fall back to whatever the OpportunityFilter found
                quora_signals = bp.get("opportunity_signals", [])
            kept.append({**original, "opportunity_signals": quora_signals})

        return kept

    def __repr__(self) -> str:
        return (
            f"<QuoraScannerAgent mode='{self._mode}' "
            f"cache={self._cache.size}>"
        )
