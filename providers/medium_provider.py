"""
SignalForge Medium Provider.

Uses feedparser to ingest Medium RSS feeds by tag/topic.
Normalises entries into the SignalForge canonical schema.

Modes:
  - mock: loads from data/mock_medium_posts.json
  - live: fetches from https://medium.com/feed/tag/{query}

Schema:
    {
        "id":           str,
        "platform":     "medium",
        "title":        str,
        "body":         str,
        "url":          str,
        "score":        int,
        "author":       str,
        "tags":         list[str],
        "published_at": str,
    }
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("signalforge.medium")

_MOCK_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "mock_medium_posts.json"
)

_MEDIUM_RSS_URL = "https://medium.com/feed/tag/{query}"


class MediumProvider:
    """
    Fetches and normalises Medium articles via RSS (feedparser).

    Live mode:  GET https://medium.com/feed/tag/{query}
    Mock mode:  load from data/mock_medium_posts.json

    All returned posts follow the normalised schema documented above.
    """

    def __init__(
        self,
        mode: str = "mock",
        mock_data_path: Optional[str] = None,
    ) -> None:
        """
        Initialise the Medium provider.

        Args:
            mode:           "mock" or "live".
            mock_data_path: Override path for mock JSON data.

        Raises:
            ImportError: If feedparser is not installed (live mode).
            ValueError:  If mode is not "mock" or "live".
        """
        if mode not in ("mock", "live"):
            raise ValueError(f"mode must be 'mock' or 'live', got '{mode}'")

        self._mode = mode
        self._mock_path = Path(mock_data_path) if mock_data_path else _MOCK_DATA_PATH

        if mode == "live":
            try:
                import feedparser  # noqa: F401
            except ImportError as exc:
                raise ImportError(
                    "feedparser is required for MediumProvider live mode. "
                    "Install it with: pip install feedparser"
                ) from exc

        logger.info("MediumProvider initialised — mode=%s", mode)

    # ── Public API ────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    def fetch_posts(
        self,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Fetch Medium articles for a tag/topic query.

        Args:
            query: Tag name to search (e.g. "automation", "ai-tools").
            limit: Maximum number of articles to return.

        Returns:
            A list of normalised article dicts.
        """
        if self._mode == "mock":
            return self._fetch_mock(query, limit)
        return self._fetch_live(query, limit)

    def normalize(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalise a raw feedparser entry or mock dict into the
        canonical SignalForge Medium schema.

        Args:
            post: Raw post dict from feedparser or mock JSON.

        Returns:
            Normalised post dict.
        """
        raw_id = post.get("id") or post.get("link") or post.get("url") or ""
        post_id = self._make_id(raw_id)

        title = post.get("title", "").strip()
        url = post.get("url") or post.get("link") or ""
        author = self._extract_author(post)
        body = self._extract_body(post)
        tags = self._extract_tags(post)
        published_at = self._extract_published_at(post)
        score = self._derive_score(post, body, published_at)

        return {
            "id": post_id,
            "platform": "medium",
            "title": title,
            "body": body,
            "url": url,
            "score": score,
            "author": author,
            "tags": tags,
            "published_at": published_at,
        }

    # ── Live fetching ─────────────────────────────────────────────────

    def _fetch_live(self, query: str, limit: int) -> List[Dict[str, Any]]:
        import feedparser

        tag = query.lower().replace(" ", "-")
        feed_url = _MEDIUM_RSS_URL.format(query=tag)

        logger.info("Fetching Medium RSS — url=%s limit=%d", feed_url, limit)

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

        entries = feed.entries[:limit]
        posts: List[Dict[str, Any]] = []
        for entry in entries:
            raw = self._entry_to_raw(entry)
            posts.append(self.normalize(raw))

        logger.info(
            "Fetched %d articles for tag '%s'", len(posts), query
        )
        return posts

    # ── Mock fetching ─────────────────────────────────────────────────

    def _fetch_mock(self, query: str, limit: int) -> List[Dict[str, Any]]:
        posts = self._load_mock_data()

        if not posts:
            return []

        # Filter by query presence in title, body, or tags
        if query:
            q = query.lower().replace("-", " ")
            matched = [
                p for p in posts
                if self._query_matches(p, q)
            ]
            posts = matched if matched else posts

        normalised = [self.normalize(p) for p in posts[:limit]]
        logger.info(
            "Mock fetch: query='%s' → %d posts", query, len(normalised)
        )
        return normalised

    def _load_mock_data(self) -> List[Dict[str, Any]]:
        if not self._mock_path.exists():
            logger.warning("Mock data not found: %s", self._mock_path)
            return []
        try:
            with open(self._mock_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            logger.info(
                "Loaded %d mock posts from %s", len(data), self._mock_path.name
            )
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load mock data: %s", exc)
            return []

    # ── feedparser entry → raw dict ───────────────────────────────────

    @staticmethod
    def _entry_to_raw(entry: Any) -> Dict[str, Any]:
        """Convert a feedparser entry object into a flat raw dict."""
        # Tags
        tags: List[str] = []
        for tag_obj in getattr(entry, "tags", []):
            term = getattr(tag_obj, "term", "") or ""
            if term:
                tags.append(term)

        # Content / summary
        body = ""
        if hasattr(entry, "content") and entry.content:
            body = entry.content[0].get("value", "")
        if not body:
            body = getattr(entry, "summary", "") or ""

        # Strip HTML tags from body
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()

        # Author
        author = ""
        if hasattr(entry, "author"):
            author = entry.author or ""
        if not author and hasattr(entry, "author_detail"):
            author = getattr(entry.author_detail, "name", "") or ""

        # Published
        published_at = ""
        if hasattr(entry, "published"):
            published_at = entry.published or ""

        return {
            "id": getattr(entry, "id", "") or getattr(entry, "link", ""),
            "title": getattr(entry, "title", ""),
            "url": getattr(entry, "link", ""),
            "author": author,
            "body": body,
            "tags": tags,
            "published_at": published_at,
        }

    # ── Normalisation helpers ─────────────────────────────────────────

    @staticmethod
    def _make_id(raw: str) -> str:
        """Derive a stable short ID from a URL or existing ID string."""
        if not raw:
            return hashlib.md5(str(id(raw)).encode()).hexdigest()[:12]
        # Medium post IDs are the hex suffix at the end of the URL
        match = re.search(r"-([a-f0-9]{8,12})(?:\?|$)", raw)
        if match:
            return f"medium_{match.group(1)}"
        # Fall back to short hash
        return "medium_" + hashlib.md5(raw.encode()).hexdigest()[:10]

    @staticmethod
    def _extract_author(post: Dict[str, Any]) -> str:
        author = post.get("author", "")
        if isinstance(author, str) and author.strip():
            return author.strip()
        return "Unknown Author"

    @staticmethod
    def _extract_body(post: Dict[str, Any]) -> str:
        body = post.get("body") or post.get("summary") or post.get("content", "")
        if isinstance(body, str):
            # Strip any residual HTML
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body).strip()
        return body or ""

    @staticmethod
    def _extract_tags(post: Dict[str, Any]) -> List[str]:
        tags = post.get("tags", [])
        if isinstance(tags, list):
            return [str(t).strip() for t in tags if t]
        return []

    @staticmethod
    def _extract_published_at(post: Dict[str, Any]) -> str:
        raw = post.get("published_at") or post.get("published") or ""
        if raw:
            return str(raw)
        return datetime.now(timezone.utc).isoformat()

    def _derive_score(
        self,
        post: Dict[str, Any],
        body: str,
        published_at: str,
    ) -> int:
        """
        Derive a proxy score when no clap count is available.

        Score components:
          - Body length:  longer articles → higher base quality signal
          - Recency:      articles published more recently score higher
        """
        # If a score is already supplied (e.g. in mock data), honour it
        explicit = post.get("score")
        if isinstance(explicit, int) and explicit > 0:
            return explicit

        score = 0

        # Content length component (max 50 pts)
        length = len(body)
        if length > 3000:
            score += 50
        elif length > 1500:
            score += 35
        elif length > 600:
            score += 20
        elif length > 200:
            score += 10

        # Recency component (max 50 pts)
        try:
            import email.utils
            parsed = email.utils.parsedate_to_datetime(published_at)
            now = datetime.now(timezone.utc)
            age_days = (now - parsed.astimezone(timezone.utc)).days
            if age_days <= 1:
                score += 50
            elif age_days <= 7:
                score += 40
            elif age_days <= 30:
                score += 25
            elif age_days <= 90:
                score += 10
        except Exception:
            # Try ISO format
            try:
                parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                age_days = (now - parsed.astimezone(timezone.utc)).days
                if age_days <= 1:
                    score += 50
                elif age_days <= 7:
                    score += 40
                elif age_days <= 30:
                    score += 25
                elif age_days <= 90:
                    score += 10
            except Exception:
                score += 5  # unknown age — small base

        return max(score, 1)

    @staticmethod
    def _query_matches(post: Dict[str, Any], query: str) -> bool:
        text = " ".join([
            post.get("title", ""),
            post.get("body", ""),
            " ".join(post.get("tags", [])),
        ]).lower()
        return query in text

    def __repr__(self) -> str:
        return f"<MediumProvider mode='{self._mode}'>"