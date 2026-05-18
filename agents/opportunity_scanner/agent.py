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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional

from agents.opportunity_scanner.reddit_scanner import RedditScanner
from agents.opportunity_scanner.cache_manager import CacheManager
from agents.opportunity_scanner.filters import OpportunityFilter, FilterConfig
from schemas.opportunity import serialize_opportunity
from utils.dedup import cache_keys_for_posts, dedupe_exact_posts
from utils.query_normalizer import is_generic_standalone_query, platform_queries
from utils.semantic_relevance import filter_by_semantic_relevance

logger = logging.getLogger("signalforge.opportunity_scanner")


TARGET_SUBREDDITS = [
    "SaaS",
    "Entrepreneur",
    "startups",
    "automation",
    "n8n",
    "nocode",
    "marketingautomation",
    "productivity",
    "AI_Agents",
    "sales",
]


class OpportunityScannerAgent:
    """
    High-level agent that orchestrates Reddit opportunity discovery.

    Usage::

        agent = OpportunityScannerAgent(force_mock=True)  # mock mode
        agent = OpportunityScannerAgent()                 # live RSS fallback
        agent = OpportunityScannerAgent(                  # live PRAW provider
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
        cache_max_age_days: Optional[int] = None,
        ephemeral_cache: bool = False,
    ) -> None:
        # ── Sub-components ────────────────────────────────────────────
        active_reddit_provider = self._resolve_reddit_provider(
            reddit_provider=reddit_provider,
            force_mock=force_mock,
        )
        self.scanner = RedditScanner(
            reddit_provider=active_reddit_provider,
            force_mock=force_mock,
        )
        # In mock mode the post IDs are always the same fixed set from the
        # test fixture.  Persisting them to the on-disk cache causes every
        # subsequent run (UI or CLI) to see 0 opportunities because every
        # mock post is filtered out as "already seen".  Use an ephemeral
        # in-memory-only cache for mock mode so the full dataset is always
        # available; only write through to disk in live mode.
        self._mock_mode = self.scanner.mode == "mock"
        self.cache = CacheManager(
            cache_dir=cache_dir,
            ephemeral=self._mock_mode or ephemeral_cache,
            max_age_days=cache_max_age_days,
        )
        self.filter = OpportunityFilter(config=filter_config)

        # Default keyword batches
        self.default_keywords = keywords or [
            "social media workflow automation pain points",
            "reddit engagement automation bottlenecks",
            "content operations workflow struggles",
        ]
        self.stats = {"fetched": 0, "deduped": 0, "filtered": 0, "approved": 0}

        provider_name = (
            type(active_reddit_provider).__name__
            if active_reddit_provider is not None
            else "mock"
        )
        logger.info("OpportunityScannerAgent Reddit provider active - %s", provider_name)

        logger.info(
            "OpportunityScannerAgent ready — mode=%s, cache=%d seen",
            self.scanner.mode,
            self.cache.size,
        )

    # ── Public API ────────────────────────────────────────────────────

    @staticmethod
    def _resolve_reddit_provider(
        reddit_provider: Optional[Any],
        force_mock: bool,
    ) -> Optional[Any]:
        if force_mock or reddit_provider is not None:
            return reddit_provider

        try:
            from providers.reddit_rss_provider import RedditRSSProvider

            provider = RedditRSSProvider(mode="live")
        except ImportError as exc:
            logger.warning(
                "RedditRSSProvider unavailable; falling back to mock Reddit data: %s",
                exc,
            )
            return None
        except Exception as exc:
            logger.warning(
                "RedditRSSProvider fallback failed; falling back to mock Reddit data: %s",
                exc,
            )
            return None

        logger.info(
            "RedditProvider credentials missing; using RedditRSSProvider fallback"
        )
        return provider

    def scan(
        self,
        keywords: Optional[List[str]] = None,
        limit_per_keyword: int = 25,
        subreddit: Optional[str] = None,
        time_filter: str = "week",
        original_intent: Optional[str] = None,
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
        raw_kw = keywords or self.default_keywords
        kw = self._prepare_queries(raw_kw, original_intent=original_intent)
        if kw != raw_kw:
            logger.info("Reddit intent query extraction: raw=%s semantic=%s", raw_kw, kw)
        logger.info("Starting Reddit scan - keywords=%s", kw)

        # 1. Fetch
        raw_posts = self._fetch_reddit_posts(
            kw,
            limit_per_keyword=limit_per_keyword,
            subreddit=subreddit,
            time_filter=time_filter,
        )
        self.stats["fetched"] += len(raw_posts)
        logger.info("Total Reddit posts fetched: %d", len(raw_posts))

        # 2. Normalise
        normalised = self._normalise(raw_posts)
        logger.info(
            "Reddit normalise stage: fetched=%d valid=%d rejected=%d",
            len(raw_posts),
            len(normalised),
            len(raw_posts) - len(normalised),
        )

        # 3. Deduplicate
        deduped = self._deduplicate(normalised)
        self.stats["deduped"] += len(deduped)
        logger.info(
            "Reddit dedup stage: input=%d kept=%d removed=%d",
            len(normalised),
            len(deduped),
            len(normalised) - len(deduped),
        )

        # 4. Filter
        opportunities = self.filter.filter_opportunities(deduped)
        if isinstance(raw_kw, str):
            raw_intent_text = raw_kw
        else:
            raw_intent_text = " ".join(str(item) for item in raw_kw)
        relevance_intent = original_intent or raw_intent_text
        if relevance_intent.strip():
            before_relevance = len(opportunities)
            opportunities = filter_by_semantic_relevance(
                opportunities,
                relevance_intent,
                threshold=0.23,
            )
            logger.info(
                "Reddit semantic relevance stage: input=%d kept=%d rejected=%d",
                before_relevance,
                len(opportunities),
                before_relevance - len(opportunities),
            )
        self.stats["filtered"] += len(opportunities)
        self.stats["approved"] += len(opportunities)
        logger.info(
            "Reddit filter stage: input=%d kept=%d rejected=%d",
            len(deduped),
            len(opportunities),
            len(deduped) - len(opportunities),
        )
        logger.info("Final Reddit opportunities: %d", len(opportunities))

        # 5. Mark exact IDs and URLs as seen
        new_keys = cache_keys_for_posts(opportunities)
        self.cache.mark_seen_batch(new_keys)

        return [
            serialize_opportunity(
                opportunity,
                status="discovered",
                pipeline_state="discovered",
                can_mutate=False,
            )
            for opportunity in opportunities
        ]

    def _prepare_queries(
        self,
        raw_keywords: Iterable[str] | str,
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
            candidates = platform_queries(raw_list, platform="reddit", max_queries=4)

        out: List[str] = []
        for query in candidates:
            clean = str(query).strip()
            if not clean or is_generic_standalone_query(clean):
                continue
            if clean not in out:
                out.append(clean)

        return out or list(self.default_keywords)

    def _fetch_reddit_posts(
        self,
        keywords: List[str],
        *,
        limit_per_keyword: int,
        subreddit: Optional[str],
        time_filter: str,
    ) -> List[Dict[str, Any]]:
        if self.scanner.mode != "live":
            return self.scanner.scan_keywords(
                keywords=keywords,
                limit_per_keyword=limit_per_keyword,
                subreddit=subreddit,
                time_filter=time_filter,
            )

        if subreddit:
            return self.scanner.scan_keywords(
                keywords=keywords,
                limit_per_keyword=limit_per_keyword,
                subreddit=subreddit,
                time_filter=time_filter,
            )

        targeted = self._scan_targeted_subreddits(
            keywords=keywords,
            limit_per_keyword=limit_per_keyword,
            time_filter=time_filter,
        )
        if len(targeted) >= max(4, min(limit_per_keyword, 10)):
            return targeted

        logger.info(
            "Targeted Reddit search returned %d posts; running global fallback",
            len(targeted),
        )
        global_posts = self.scanner.scan_keywords(
            keywords=keywords,
            limit_per_keyword=max(3, min(limit_per_keyword, 8)),
            subreddit=None,
            time_filter=time_filter,
        )
        return targeted + global_posts

    def _scan_targeted_subreddits(
        self,
        *,
        keywords: List[str],
        limit_per_keyword: int,
        time_filter: str,
    ) -> List[Dict[str, Any]]:
        per_subreddit_limit = max(2, min(5, limit_per_keyword))
        all_posts: List[Dict[str, Any]] = []

        def fetch_target(subreddit: str) -> List[Dict[str, Any]]:
            return self.scanner.scan_keywords(
                keywords=keywords,
                limit_per_keyword=per_subreddit_limit,
                subreddit=subreddit,
                time_filter=time_filter,
            )

        logger.info(
            "Reddit targeted subreddit search first: subreddits=%s",
            TARGET_SUBREDDITS,
        )
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(fetch_target, target): target
                for target in TARGET_SUBREDDITS
            }
            for future in as_completed(futures):
                target = futures[future]
                try:
                    posts = future.result()
                    all_posts.extend(posts)
                    logger.info(
                        "Targeted Reddit scan r/%s -> %d posts",
                        target,
                        len(posts),
                    )
                except Exception as exc:
                    logger.warning("Targeted Reddit scan failed r/%s: %s", target, exc)

        return all_posts

    # ── Normalisation ─────────────────────────────────────────────────

    def _normalise(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Ensure every post has all expected keys with sensible defaults.

        For Reddit posts, also validates the URL as a defense-in-depth
        measure.  Posts with invalid URLs are filtered out and logged.
        """
        from utils.url_validator import normalize_url

        normalised: List[Dict[str, Any]] = []
        url_rejected = 0
        for post in posts:
            platform = post.get("platform", "reddit")
            url, url_valid = normalize_url(post.get("url", ""), platform)

            # Defense-in-depth: reject posts with invalid platform URLs.
            if not url_valid:
                logger.warning(
                    "FILTER REJECT: id=%s platform=%s reason=invalid_url url=%s",
                    post.get("id", "?"), platform, post.get("url", ""),
                )
                url_rejected += 1
                continue

            normalised.append({
                "platform": platform,
                "id": post.get("id", ""),
                "title": post.get("title", ""),
                "body": post.get("body", ""),
                "url": url,
                "url_valid": True,
                "score": post.get("score", 0),
                "author": post.get("author", "[unknown]"),
                "subreddit": post.get("subreddit", ""),
                "created_utc": post.get("created_utc", 0),
                "num_comments": post.get("num_comments", 0),
            })

        if url_rejected:
            logger.info(
                "URL validation gate filtered %d posts with invalid URLs",
                url_rejected,
            )
        return normalised

    # ── Deduplication ─────────────────────────────────────────────────

    def _deduplicate(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove only exact duplicate IDs, exact duplicate URLs, and cache hits."""
        return dedupe_exact_posts(
            posts,
            cache=self.cache,
            logger=logger,
            stage="reddit",
            platform="reddit",
        )

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
