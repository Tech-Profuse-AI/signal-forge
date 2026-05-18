"""Tests for RedditPostProvider manual posting flow."""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from providers.reddit_post_provider import RedditPostProvider
from workflows.review_queue import ReviewQueue

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMP_ROOT = PROJECT_ROOT / "tests" / ".tmp_reddit_post_provider"


@contextmanager
def _workspace_tmpdir():
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = TMP_ROOT / f"run_{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_reddit_post_provider_stages_manual_reply(capsys):
    with _workspace_tmpdir() as temp_dir:
        queue_path = temp_dir / ".review_queue.json"
        pending_dir = temp_dir / "pending_posts"
        queue = ReviewQueue(queue_path=str(queue_path))
        provider = RedditPostProvider(
            review_queue=queue,
            pending_posts_dir=str(pending_dir),
        )

        result = provider.post_reply(
            "https://www.reddit.com/r/python/comments/abc123/example_post/",
            "This is the approved reply draft.",
        )

        assert result == {
            "status": "manual_required",
            "url": "https://www.reddit.com/r/python/comments/abc123/example_post",
            "draft": "This is the approved reply draft.",
        }

        logs = list(pending_dir.glob("reddit_*.json"))
        assert len(logs) == 1
        payload = json.loads(logs[0].read_text(encoding="utf-8"))
        assert payload["status"] == "manual_required"
        assert payload["review_queue_status"] == "approved_for_posting"
        assert payload["thread_url"] == result["url"]
        assert payload["draft"] == result["draft"]
        assert (
            payload["note"]
            == "Reddit auto-posting requires OAuth approval. Draft saved for manual review."
        )

        record = queue.items[0]
        assert record["review_status"] == "approved_for_posting"
        assert record["status"] == "approved_for_posting"
        assert record["review_id"] == "review-reddit-post-abc123"
        assert record["url"] == result["url"]
        assert record["url_valid"] is True
        assert record["final_draft"] == result["draft"]

        printed = capsys.readouterr().out
        assert result["url"] in printed
        assert result["draft"] in printed
        assert payload["note"] in printed
