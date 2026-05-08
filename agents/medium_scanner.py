"""
SignalForge Medium Scanner Agent.

Orchestrates the full Medium discovery pipeline:
  1. Fetch articles via MediumProvider (mock or live RSS)
  2. Deduplicate via CacheManager (ID-based)
  3. Filter via OpportunityFilter
  4. Extract article-optimised signals

Signal types (article-optimised keyword detection):
  - problem_intent
  - workflow_pain
  - tool_evaluation
  - competitor_mention
  - automation_need
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from agents.opportunity_scanner.cache_manager import CacheManager
from agents.opportunity_scanner.filters import OpportunityFilter, FilterConfig
from providers.medium_provider import MediumProvider

logger = logging.getLogger("signalforge.medium_scanner")


# ── Article-optimised signal keywords ────────────────────────────────

_SIGNAL_PATTERNS: Dict[str, List[str]] = {
    "problem_intent": [
        "problem", "challenge", "struggle", "difficulty", "issue",
        "obstacle", "pain", "friction", "blocker", "bottleneck",
        "why i stopped", "what's wrong with", "the problem with",
        "why most", "common mistake", "pitfall", "failure",
        "broken", "doesn't work", "failed to",
    ],
    "workflow_pain": [
        "workflow", "process", "pipeline", "manual", "repetitive",
        "time-consuming", "hours every", "days every", "tedious",
        "inefficient", "slow", "wasted time", "taking too long",
        "doing it manually", "copy paste", "copy-paste",
        "context switch", "juggling", "keeping track",
        "spreadsheet", "scattered",
    ],
    "tool_evaluation": [
        "tool", "software", "platform", "app", "solution",
        "compared", "comparison", "review", "tested", "tried",
        "pros and cons", "pros & cons", "worth it", "is it worth",
        "should you use", "best tool", "top tool", "best software",
        "which tool", "which platform", "alternative",
        "switched from", "switched to", "replaced",
    ],
    "competitor_mention": [
        "zapier", "make.com", "integromat", "n8n", "activepieces",
        "hubspot", "salesforce", "marketo", "pardot",
        "notion", "airtable", "clickup", "monday", "asana",
        "hootsuite", "buffer", "sproutsocial", "later",
        "chatgpt", "jasper", "copy.ai", "writesonic",
        "midjourney", "stable diffusion", "dalle",
        "vs ", " versus ", " compared to ",
    ],
    "automation_need": [
        "automat", "autonomous", "automatically",
        "no-code", "low-code", "workflow automation",
        "trigger", "zap", "integration", "api", "webhook",
        "schedule", "recurring", "batch", "bulk",
        "scale", "at scale", "scalable",
        "save time", "time-saving", "productivity",
        "eliminate manual", "reduce manual",
        "ai agent", "ai workflow", "ai automation",
        "llm", "gpt", "generative ai",
    ],
}


class MediumScannerAgent:
    """
    Discovers and classifies Medium articles as engagement opportunities.

    Usage::

        agent = MediumScannerAgent()                      # mock
        agent = MediumScannerAgent(mode="live")           # live RSS
        opportunities = agent.scan(["ai automation", "workflow"])
    """

    def __init__(
        self,
        mode: str = "mock",
        mock_data_path: Optional[str] = None,
        filter_config: Optional[FilterConfig] = None,
        cache_dir: Optional[str] = None,
        default_keywords: Optional[List[str]] = None,
    ) -> None:
        self._provider = MediumProvider(mode=mode, mock_data_path=mock_data_path)
        self._cache = CacheManager(
            cache_dir=cache_dir,
            cache_filename="seen_medium_posts.json",
            max_age_days=7,
        )
        self._filter = OpportunityFilter(
            config=filter_config or self._medium_filter_config()
        )
        self._default_keywords = default_keywords or [
            "ai automation",
            "workflow optimization",
            "marketing automation",
            "content generation",
            "lead generation",
        ]
        self.stats = {"fetched": 0, "deduped": 0, "filtered": 0, "approved": 0}

        logger.info(
            "MediumScannerAgent ready — mode=%s, cache=%d seen",
            self._provider.mode,
            self._cache.size,
        )

    # ── Public API ────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._provider.mode

    @property
    def cache(self) -> CacheManager:
        return self._cache

    @property
    def provider(self) -> MediumProvider:
        return self._provider

    def scan(
        self,
        keywords: Optional[List[str]] = None,
        limit_per_keyword: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Run the full pipeline: fetch → deduplicate → filter → signal extraction.

        Args:
            keywords:          Tag queries to search (uses defaults if None).
            limit_per_keyword: Max articles to fetch per keyword.

        Returns:
            List of filtered, signal-annotated article dicts.
        """
        kw = keywords or self._default_keywords
        logger.info("MediumScannerAgent.scan — keywords=%s", kw)

        # 1. Fetch
        raw_posts = self._fetch_all(kw, limit_per_keyword)
        self.stats["fetched"] += len(raw_posts)
        logger.info("Total fetched: %d articles", len(raw_posts))

        # 2. Deduplicate
        deduped = self._deduplicate(raw_posts)
        self.stats["deduped"] += len(deduped)
        logger.info("After dedup: %d articles", len(deduped))

        # 3. Filter
        filtered = self._filter.filter_opportunities(deduped)
        self.stats["filtered"] += len(filtered)
        logger.info("After filter: %d articles", len(filtered))

        # 4. Signal extraction (article-optimised)
        opportunities = []
        for article in filtered:
            signals = self._extract_signals(article)
            if signals:
                enriched = {**article, "opportunity_signals": signals}
                opportunities.append(enriched)
                logger.info(
                    "SIGNAL [%s] %s — %s",
                    article.get("id", "?"),
                    signals,
                    article.get("title", "")[:60],
                )

        # 5. Mark seen
        new_ids = [p["id"] for p in opportunities if p.get("id")]
        self._cache.mark_seen_batch(new_ids)
        self.stats["approved"] += len(opportunities)

        logger.info("Final opportunities: %d", len(opportunities))
        return opportunities

    def generate_report(self, opportunities: List[Dict[str, Any]]) -> str:
        """Build a human-readable summary of discovered Medium opportunities."""
        if not opportunities:
            return "No Medium opportunities found in this scan."

        lines = [
            f"# Medium Opportunity Scan Report — {len(opportunities)} found",
            "",
        ]
        for i, opp in enumerate(opportunities, 1):
            signals = ", ".join(opp.get("opportunity_signals", []))
            lines.append(f"## {i}. {opp.get('title', 'Untitled')}")
            lines.append(f"- **Author:** {opp.get('author', '?')}")
            lines.append(f"- **Score:** {opp.get('score', 0)}")
            lines.append(f"- **Signals:** {signals}")
            lines.append(f"- **Tags:** {', '.join(opp.get('tags', []))}")
            lines.append(f"- **Published:** {opp.get('published_at', '?')}")
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
        all_posts: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for kw in keywords:
            try:
                posts = self._provider.fetch_posts(query=kw, limit=limit)
                for p in posts:
                    pid = p.get("id", "")
                    if pid not in seen_ids:
                        seen_ids.add(pid)
                        all_posts.append(p)
                logger.info("Fetched %d articles for keyword '%s'", len(posts), kw)
            except Exception as exc:
                logger.error("Fetch failed for keyword '%s': %s", kw, exc)

        return all_posts

    def _deduplicate(
        self, posts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove posts already seen via CacheManager (ID-based dedup)."""
        unique: List[Dict[str, Any]] = []
        seen_in_batch: set = set()

        for post in posts:
            pid = post.get("id", "")
            if not pid:
                unique.append(post)
                continue
            if self._cache.has_seen(pid):
                logger.debug("Skipping already-seen article: %s", pid)
                continue
            if pid in seen_in_batch:
                continue
            seen_in_batch.add(pid)
            unique.append(post)

        return unique

    def _extract_signals(self, article: Dict[str, Any]) -> List[str]:
        """
        Article-optimised signal extraction using keyword matching.

        Medium articles tend to be longer and more structured than Reddit posts,
        so signals are detected across the full body + title + tags.
        """
        text = " ".join([
            article.get("title", ""),
            article.get("body", ""),
            " ".join(article.get("tags", [])),
        ]).lower()

        signals: List[str] = []
        for signal_name, keywords in _SIGNAL_PATTERNS.items():
            if any(kw.lower() in text for kw in keywords):
                signals.append(signal_name)

        return signals

    # ── Filter configuration ──────────────────────────────────────────

    @staticmethod
    def _medium_filter_config() -> FilterConfig:
        """
        Return a FilterConfig tuned for Medium article-style content.

        Medium articles tend to be long-form, so body-length threshold
        is higher. Score threshold is lower since clap counts aren't
        available and we derive a proxy score instead.
        """
        config = FilterConfig(
            minimum_score=1,         # proxy scores start low
            minimum_body_length=50,  # Medium RSS feeds return truncated previews, not full article bodies
        )
        # Medium articles don't have subreddits; clear Reddit-specific rules
        config.blacklisted_subreddits = []
        config.bot_author_patterns = [
            r"b[o0]t",
            r"auto[-_]?generated",
            r"^test$",
        ]
        # Override keep signals for article content
        config.help_keywords = [
            "how to", "guide", "tutorial", "step by step",
            "tips", "strategies", "best practices", "ways to",
            "how i", "how we", "lessons learned",
        ]
        config.recommendation_keywords = [
            "recommend", "tool", "platform", "software", "review",
            "comparison", "alternative", "best", "top", "worth",
        ]
        config.pain_point_keywords = [
            "problem", "challenge", "struggle", "frustrat", "fail",
            "mistake", "wrong", "broken", "inefficient", "slow",
            "wasted", "pain", "annoying", "tedious",
        ]
        config.bottleneck_keywords = [
            "automat", "workflow", "scale", "bottleneck", "process",
            "time-consuming", "manual", "inefficient", "productivity",
            "pipeline", "integration",
        ]
        return config

    def __repr__(self) -> str:
        return (
            f"<MediumScannerAgent mode='{self.mode}' "
            f"cache={self._cache.size}>"
        )
