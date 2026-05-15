"""
SignalForge Reddit post provider.

Reddit RSS gives us read access without credentials, but Reddit reply posting
requires an OAuth-approved app. This provider keeps the posting path honest:
approved replies are saved for manual posting instead of pretending to automate
an API call we cannot make safely.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from providers.reddit_rss_provider import RedditRSSProvider
from workflows.review_queue import ReviewQueue

logger = logging.getLogger("signalforge.reddit_post")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_QUEUE_PATH = _PROJECT_ROOT / "outputs" / ".review_queue.json"
_DEFAULT_PENDING_POSTS_DIR = _PROJECT_ROOT / "outputs" / "pending_posts"
_MANUAL_POST_NOTE = (
    "Reddit auto-posting requires OAuth approval. Draft saved for manual review."
)


class RedditPostProvider:
    """
    Read Reddit threads via RSS and stage approved replies for manual posting.

    Args:
        rss_provider: Optional reader provider. Defaults to RedditRSSProvider.
        review_queue: Optional queue instance for tests or custom storage.
        queue_path: JSON queue path used when review_queue is not supplied.
        pending_posts_dir: Directory where manual posting artifacts are written.
        reader_mode: Mode for the default RedditRSSProvider ("mock" or "live").
    """

    def __init__(
        self,
        *,
        rss_provider: Optional[RedditRSSProvider] = None,
        review_queue: Optional[ReviewQueue] = None,
        queue_path: Optional[str] = None,
        pending_posts_dir: Optional[str] = None,
        reader_mode: str = "mock",
    ) -> None:
        self._rss_provider = rss_provider or RedditRSSProvider(mode=reader_mode)
        self._review_queue = review_queue or ReviewQueue(
            queue_path=str(Path(queue_path) if queue_path else _DEFAULT_QUEUE_PATH)
        )
        self._pending_posts_dir = (
            Path(pending_posts_dir) if pending_posts_dir else _DEFAULT_PENDING_POSTS_DIR
        )
        self._pending_posts_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "RedditPostProvider initialised - pending_posts_dir=%s",
            self._pending_posts_dir,
        )

    def fetch_posts(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        """Delegate Reddit reading to the RSS provider."""
        return self._rss_provider.fetch_posts(query=query, limit=limit)

    def post_reply(self, thread_url: str, draft_text: str) -> Dict[str, str]:
        """
        Stage a Reddit reply for manual posting.

        Returns:
            {"status": "manual_required", "url": thread_url, "draft": draft_text}
        """
        clean_url = str(thread_url).strip()
        clean_draft = str(draft_text).strip()
        if not clean_url:
            raise ValueError("thread_url is required.")
        if not clean_draft:
            raise ValueError("draft_text is required.")

        timestamp = datetime.now(timezone.utc)
        queue_record = self._enqueue_for_manual_posting(clean_url, clean_draft)
        log_path = self._write_pending_post_log(
            thread_url=clean_url,
            draft_text=clean_draft,
            timestamp=timestamp,
            review_id=queue_record.get("review_id", ""),
        )

        logger.info(
            "Reddit reply staged for manual posting - review_id=%s url=%s log=%s",
            queue_record.get("review_id", ""),
            clean_url,
            log_path,
        )

        print("Reddit manual post required")
        print(f"Target URL: {clean_url}")
        print("Draft:")
        print(clean_draft)
        print(_MANUAL_POST_NOTE)

        return {
            "status": "manual_required",
            "url": clean_url,
            "draft": clean_draft,
        }

    def _enqueue_for_manual_posting(
        self,
        thread_url: str,
        draft_text: str,
    ) -> Dict[str, Any]:
        return self._review_queue.enqueue({
            "status": "approved_for_posting",
            "review_status": "approved_for_posting",
            "reviewer_action": "approved_for_posting",
            "opportunity": {
                "id": self._review_id_source(thread_url),
                "platform": "reddit",
                "url": thread_url,
                "thread_url": thread_url,
            },
            "draft": {
                "draft": draft_text,
                "thread_url": thread_url,
            },
            "compliance": {
                "approved": True,
                "safe_draft": draft_text,
            },
        })

    def _write_pending_post_log(
        self,
        *,
        thread_url: str,
        draft_text: str,
        timestamp: datetime,
        review_id: str,
    ) -> Path:
        file_timestamp = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
        log_path = self._pending_posts_dir / f"reddit_{file_timestamp}.json"
        payload = {
            "platform": "reddit",
            "status": "manual_required",
            "review_queue_status": "approved_for_posting",
            "review_id": review_id,
            "thread_url": thread_url,
            "url": thread_url,
            "draft": draft_text,
            "note": _MANUAL_POST_NOTE,
            "created_at": timestamp.replace(microsecond=0).isoformat(),
        }
        log_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return log_path

    @staticmethod
    def _review_id_source(thread_url: str) -> str:
        match = re.search(r"/comments/([A-Za-z0-9_]+)/?", thread_url)
        source = match.group(1) if match else thread_url.rstrip("/").split("/")[-1]
        source = re.sub(r"[^A-Za-z0-9_-]+", "-", source).strip("-")
        source = source or "manual-reddit-reply"
        return f"reddit-post-{source}"

    def __repr__(self) -> str:
        return "<RedditPostProvider mode='manual_required'>"
