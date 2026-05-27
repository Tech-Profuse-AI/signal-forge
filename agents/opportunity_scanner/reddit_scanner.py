"""
SignalForge Reddit Scanner.

Wraps the Phase 1 RedditProvider with automatic fallback to mock data
when Reddit credentials are unavailable.

Modes:
  - live  — uses RedditProvider (PRAW) for real API calls
  - mock  — loads test JSON data from disk
"""

from __future__ import annotations

import json
import logging
import inspect
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("signalforge.reddit_scanner")

_MOCK_DATA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "mock_reddit_posts.json"
)


class RedditScanner:
    """
    Fetches Reddit posts via live API or mock JSON.

    Automatically falls back to mock mode if Reddit credentials are
    missing or if ``force_mock=True``.
    """

    def __init__(
        self,
        reddit_provider: Optional[Any] = None,
        force_mock: bool = False,
        mock_data_path: Optional[str] = None,
    ) -> None:
        self._provider = reddit_provider
        self._mock_path = Path(mock_data_path) if mock_data_path else _MOCK_DATA_PATH

        if force_mock or self._provider is None:
            self._mode = "mock"
            logger.info(
                "RedditScanner in MOCK mode — data=%s",
                self._mock_path.name,
            )
        else:
            self._mode = "live"
            logger.info(
                "RedditScanner in LIVE mode - provider=%s",
                type(self._provider).__name__,
            )

    # ── Public API ────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    def scan_keywords(
        self,
        keywords: List[str],
        limit_per_keyword: int = 25,
        subreddit: Optional[str] = None,
        time_filter: str = "week",
        max_posts: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Scan Reddit for posts matching the given keywords.

        Returns a flat, normalised list of post dicts.
        """
        if self._mode == "mock":
            return self._scan_mock(keywords, max_posts=max_posts)
        return self._scan_live(
            keywords,
            limit_per_keyword,
            subreddit,
            time_filter,
            max_posts=max_posts,
        )

    # ── Live scanning ─────────────────────────────────────────────────

    def _scan_live(
        self,
        keywords: List[str],
        limit: int,
        subreddit: Optional[str],
        time_filter: str,
        *,
        max_posts: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        all_posts: List[Dict[str, Any]] = []
        for kw in keywords:
            remaining = self._remaining_capacity(max_posts, len(all_posts))
            if remaining is not None and remaining <= 0:
                logger.info(
                    "Early scan cap reached: platform=reddit cap=%d",
                    max_posts,
                )
                break
            request_limit = min(limit, remaining) if remaining is not None else limit
            try:
                posts = self._fetch_provider_posts(
                    keyword=kw,
                    limit=request_limit,
                    subreddit=subreddit,
                    time_filter=time_filter,
                )
                if remaining is not None:
                    posts = posts[:remaining]
                all_posts.extend(posts)
                logger.info("Live scan: keyword='%s' -> %d posts", kw, len(posts))
            except Exception as exc:
                logger.error("Live scan failed for '%s': %s", kw, exc)
        return all_posts

    # ── Mock scanning ─────────────────────────────────────────────────

    def _provider_accepts_keyword(self) -> bool:
        try:
            signature = inspect.signature(self._provider.fetch_posts)
        except (TypeError, ValueError):
            return True

        parameters = signature.parameters
        return (
            "keyword" in parameters
            or any(param.kind == param.VAR_KEYWORD for param in parameters.values())
        )

    def _fetch_provider_posts(
        self,
        *,
        keyword: str,
        limit: int,
        subreddit: Optional[str],
        time_filter: str,
    ) -> List[Dict[str, Any]]:
        try:
            signature = inspect.signature(self._provider.fetch_posts)
            parameters = signature.parameters
            accepts_kwargs = any(
                param.kind == param.VAR_KEYWORD for param in parameters.values()
            )
        except (TypeError, ValueError):
            parameters = {}
            accepts_kwargs = True

        kwargs: Dict[str, Any] = {"limit": limit}
        if "keyword" in parameters or accepts_kwargs:
            kwargs["keyword"] = keyword
        else:
            kwargs["query"] = keyword
        if subreddit and ("subreddit" in parameters or accepts_kwargs):
            kwargs["subreddit"] = subreddit
        if time_filter and ("time_filter" in parameters or accepts_kwargs):
            kwargs["time_filter"] = time_filter

        return self._provider.fetch_posts(**kwargs)

    def _scan_mock(
        self,
        keywords: List[str],
        *,
        max_posts: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        posts = self._load_mock_data()
        if max_posts is not None and max_posts <= 0:
            logger.info("Early scan cap reached: platform=reddit cap=%d", max_posts)
            return []
        if not keywords:
            return self._cap_posts(posts, max_posts)

        # Filter mock posts by keyword presence in title + body
        matched: List[Dict[str, Any]] = []
        kw_lower = [k.lower() for k in keywords if k.strip()]
        if not kw_lower:
            return posts
        for post in posts:
            text = f"{post.get('title', '')} {post.get('body', '')}".lower()
            if any(self._keyword_matches_text(kw, text) for kw in kw_lower):
                matched.append(post)

        logger.info(
            "Mock scan: keywords=%s -> %d/%d posts matched",
            keywords, len(matched), len(posts),
        )
        return self._cap_posts(matched, max_posts)

    @staticmethod
    def _remaining_capacity(max_posts: Optional[int], current_count: int) -> Optional[int]:
        if max_posts is None:
            return None
        return max(0, max_posts - current_count)

    @staticmethod
    def _cap_posts(
        posts: List[Dict[str, Any]],
        max_posts: Optional[int],
    ) -> List[Dict[str, Any]]:
        if max_posts is None:
            return posts
        capped = posts[:max_posts]
        if len(posts) > len(capped):
            logger.info(
                "Early scan cap reached: platform=reddit cap=%d collected=%d",
                max_posts,
                len(capped),
            )
        return capped

    @staticmethod
    def _keyword_matches_text(keyword: str, text: str) -> bool:
        if keyword in text:
            return True
        terms = [term for term in re.split(r"\s+", keyword) if len(term) > 2]
        if not terms:
            return False
        return any(term in text for term in terms)

    def _load_mock_data(self) -> List[Dict[str, Any]]:
        if not self._mock_path.exists():
            logger.warning("Mock data not found: %s", self._mock_path)
            return []
        try:
            with open(self._mock_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            logger.info("Loaded %d mock posts from %s", len(data), self._mock_path.name)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load mock data: %s", exc)
            return []

    def __repr__(self) -> str:
        return f"<RedditScanner mode='{self._mode}'>"
