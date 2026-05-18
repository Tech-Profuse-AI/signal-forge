"""SignalForge unified multi-platform scanner."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterator, List, Optional, Tuple

from agents.medium_scanner import MediumScannerAgent
from agents.opportunity_scanner.agent import OpportunityScannerAgent
from agents.quora_scanner import QuoraScannerAgent
from utils.dedup import dedupe_unified_exact
from utils.query_normalizer import platform_query_candidates, query_plan_summary
from utils.url_validator import normalize_url

logger = logging.getLogger("signalforge.unified_scanner")


class _NoOpDedupAgent:
    def deduplicate(self, opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return list(opportunities)


class UnifiedScannerAgent:
    """Fan out one user intent to Reddit, Quora, and Medium."""

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
        self.reddit_scanner = OpportunityScannerAgent(
            reddit_provider=reddit_provider,
            force_mock=mock_mode,
            cache_dir=cache_dir,
            cache_max_age_days=cache_max_age_days,
            ephemeral_cache=ephemeral_cache,
        )

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

        self.medium_scanner = MediumScannerAgent(
            mode="mock" if mock_mode else "live",
            cache_dir=cache_dir,
            cache_max_age_days=cache_max_age_days,
            ephemeral_cache=ephemeral_cache,
        )

        self._dedup_agent = None
        if enable_dedup:
            logger.warning(
                "Semantic dedup requested but disabled; using exact ID/URL dedup only"
            )
        self.dedup_agent = _NoOpDedupAgent()
        self._mock_mode = mock_mode

        logger.info(
            "UnifiedScannerAgent ready - mode=%s reddit=%s quora=%s medium=%s dedup=%s",
            "mock" if mock_mode else "live",
            self.reddit_scanner.scanner.mode,
            self.quora_scanner.mode,
            self.medium_scanner.mode,
            "exact-id-url",
        )

    @property
    def mode(self) -> str:
        return "mock" if self._mock_mode else "live"

    def scan(
        self,
        keywords: Optional[List[str]] = None,
        limit_per_keyword: int = 25,
        subreddit: Optional[str] = None,
        time_filter: str = "week",
        progress_callback: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Run all platform scanners concurrently and merge results."""
        unified_results: List[Dict[str, Any]] = []
        platform_counts: Dict[str, int] = {"reddit": 0, "quora": 0, "medium": 0}
        failed_platforms: List[str] = []

        for batch in self.scan_platform_batches(
            keywords=keywords,
            limit_per_keyword=limit_per_keyword,
            subreddit=subreddit,
            time_filter=time_filter,
        ):
            platform = batch["platform"]
            results = batch["results"]
            error = batch.get("error")
            if error:
                failed_platforms.append(platform)
            unified_results.extend(results)
            platform_counts[platform] = len(results)
            self._emit_partial(
                progress_callback,
                platform=platform,
                results=results,
                platform_counts=platform_counts,
                error=error,
                elapsed_ms=batch.get("elapsed_ms"),
            )

        logger.info(
            "Platform counts (pre-dedup): %s - merged=%d failed=%s",
            platform_counts,
            len(unified_results),
            failed_platforms or "none",
        )

        before_exact = len(unified_results)
        unified_results = dedupe_unified_exact(unified_results, logger=logger)
        logger.info(
            "Unified exact dedup stage: input=%d kept=%d removed=%d",
            before_exact,
            len(unified_results),
            before_exact - len(unified_results),
        )

        return unified_results

    def scan_platform_batches(
        self,
        keywords: Optional[List[str]] = None,
        limit_per_keyword: int = 25,
        subreddit: Optional[str] = None,
        time_filter: str = "week",
    ) -> Iterator[Dict[str, Any]]:
        """Yield each platform's completed scan batch as soon as it finishes."""
        raw_queries = self._raw_queries(keywords)
        original_intent = " ".join(raw_queries).strip()
        query_plan = {
            platform: platform_query_candidates(
                raw_queries,
                platform=platform,
                max_queries=4,
            )
            for platform in ("reddit", "quora", "medium")
        }
        logger.info(
            "Unified intent query plan: %s",
            {key: query_plan_summary(value) for key, value in query_plan.items()},
        )

        def scan_platform(platform: str) -> Tuple[List[Dict[str, Any]], float]:
            started = time.perf_counter()
            platform_keywords = [candidate.text for candidate in query_plan[platform]]
            results: List[Dict[str, Any]]
            try:
                if platform == "reddit":
                    results = self.reddit_scanner.scan(
                        keywords=platform_keywords,
                        limit_per_keyword=limit_per_keyword,
                        subreddit=subreddit,
                        time_filter=time_filter,
                        original_intent=original_intent,
                    )
                elif platform == "quora":
                    results = self.quora_scanner.scan(
                        keywords=platform_keywords,
                        limit_per_keyword=min(limit_per_keyword, 6),
                        original_intent=original_intent,
                    )
                else:
                    results = self.medium_scanner.scan(
                        keywords=platform_keywords,
                        limit_per_keyword=min(limit_per_keyword, 8),
                        original_intent=original_intent,
                    )
                return results, (time.perf_counter() - started) * 1000.0
            finally:
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                logger.info(
                    "TIMING stage=scanner platform=%s elapsed_ms=%.2f",
                    platform,
                    elapsed_ms,
                )

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(scan_platform, platform): platform
                for platform in ("reddit", "quora", "medium")
            }
            for future in as_completed(futures):
                platform = futures[future]
                try:
                    results, elapsed_ms = future.result()
                    results = self._valid_url_results(results, platform)
                    yield {
                        "platform": platform,
                        "results": results,
                        "elapsed_ms": elapsed_ms,
                    }
                except Exception as exc:
                    logger.exception("%s scanner failed", platform.capitalize())
                    yield {
                        "platform": platform,
                        "results": [],
                        "error": str(exc),
                        "elapsed_ms": None,
                    }

    @staticmethod
    def _raw_queries(keywords: Optional[List[str]] | str) -> List[str]:
        if not keywords:
            return ["AI workflow automation pain points"]
        if isinstance(keywords, str):
            return [keywords]
        return [str(item) for item in keywords if str(item).strip()]

    @staticmethod
    def _valid_url_results(
        results: List[Dict[str, Any]],
        platform: str,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for item in results:
            cleaned, valid = normalize_url(item.get("url", ""), item.get("platform") or platform)
            if not valid:
                logger.info(
                    "Unified URL gate dropped platform=%s id=%s url=%s",
                    platform,
                    item.get("id", ""),
                    item.get("url", ""),
                )
                continue
            out.append({**item, "url": cleaned, "url_valid": True})
        return out

    @staticmethod
    def _emit_partial(
        callback: Optional[Any],
        *,
        platform: str,
        results: List[Dict[str, Any]],
        platform_counts: Dict[str, int],
        error: Optional[str] = None,
        elapsed_ms: Optional[float] = None,
    ) -> None:
        if callback is None:
            return
        payload = {
            "platform": platform,
            "items": results[:5],
            "count": len(results),
            "platform_counts": dict(platform_counts),
        }
        if elapsed_ms is not None:
            payload["elapsed_ms"] = round(float(elapsed_ms), 2)
        if error:
            payload["error"] = error
        try:
            callback(f"{platform}_partial", sum(platform_counts.values()), payload)
        except TypeError:
            callback(f"{platform}_partial", sum(platform_counts.values()))

    def __repr__(self) -> str:
        return (
            f"<UnifiedScannerAgent mode='{self.mode}' "
            f"reddit={self.reddit_scanner!r} "
            f"quora={self.quora_scanner!r} "
            f"medium={self.medium_scanner!r}>"
        )
