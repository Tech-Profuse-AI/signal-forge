"""
SignalForge Unified Scanner Agent.

Merges results from Reddit, Quora, and Medium scanners into a single
opportunity list.  Optionally deduplicates using SemanticDedupAgent.

Supports mock and live modes.  Mode is propagated to every sub-scanner
so a single flag controls the entire discovery layer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.opportunity_scanner.agent import OpportunityScannerAgent
from agents.quora_scanner import QuoraScannerAgent
from agents.medium_scanner import MediumScannerAgent
from utils.dedup import dedupe_unified_exact
from utils.query_normalizer import normalize_queries

logger = logging.getLogger("signalforge.unified_scanner")


class _NoOpDedupAgent:
    def deduplicate(self, opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return list(opportunities)


class UnifiedScannerAgent:
    """Multi-platform scanner that fans out to Reddit, Quora, and Medium.

    Parameters
    ----------
    mock_mode:
        If ``True`` (default), every sub-scanner runs in mock/offline mode.
        If ``False``, sub-scanners use live providers.
    reddit_provider:
        An optional live ``RedditProvider`` instance.  Ignored in mock mode.
    cache_dir:
        Shared cache directory for ID-based deduplication.
    enable_dedup:
        If ``True``, run ``SemanticDedupAgent`` as a post-merge step.
        Defaults to ``False`` because the dedup agent requires a working
        embedding pipeline and is O(n²).
    """

    def __init__(
        self,
        *,
        mock_mode: bool = True,
        reddit_provider: Optional[Any] = None,
        cache_dir: Optional[str] = None,
        enable_dedup: bool = False,
        cache_max_age_days: Optional[int] = None,
        ephemeral_cache: bool = False,
    ) -> None:
        # ── Reddit ────────────────────────────────────────────────────
        self.reddit_scanner = OpportunityScannerAgent(
            reddit_provider=reddit_provider,
            force_mock=mock_mode,
            cache_dir=cache_dir,
            cache_max_age_days=cache_max_age_days,
            ephemeral_cache=ephemeral_cache,
        )

        # ── Quora ─────────────────────────────────────────────────────
        if mock_mode:
            self.quora_scanner = QuoraScannerAgent(
                force_mock=True,
                cache_dir=cache_dir,
                cache_max_age_days=cache_max_age_days,
                ephemeral_cache=ephemeral_cache,
            )
        else:
            from providers.quora_provider import QuoraProvider
            self.quora_scanner = QuoraScannerAgent(
                quora_provider=QuoraProvider(mock_mode=False),
                force_mock=False,
                cache_dir=cache_dir,
                cache_max_age_days=cache_max_age_days,
                ephemeral_cache=ephemeral_cache,
            )

        # ── Medium ────────────────────────────────────────────────────
        medium_mode = "mock" if mock_mode else "live"
        self.medium_scanner = MediumScannerAgent(
            mode=medium_mode,
            cache_dir=cache_dir,
            cache_max_age_days=cache_max_age_days,
            ephemeral_cache=ephemeral_cache,
        )

        # ── Optional semantic dedup ───────────────────────────────────
        self._dedup_agent = None
        if enable_dedup:
            logger.warning(
                "Semantic dedup requested but disabled; using exact ID/URL dedup only"
            )
        self.dedup_agent = _NoOpDedupAgent()

        self._mock_mode = mock_mode
        logger.info(
            "UnifiedScannerAgent ready — mode=%s reddit=%s quora=%s medium=%s dedup=%s",
            "mock" if mock_mode else "live",
            self.reddit_scanner.scanner.mode,
            self.quora_scanner.mode,
            self.medium_scanner.mode,
            "exact-id-url",
        )

    # ── Public API (aligned with OpportunityScannerAgent.scan) ────────

    @property
    def mode(self) -> str:
        return "mock" if self._mock_mode else "live"

    def scan(
        self,
        keywords: Optional[List[str]] = None,
        limit_per_keyword: int = 25,
        subreddit: Optional[str] = None,
        time_filter: str = "week",
    ) -> List[Dict[str, Any]]:
        """Run all platform scanners and merge results.

        The signature matches ``OpportunityScannerAgent.scan()`` so this
        agent is a drop-in replacement inside ``SignalForgeGraph``.

        Parameters
        ----------
        keywords:
            Search terms.  Each scanner uses these as search queries.
        limit_per_keyword:
            Max results per keyword per platform.
        subreddit:
            Reddit-only: restrict to a specific subreddit.
        time_filter:
            Reddit-only: time window (``week``, ``month``, etc.).
        """
        unified_results: List[Dict[str, Any]] = []
        platform_counts: Dict[str, int] = {"reddit": 0, "quora": 0, "medium": 0}
        failed_platforms: List[str] = []
        normalized_keywords = normalize_queries(keywords) if keywords else None
        if keywords and normalized_keywords != keywords:
            logger.info(
                "Unified query normalization: raw=%s normalized=%s",
                keywords,
                normalized_keywords,
            )

        # ── Reddit ────────────────────────────────────────────────────
        try:
            reddit_results = self.reddit_scanner.scan(
                keywords=normalized_keywords,
                limit_per_keyword=limit_per_keyword,
                subreddit=subreddit,
                time_filter=time_filter,
            )
            unified_results.extend(reddit_results)
            platform_counts["reddit"] = len(reddit_results)
        except Exception as exc:
            failed_platforms.append("reddit")
            logger.error("Reddit scanner failed: %s", exc)

        # ── Quora ─────────────────────────────────────────────────────
        try:
            quora_results = self.quora_scanner.scan(
                keywords=normalized_keywords,
                limit_per_keyword=limit_per_keyword,
            )
            unified_results.extend(quora_results)
            platform_counts["quora"] = len(quora_results)
        except Exception as exc:
            failed_platforms.append("quora")
            logger.error("Quora scanner failed: %s", exc)

        # ── Medium ────────────────────────────────────────────────────
        try:
            medium_results = self.medium_scanner.scan(
                keywords=normalized_keywords,
                limit_per_keyword=limit_per_keyword,
            )
            unified_results.extend(medium_results)
            platform_counts["medium"] = len(medium_results)
        except Exception as exc:
            failed_platforms.append("medium")
            logger.error("Medium scanner failed: %s", exc)

        logger.info(
            "Platform counts (pre-dedup): %s — merged=%d failed=%s",
            platform_counts,
            len(unified_results),
            failed_platforms or "none",
        )

        # ── Optional semantic dedup ───────────────────────────────────
        before_exact = len(unified_results)
        unified_results = dedupe_unified_exact(unified_results, logger=logger)
        logger.info(
            "Unified exact dedup stage: input=%d kept=%d removed=%d",
            before_exact,
            len(unified_results),
            before_exact - len(unified_results),
        )

        return unified_results

    def __repr__(self) -> str:
        return (
            f"<UnifiedScannerAgent mode='{self.mode}' "
            f"reddit={self.reddit_scanner!r} "
            f"quora={self.quora_scanner!r} "
            f"medium={self.medium_scanner!r}>"
        )
