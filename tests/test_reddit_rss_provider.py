#!/usr/bin/env python3
"""Tests for RedditRSSProvider."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MOCK_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mock_reddit_posts.json",
)


def test_reddit_rss_provider_mock_mode_filters_and_normalizes():
    from providers.reddit_rss_provider import RedditRSSProvider

    provider = RedditRSSProvider(mode="mock", mock_data_path=MOCK_DATA_PATH)

    posts = provider.fetch_posts("workflow", limit=5)

    assert posts, "Expected workflow query to match mock posts"
    assert len(posts) <= 5
    for post in posts:
        assert post["platform"] == "reddit"
        assert post["id"]
        assert post["title"]
        assert isinstance(post["body"], str)
        assert post["url"].startswith("https://www.reddit.com/")
        assert isinstance(post["score"], int)
        assert post["author"]
        assert post["subreddit"]

    unrelated = provider.fetch_posts("TVK Vijay Stranger Things", limit=5)
    assert unrelated == []


def test_reddit_rss_provider_normalizes_rss_entry_fields():
    from providers.reddit_rss_provider import RedditRSSProvider

    provider = RedditRSSProvider(mode="mock", mock_data_path=MOCK_DATA_PATH)
    post = provider.normalize(
        {
            "id": "https://www.reddit.com/r/python/comments/abc123/example_post",
            "title": "Example post",
            "summary": "<p>This is <b>body</b> text.</p>",
            "link": "https://www.reddit.com/r/python/comments/abc123/example_post",
            "author": "u/example",
        }
    )

    assert post == {
        "id": "abc123",
        "platform": "reddit",
        "title": "Example post",
        "body": "This is body text.",
        "url": "https://www.reddit.com/r/python/comments/abc123/example_post",
        "url_valid": True,
        "score": 10,
        "author": "u/example",
        "subreddit": "python",
    }


def test_reddit_scanner_dispatches_to_rss_query_signature():
    from agents.opportunity_scanner.reddit_scanner import RedditScanner
    from providers.reddit_rss_provider import RedditRSSProvider

    provider = RedditRSSProvider(mode="mock", mock_data_path=MOCK_DATA_PATH)
    scanner = RedditScanner(reddit_provider=provider)

    posts = scanner.scan_keywords(["workflow"], limit_per_keyword=2)

    assert scanner.mode == "live"
    assert posts
    assert len(posts) <= 2
    assert all(post["platform"] == "reddit" for post in posts)


def test_t5_entry_id_with_no_link_rejected():
    """RSS entries with t5_ subreddit IDs and no link must be rejected."""
    from providers.reddit_rss_provider import RedditRSSProvider

    provider = RedditRSSProvider(mode="mock", mock_data_path=MOCK_DATA_PATH)

    # Simulate a t5_ entry (subreddit metadata) with no link
    post = provider.normalize({
        "id": "t5_gj6rto",
        "entry_id": "t5_gj6rto",
        "title": "Subreddit metadata entry",
        "body": "This is a subreddit entry, not a real post.",
        "url": "",
        "author": "",
    })

    assert post["url_valid"] is False, (
        f"t5_ entry should be rejected, got url={post['url']}"
    )


def test_t3_entry_id_with_no_link_reconstructed():
    """RSS entries with t3_ post IDs and no link should reconstruct a valid URL."""
    from providers.reddit_rss_provider import RedditRSSProvider

    provider = RedditRSSProvider(mode="mock", mock_data_path=MOCK_DATA_PATH)

    post = provider.normalize({
        "id": "t3_abc123",
        "entry_id": "t3_abc123",
        "title": "Post with t3 ID but no link",
        "body": "Some body content for the post discussion.",
        "url": "",
        "author": "testuser",
    })

    assert post["url_valid"] is True
    assert "/comments/abc123" in post["url"]


def test_valid_entry_link_preferred_over_entry_id():
    """When entry.link is present and valid, it should be used regardless of entry.id."""
    from providers.reddit_rss_provider import RedditRSSProvider

    provider = RedditRSSProvider(mode="mock", mock_data_path=MOCK_DATA_PATH)

    post = provider.normalize({
        "id": "t5_something",
        "entry_id": "t5_something",
        "title": "Post with valid link but t5 entry ID",
        "body": "Body content here.",
        "url": "https://www.reddit.com/r/test/comments/xyz789/some_post",
        "author": "user",
    })

    assert post["url_valid"] is True
    assert "/comments/xyz789" in post["url"]
    assert "t5_" not in post["url"]


def test_entry_to_raw_rejects_t5_with_no_link():
    """_entry_to_raw should return None for t5_ entries without a link."""
    from providers.reddit_rss_provider import RedditRSSProvider

    class FakeEntry:
        id = "t5_gj6rto"
        link = ""
        title = "Community metadata"
        summary = ""
        author = ""

    result = RedditRSSProvider._entry_to_raw(FakeEntry())
    assert result is None, "t5_ entries with no link should return None"


def test_entry_to_raw_accepts_t3_with_no_link():
    """_entry_to_raw should accept t3_ entries even without a link."""
    from providers.reddit_rss_provider import RedditRSSProvider

    class FakeEntry:
        id = "t3_abc123"
        link = ""
        title = "Valid post"
        summary = "Body text"
        author = "testuser"

    result = RedditRSSProvider._entry_to_raw(FakeEntry())
    assert result is not None, "t3_ entries should be accepted"
    assert result["entry_id"] == "t3_abc123"
