"""
SignalForge OpportunityScannerAgent.

Orchestrates the full discovery pipeline:
  1. Scan keyword batches via RedditScanner (live or mock)
  2. Normalise results
  3. Deduplicate via CacheManager
  4. Filter via OpportunityFilter

Inspired by the TrendScannerAgent pattern in social-media-agents.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.opportunity_scanner.reddit_scanner import RedditScanner
from agents.opportunity_scanner.cache_manager import CacheManager
from agents.opportunity_scanner.filters import OpportunityFilter, FilterConfig

logger = logging.getLogger("signalforge.opportunity_scanner")


class OpportunityScannerAgent:
    """
    High-level agent that orchestrates Reddit opportunity discovery.

    Usage::

        agent = OpportunityScannerAgent()           # mock mode
        agent = OpportunityScannerAgent(             # live mode
            reddit_provider=my_reddit_provider,
        )
        opportunities = agent.scan(["social media tool", "automation"])
    """

    def __init__(
        self,
        reddit_provider: Optional[Any] = None,
        force_mock: bool = False,
        filter_config: Optional[FilterConfig] = None,
        cache_dir: Optional[str] = None,
        keywords: Optional[List[str]] = None,
    ) -> None:
        # ── Sub-components ────────────────────────────────────────────
        self.scanner = RedditScanner(
            reddit_provider=reddit_provider,
            force_mock=force_mock,
        )
        # In mock mode the post IDs are always the same fixed set from the
        # test fixture.  Persisting them to the on-disk cache causes every
        # subsequent run (UI or CLI) to see 0 opportunities because every
        # mock post is filtered out as "already seen".  Use an ephemeral
        # in-memory-only cache for mock mode so the full dataset is always
        # available; only write through to disk in live mode.
        self._mock_mode = self.scanner.mode == "mock"
        self.cache = CacheManager(cache_dir=cache_dir, ephemeral=self._mock_mode)
        self.filter = OpportunityFilter(config=filter_config)

        # Default keyword batches
        self.default_keywords = keywords or [
            "social media automation",
            "reddit engagement tool",
            "content creation workflow",
        ]
        self.stats = {"fetched": 0, "deduped": 0, "filtered": 0, "approved": 0}

        logger.info(
            "OpportunityScannerAgent ready — mode=%s, cache=%d seen",
            self.scanner.mode,
            self.cache.size,
        )

    # ── Public API ────────────────────────────────────────────────────

    def scan(
        self,
        keywords: Optional[List[str]] = None,
        limit_per_keyword: int = 25,
        subreddit: Optional[str] = None,
        time_filter: str = "week",
    ) -> List[Dict[str, Any]]:
        """
        Run the full pipeline: fetch → normalise → deduplicate → filter.

        Args:
            keywords:          Search terms (uses defaults if None).
            limit_per_keyword: Max posts per keyword (live mode only).
            subreddit:         Restrict to a specific subreddit.
            time_filter:       Time window for search.

        Returns:
            List of filtered, deduplicated opportunity dicts.
        """
        kw = keywords or self.default_keywords
        logger.info("Starting scan — keywords=%s", kw)

        # 1. Fetch
        raw_posts = self.scanner.scan_keywords(
            keywords=kw,
            limit_per_keyword=limit_per_keyword,
            subreddit=subreddit,
            time_filter=time_filter,
        )
        self.stats["fetched"] += len(raw_posts)
        logger.info("Total Reddit posts fetched: %d", len(raw_posts))

        # 2. Normalise
        normalised = self._normalise(raw_posts)

        # 3. Deduplicate
        deduped = self._deduplicate(normalised)
        self.stats["deduped"] += len(deduped)
        logger.info("After dedup: %d posts", len(deduped))

        # 4. Filter
        opportunities = self.filter.filter_opportunities(deduped)
        self.stats["filtered"] += len(opportunities)
        self.stats["approved"] += len(opportunities)
        logger.info("Final opportunities: %d", len(opportunities))

        # 5. Mark new IDs as seen
        new_ids = [p["id"] for p in opportunities if p.get("id")]
        self.cache.mark_seen_batch(new_ids)

        return opportunities

    # ── Normalisation ─────────────────────────────────────────────────

    def _normalise(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Ensure every post has all expected keys with sensible defaults."""
        normalised: List[Dict[str, Any]] = []
        for post in posts:
            normalised.append({
                "platform": post.get("platform", "reddit"),
                "id": post.get("id", ""),
                "title": post.get("title", ""),
                "body": post.get("body", ""),
                "url": post.get("url", ""),
                "score": post.get("score", 0),
                "author": post.get("author", "[unknown]"),
                "subreddit": post.get("subreddit", ""),
                "created_utc": post.get("created_utc", 0),
                "num_comments": post.get("num_comments", 0),
            })
        return normalised

    # ── Deduplication ─────────────────────────────────────────────────

    def _deduplicate(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove posts that have already been seen (via CacheManager)
        and remove in-batch duplicates by post ID.
        """
        seen_in_batch: set = set()
        unique: List[Dict[str, Any]] = []

        for post in posts:
            pid = post.get("id", "")
            if not pid:
                unique.append(post)
                continue
            if self.cache.has_seen(pid):
                logger.debug("Skipping seen post: %s", pid)
                continue
            if pid in seen_in_batch:
                continue
            seen_in_batch.add(pid)
            unique.append(post)

        return unique

    # ── Report ────────────────────────────────────────────────────────

    def generate_report(
        self, opportunities: List[Dict[str, Any]]
    ) -> str:
        """Build a readable summary of discovered opportunities."""
        if not opportunities:
            return "No opportunities found in this scan."

        lines = [
            f"# Opportunity Scan Report — {len(opportunities)} found",
            "",
        ]
        for i, opp in enumerate(opportunities, 1):
            signals = ", ".join(opp.get("opportunity_signals", []))
            lines.append(f"## {i}. {opp.get('title', 'Untitled')}")
            lines.append(f"- **Subreddit:** r/{opp.get('subreddit', '?')}")
            lines.append(f"- **Score:** {opp.get('score', 0)}")
            lines.append(f"- **Signals:** {signals}")
            lines.append(f"- **Author:** u/{opp.get('author', '?')}")
            lines.append(f"- **URL:** {opp.get('url', '')}")
            body_preview = (opp.get("body", ""))[:150]
            if body_preview:
                lines.append(f"- **Preview:** {body_preview}…")
            lines.append("")

        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"<OpportunityScannerAgent mode='{self.scanner.mode}' "
            f"cache={self.cache.size}>"
        )