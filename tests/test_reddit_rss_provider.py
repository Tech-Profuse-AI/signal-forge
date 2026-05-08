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
