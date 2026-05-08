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
    ) -> List[Dict[str, Any]]:
        """
        Scan Reddit for posts matching the given keywords.

        Returns a flat, normalised list of post dicts.
        """
        if self._mode == "mock":
            return self._scan_mock(keywords)
        return self._scan_live(keywords, limit_per_keyword, subreddit, time_filter)

    # ── Live scanning ─────────────────────────────────────────────────

    def _scan_live(
        self,
        keywords: List[str],
        limit: int,
        subreddit: Optional[str],
        time_filter: str,
    ) -> List[Dict[str, Any]]:
        all_posts: List[Dict[str, Any]] = []
        for kw in keywords:
            try:
                if self._provider_accepts_keyword():
                    posts = self._provider.fetch_posts(
                        keyword=kw,
                        limit=limit,
                        subreddit=subreddit,
                        time_filter=time_filter,
                    )
                else:
                    posts = self._provider.fetch_posts(query=kw, limit=limit)
                all_posts.extend(posts)
                logger.info("Live scan: keyword='%s' → %d posts", kw, len(posts))
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

    def _scan_mock(
        self, keywords: List[str]
    ) -> List[Dict[str, Any]]:
        posts = self._load_mock_data()
        if not keywords:
            return posts

        # Filter mock posts by keyword presence in title + body
        matched: List[Dict[str, Any]] = []
        kw_lower = [k.lower() for k in keywords if k.strip()]
        if not kw_lower:
            return posts
        for post in posts:
            text = f"{post.get('title', '')} {post.get('body', '')}".lower()
            if any(kw in text for kw in kw_lower):
                matched.append(post)

        logger.info(
            "Mock scan: keywords=%s → %d/%d posts matched",
            keywords, len(matched), len(posts),
        )
        return matched

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
