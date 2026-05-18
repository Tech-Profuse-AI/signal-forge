"""Production URL normalization and public payload URL gates."""

from __future__ import annotations

from api.serializers import opportunity_list_response
from schemas.opportunity import serialize_opportunity
from utils.url_validator import normalize_url


def test_reddit_normalizes_rss_and_tracking_variants():
    url, valid = normalize_url(
        "http://old.reddit.com/r/python/amp/comments/abc123/example/?utm_source=rss#top",
        "reddit",
    )

    assert valid is True
    assert url == "https://www.reddit.com/r/python/comments/abc123/example"


def test_reddit_shortlink_reconstructs_to_comments_url():
    url, valid = normalize_url("https://redd.it/ABC123?utm_source=share", "reddit")

    assert valid is True
    assert url == "https://www.reddit.com/comments/abc123"


def test_reddit_rejects_entities_subreddits_and_profiles():
    invalid_urls = [
        "https://www.reddit.com/t5_gj6rto",
        "https://www.reddit.com/t3_abc123",
        "https://www.reddit.com/r/python",
        "https://www.reddit.com/user/someone",
        "https://i.redd.it/image-only.png",
    ]

    for raw in invalid_urls:
        _url, valid = normalize_url(raw, "reddit")
        assert valid is False


def test_quora_unwraps_redirect_and_strips_answer_path():
    url, valid = normalize_url(
        "https://www.google.com/url?q=https%3A%2F%2Fwww.quora.com%2FHow-do-I-build-a-workflow%2Fanswer%2FJane-Doe&utm_source=x",
        "quora",
    )

    assert valid is True
    assert url == "https://www.quora.com/How-do-I-build-a-workflow"


def test_quora_rejects_non_question_surfaces():
    invalid_urls = [
        "https://www.quora.com/profile/Jane-Doe",
        "https://www.quora.com/topic/Workflow-Automation",
        "https://startup.quora.com/Some-post",
        "https://www.quora.com/q/startupspace",
        "https://www.quora.com/deleted-question-1234",
        "https://www.google.com/url?q=https%3A%2F%2Fwww.quora.com%2Fprofile%2FJane-Doe",
    ]

    for raw in invalid_urls:
        _url, valid = normalize_url(raw, "quora")
        assert valid is False


def test_medium_strips_tracking_and_accepts_article_shapes():
    author_url, author_valid = normalize_url(
        "https://medium.com/@author/my-article-abc123?source=rss&utm_campaign=x",
        "medium",
    )
    post_url, post_valid = normalize_url("https://medium.com/p/htmltest?sk=abc", "medium")

    assert author_valid is True
    assert author_url == "https://medium.com/@author/my-article-abc123"
    assert post_valid is True
    assert post_url == "https://medium.com/p/htmltest"


def test_medium_rejects_feed_tag_and_profile_links():
    invalid_urls = [
        "https://medium.com/feed/tag/automation",
        "https://medium.com/tag/automation",
        "https://medium.com/some-publication",
        "https://medium.com/@author",
        "https://medium.com/search?q=automation",
    ]

    for raw in invalid_urls:
        _url, valid = normalize_url(raw, "medium")
        assert valid is False


def test_schema_does_not_leak_invalid_raw_url():
    out = serialize_opportunity({
        "id": "bad-reddit",
        "platform": "reddit",
        "title": "Subreddit entity",
        "url": "https://www.reddit.com/t5_gj6rto",
        "draft": "draft",
    })

    assert out["url_valid"] is False
    assert out["url"] == ""


def test_schema_accepts_legacy_thread_url_only_after_normalization():
    out = serialize_opportunity({
        "id": "thread-url-only",
        "platform": "reddit",
        "title": "Thread URL fallback",
        "thread_url": "http://old.reddit.com/r/SaaS/comments/abc123/help?utm_source=rss",
        "draft": "draft",
    })

    assert out["url_valid"] is True
    assert out["url"] == "https://www.reddit.com/r/SaaS/comments/abc123/help"


def test_public_opportunity_list_filters_invalid_urls():
    items = [
        {
            "id": "good",
            "platform": "quora",
            "title": "How do I automate workflows?",
            "url": "https://www.quora.com/How-do-I-automate-workflows",
            "draft": "draft",
        },
        {
            "id": "bad",
            "platform": "reddit",
            "title": "Profile",
            "url": "https://www.reddit.com/user/someone",
            "draft": "draft",
        },
    ]

    out = opportunity_list_response(items)

    assert [item["id"] for item in out] == ["good"]
    assert out[0]["url_valid"] is True


def test_pipeline_status_response_filters_partial_and_live_invalid_urls():
    from api.serializers import pipeline_status_response

    out = pipeline_status_response({
        "running": True,
        "partial_results": {
            "reddit": {
                "count": 2,
                "items": [
                    {
                        "id": "good",
                        "platform": "reddit",
                        "title": "Real post",
                        "url": "https://www.reddit.com/r/SaaS/comments/abc123/help",
                    },
                    {
                        "id": "bad",
                        "platform": "reddit",
                        "title": "Entity",
                        "url": "https://www.reddit.com/t5_gj6rto",
                    },
                ],
            }
        },
        "live_opportunities": [
            {
                "id": "bad-live",
                "platform": "medium",
                "title": "Medium tag",
                "url": "https://medium.com/tag/automation",
            }
        ],
    })

    assert [item["id"] for item in out["partial_results"]["reddit"]["items"]] == ["good"]
    assert out["live_opportunities"] == []


def test_api_live_opportunity_store_drops_invalid_urls():
    import api.main as api_main

    with api_main._pipeline_lock:
        api_main._pipeline_live_opportunities.clear()
        api_main._merge_live_opportunity_unlocked({
            "event": "opportunity_state",
            "id": "bad-live",
            "platform": "reddit",
            "title": "Subreddit entity",
            "url": "https://www.reddit.com/t5_gj6rto",
            "pipeline_state": "discovered",
        })

        assert api_main._pipeline_live_opportunities == {}
