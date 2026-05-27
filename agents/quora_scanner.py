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
from schemas.opportunity import serialize_opportunity
from utils.dedup import cache_keys_for_posts, dedupe_exact_posts
from utils.query_normalizer import is_generic_standalone_query, platform_queries
from utils.semantic_relevance import filter_by_semantic_relevance
from utils.url_validator import normalize_url

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
        cache_max_age_days: Optional[int] = None,
        ephemeral_cache: bool = False,
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
            max_age_days=cache_max_age_days,
            ephemeral=ephemeral_cache,
        )
        self._filter = OpportunityFilter(config=filter_config or self._quora_filter_config())

        self.default_keywords = keywords or [
            "business process automation implementation struggles",
            "workflow automation tool recommendations for SaaS",
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
        original_intent: Optional[str] = None,
        max_posts: Optional[int] = None,
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
        raw_kw = keywords or self.default_keywords
        kw = self._prepare_queries(raw_kw, original_intent=original_intent)
        if kw != raw_kw:
            logger.info("Quora intent query extraction: raw=%s semantic=%s", raw_kw, kw)
        logger.info("QuoraScannerAgent.scan() - keywords=%s", kw)
        scan_cap = self._effective_scan_cap(limit_per_keyword, max_posts)
        if scan_cap <= 0:
            logger.info("Early scan cap reached: platform=quora cap=%d", scan_cap)
            return []

        # 1. Fetch
        raw_posts = self._fetch_all(kw, scan_cap)
        self.stats["fetched"] += len(raw_posts)
        logger.info("Raw Quora posts fetched: %d", len(raw_posts))

        # 2. Normalise (provider already normalises; this ensures schema)
        normalised = self._normalise(raw_posts)
        logger.info(
            "Quora normalise stage: fetched=%d valid=%d rejected=%d",
            len(raw_posts),
            len(normalised),
            len(raw_posts) - len(normalised),
        )

        # 3. Deduplicate
        deduped = self._deduplicate(normalised)
        self.stats["deduped"] += len(deduped)
        logger.info(
            "Quora dedup stage: input=%d kept=%d removed=%d",
            len(normalised),
            len(deduped),
            len(normalised) - len(deduped),
        )

        # 4. Filter via OpportunityFilter
        #    Quora posts don't have subreddits — pass through the platform-
        #    agnostic filter then re-detect with Quora-specific signals.
        filtered = self._filter_quora(deduped)
        if isinstance(raw_kw, str):
            raw_intent_text = raw_kw
        else:
            raw_intent_text = " ".join(str(item) for item in raw_kw)
        relevance_intent = original_intent or raw_intent_text
        if relevance_intent.strip():
            before_relevance = len(filtered)
            filtered = filter_by_semantic_relevance(
                filtered,
                relevance_intent,
                threshold=0.22,
            )
            logger.info(
                "Quora semantic relevance stage: input=%d kept=%d rejected=%d",
                before_relevance,
                len(filtered),
                before_relevance - len(filtered),
            )
        self.stats["filtered"] += len(filtered)
        logger.info(
            "Quora filter stage: input=%d kept=%d rejected=%d",
            len(deduped),
            len(filtered),
            len(deduped) - len(filtered),
        )

        # 5. Mark exact IDs and URLs as seen
        new_keys = cache_keys_for_posts(filtered)
        self._cache.mark_seen_batch(new_keys)
        self.stats["approved"] += len(filtered)

        return [
            serialize_opportunity(
                opportunity,
                status="discovered",
                pipeline_state="discovered",
                can_mutate=False,
            )
            for opportunity in filtered
        ]

    def _prepare_queries(
        self,
        raw_keywords: List[str] | str,
        *,
        original_intent: Optional[str],
    ) -> List[str]:
        if isinstance(raw_keywords, str):
            raw_list = [raw_keywords]
        else:
            raw_list = [str(item) for item in raw_keywords if str(item).strip()]

        if original_intent:
            candidates = raw_list
        else:
            candidates = platform_queries(raw_list, platform="quora", max_queries=4)

        out: List[str] = []
        for query in candidates:
            clean = str(query).strip()
            if not clean or is_generic_standalone_query(clean):
                continue
            if clean not in out:
                out.append(clean)

        return out or list(self.default_keywords)

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
            remaining = limit - len(all_posts)
            if remaining <= 0:
                logger.info(
                    "Early scan cap reached: platform=quora cap=%d collected=%d",
                    limit,
                    len(all_posts),
                )
                break
            try:
                posts = self._provider.fetch_posts(query=kw, limit=remaining)
                posts = posts[:remaining]
                all_posts.extend(posts)
                logger.info("Fetched %d posts for query '%s'", len(posts), kw)
            except Exception as exc:
                logger.error("Fetch failed for '%s': %s", kw, exc)
            if len(all_posts) >= limit:
                logger.info(
                    "Early scan cap reached: platform=quora cap=%d collected=%d",
                    limit,
                    len(all_posts),
                )
                break

        return all_posts

    @staticmethod
    def _effective_scan_cap(
        limit_per_keyword: int,
        requested_max_posts: Optional[int],
    ) -> int:
        try:
            limit = int(limit_per_keyword)
        except (TypeError, ValueError):
            limit = 10
        caps = [max(0, limit)]
        if requested_max_posts is not None:
            caps.append(max(0, int(requested_max_posts)))
        try:
            from config.settings import Settings

            caps.append(max(0, int(Settings().max_quora_posts)))
        except Exception:
            caps.append(2)
        return min(caps)

    def _normalise(
        self, posts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Ensure every post conforms to the canonical Quora schema."""
        out: List[Dict[str, Any]] = []
        for post in posts:
            url, url_valid = normalize_url(post.get("url", ""), "quora")
            if not url_valid:
                logger.info(
                    "FILTER REJECT: id=%s platform=quora reason=invalid_url url=%s",
                    post.get("id", "?"),
                    post.get("url", ""),
                )
                continue
            out.append({
                "id": post.get("id", ""),
                "platform": post.get("platform", "quora"),
                "title": post.get("title", ""),
                "body": post.get("body", ""),
                "url": url,
                "url_valid": True,
                "score": int(post.get("score", 0)),
                "author": post.get("author", ""),
                "topic": post.get("topic", ""),
            })
        return out

    def _deduplicate(
        self, posts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove only exact duplicate IDs, exact duplicate URLs, and cache hits."""
        return dedupe_exact_posts(
            posts,
            cache=self._cache,
            logger=logger,
            stage="quora",
            platform="quora",
        )

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

    @staticmethod
    def _quora_filter_config() -> FilterConfig:
        """Quora search results often have score=0, so lean on signals."""
        config = FilterConfig(minimum_score=0, minimum_body_length=35)
        config.blacklisted_subreddits = []
        return config

    def __repr__(self) -> str:
        return (
            f"<QuoraScannerAgent mode='{self._mode}' "
            f"cache={self._cache.size}>"
        )
