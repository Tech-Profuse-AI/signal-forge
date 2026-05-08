"""
SignalForge Reddit RSS Provider.

Uses Reddit's public RSS search feed to fetch posts without API credentials.
Normalises entries into the same canonical schema used by RedditProvider.

Modes:
  - mock: loads from tests/mock_reddit_posts.json
  - live: fetches from https://www.reddit.com/search.rss
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse

logger = logging.getLogger("signalforge.reddit_rss")

_MOCK_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "mock_reddit_posts.json"
)

_REDDIT_RSS_URL = (
    "https://www.reddit.com/search.rss?q={query}&sort=relevance&t=week&limit={limit}"
)


class RedditRSSProvider:
    """
    Fetches and normalises Reddit posts via public RSS feeds.

    Live mode:  GET https://www.reddit.com/search.rss?q={query}
    Mock mode:  load from tests/mock_reddit_posts.json
    """

    def __init__(
        self,
        mode: str = "mock",
        mock_data_path: Optional[str] = None,
    ) -> None:
        if mode not in ("mock", "live"):
            raise ValueError(f"mode must be 'mock' or 'live', got '{mode}'")

        self._mode = mode
        self._mock_path = Path(mock_data_path) if mock_data_path else _MOCK_DATA_PATH

        if mode == "live":
            try:
                import feedparser  # noqa: F401
            except ImportError as exc:
                raise ImportError(
                    "feedparser is required for RedditRSSProvider live mode. "
                    "Install it with: pip install feedparser"
                ) from exc

        logger.info("RedditRSSProvider initialised - mode=%s", mode)

    @property
    def mode(self) -> str:
        return self._mode

    def fetch_posts(
        self,
        query: str,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Fetch Reddit posts for a search query.

        Args:
            query: Search query string.
            limit: Maximum number of posts to return.

        Returns:
            A list of normalised Reddit post dicts.
        """
        if self._mode == "mock":
            return self._fetch_mock(query, limit)
        return self._fetch_live(query, limit)

    def normalize(self, post: Dict[str, Any]) -> Dict[str, Any]:
        raw_id = post.get("id") or post.get("link") or post.get("url") or ""
        url = post.get("url") or post.get("link") or ""
        body = self._extract_body(post)

        return {
            "id": self._make_id(raw_id, url),
            "platform": "reddit",
            "title": str(post.get("title", "")).strip(),
            "body": body,
            "url": url,
            "score": self._extract_score(post),
            "author": self._extract_author(post),
            "subreddit": self._extract_subreddit(post, url),
        }

    def _fetch_live(self, query: str, limit: int) -> List[Dict[str, Any]]:
        import feedparser

        feed_url = _REDDIT_RSS_URL.format(
            query=quote_plus(query),
            limit=limit,
        )
        logger.info("Fetching Reddit RSS - url=%s limit=%d", feed_url, limit)

        try:
            feed = feedparser.parse(feed_url)
        except Exception as exc:
            logger.error("feedparser failed for '%s': %s", feed_url, exc)
            return []

        if feed.bozo and not feed.entries:
            logger.warning(
                "feedparser bozo error for '%s': %s", feed_url, feed.bozo_exception
            )
            return []

        posts: List[Dict[str, Any]] = []
        for entry in feed.entries[:limit]:
            raw = self._entry_to_raw(entry)
            posts.append(self.normalize(raw))

        logger.info("Fetched %d Reddit RSS posts for query '%s'", len(posts), query)
        return posts

    def _fetch_mock(self, query: str, limit: int) -> List[Dict[str, Any]]:
        posts = self._load_mock_data()
        if not posts:
            return []

        if query:
            q = query.lower()
            posts = [post for post in posts if self._query_matches(post, q)]

        normalised = [self.normalize(post) for post in posts[:limit]]
        logger.info("Mock Reddit RSS fetch: query='%s' -> %d posts", query, len(normalised))
        return normalised

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

    @staticmethod
    def _entry_to_raw(entry: Any) -> Dict[str, Any]:
        body = getattr(entry, "summary", "") or ""
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()

        return {
            "id": getattr(entry, "id", "") or getattr(entry, "link", ""),
            "title": getattr(entry, "title", ""),
            "body": body,
            "url": getattr(entry, "link", ""),
            "author": getattr(entry, "author", "") or "",
            "score": 10,
        }

    @staticmethod
    def _make_id(raw_id: str, url: str) -> str:
        source = raw_id or url
        if not source:
            return hashlib.md5(str(id(source)).encode()).hexdigest()[:12]

        match = re.search(r"/comments/([A-Za-z0-9_]+)/", source)
        if not match and url:
            match = re.search(r"/comments/([A-Za-z0-9_]+)/", url)
        if match:
            return match.group(1)

        if source.startswith("t3_"):
            return source[3:]
        return source

    @staticmethod
    def _extract_body(post: Dict[str, Any]) -> str:
        body = post.get("body") or post.get("summary") or ""
        if isinstance(body, str):
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body).strip()
        return body or ""

    @staticmethod
    def _extract_score(post: Dict[str, Any]) -> int:
        score = post.get("score")
        try:
            return int(score)
        except (TypeError, ValueError):
            return 10

    @staticmethod
    def _extract_author(post: Dict[str, Any]) -> str:
        author = post.get("author", "")
        if isinstance(author, str) and author.strip():
            return author.strip()
        return "[unknown]"

    @staticmethod
    def _extract_subreddit(post: Dict[str, Any], url: str) -> str:
        subreddit = post.get("subreddit", "")
        if isinstance(subreddit, str) and subreddit.strip():
            return subreddit.strip()

        parts = [part for part in urlparse(url).path.split("/") if part]
        if len(parts) >= 2 and parts[0].lower() == "r":
            return parts[1]
        return ""

    @staticmethod
    def _query_matches(post: Dict[str, Any], query: str) -> bool:
        text = " ".join([
            post.get("title", ""),
            post.get("body", ""),
        ]).lower()
        return query in text

    def __repr__(self) -> str:
        return f"<RedditRSSProvider mode='{self._mode}'>"
