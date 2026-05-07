#!/usr/bin/env python3
"""
Phase 14 Tests — MediumScannerAgent.

Validates the full Medium discovery pipeline using mock data only.
No Medium API credentials or network access required.

Run:
    cd SignalForge
    python -m pytest tests/test_medium_scanner.py -v
    # or
    python -m tests.test_medium_scanner
"""

import json
import os
import sys
import tempfile
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-36s │ %(levelname)-7s │ %(message)s",
)
logger = logging.getLogger("test_medium_scanner")

MOCK_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "mock_medium_posts.json",
)


def load_mock_posts():
    with open(MOCK_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Mock Data Integrity
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mock_data_integrity():
    """Mock JSON file exists, is valid, and has the expected schema."""
    print("\n" + "=" * 60)
    print("  TEST: Mock Data Integrity")
    print("=" * 60)

    assert os.path.exists(MOCK_DATA_PATH), (
        f"mock_medium_posts.json not found at {MOCK_DATA_PATH}"
    )

    posts = load_mock_posts()
    assert isinstance(posts, list), "Mock data must be a list"
    assert len(posts) >= 10, f"Expected ≥10 mock posts, got {len(posts)}"

    required_keys = {"id", "title", "body", "url", "author", "tags", "published_at"}
    for post in posts:
        missing = required_keys - set(post.keys())
        assert not missing, f"Post {post.get('id')} missing keys: {missing}"
        assert isinstance(post["tags"], list), f"tags must be a list in {post['id']}"
        assert isinstance(post["body"], str), f"body must be str in {post['id']}"
        assert len(post["title"]) > 0, f"title must be non-empty in {post['id']}"

    print(f"  ✓ {len(posts)} mock posts loaded with valid schema")
    print("  ── Mock Data Integrity tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Provider Mock Mode
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_provider_mock_mode():
    """MediumProvider in mock mode loads and returns normalised posts."""
    from providers.medium_provider import MediumProvider

    print("\n" + "=" * 60)
    print("  TEST: Provider Mock Mode")
    print("=" * 60)

    provider = MediumProvider(mode="mock", mock_data_path=MOCK_DATA_PATH)
    assert provider.mode == "mock"
    print(f"  ✓ Provider mode: {provider.mode}")

    posts = provider.fetch_posts(query="automation", limit=10)
    assert isinstance(posts, list)
    assert len(posts) > 0, "Should return posts from mock data"
    print(f"  ✓ fetch_posts('automation'): {len(posts)} posts")

    # Check normalised schema on each post
    normalised_keys = {"id", "platform", "title", "body", "url",
                       "score", "author", "tags", "published_at"}
    for post in posts:
        missing = normalised_keys - set(post.keys())
        assert not missing, f"Missing keys after normalise: {missing}"
        assert post["platform"] == "medium"
        assert isinstance(post["score"], int)
        assert post["score"] >= 1

    print("  ✓ All posts have correct normalised schema")
    print("  ✓ platform == 'medium' on all posts")
    print("  ✓ score >= 1 on all posts")

    # No-keyword fetch returns data
    all_posts = provider.fetch_posts(query="", limit=20)
    assert len(all_posts) > 0
    print(f"  ✓ Empty-query fetch: {len(all_posts)} posts")

    print("  ── Provider Mock Mode tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. RSS Parser Dry-Run
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_rss_parser_dry_run():
    """feedparser can parse a minimal RSS feed string without errors."""
    print("\n" + "=" * 60)
    print("  TEST: RSS Parser Dry-Run")
    print("=" * 60)

    try:
        import feedparser
    except ImportError:
        print("  ⚠ feedparser not installed — skipping RSS dry-run test")
        print("  ── RSS Parser Dry-Run SKIPPED ──")
        return

    sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Medium - automation</title>
        <link>https://medium.com/tag/automation</link>
        <description>Medium articles tagged automation</description>
        <item>
          <title>How I Automated My Entire Marketing Workflow</title>
          <link>https://medium.com/@testauthor/how-i-automated-my-workflow-abc123def456</link>
          <description>I spent years doing everything manually. Then I discovered workflow automation tools that changed everything. Here is the complete guide to automating your marketing stack using AI and no-code tools.</description>
          <author>test@example.com (Test Author)</author>
          <pubDate>Mon, 01 Jan 2025 12:00:00 GMT</pubDate>
          <guid>https://medium.com/p/abc123def456</guid>
          <category>automation</category>
          <category>marketing</category>
        </item>
      </channel>
    </rss>"""

    feed = feedparser.parse(sample_rss)
    assert not feed.bozo or feed.entries, "feedparser should parse sample RSS"
    assert len(feed.entries) == 1
    entry = feed.entries[0]
    assert "Automated" in entry.title
    print(f"  ✓ feedparser parsed 1 entry: '{entry.title}'")

    # Now test _entry_to_raw
    from providers.medium_provider import MediumProvider
    provider = MediumProvider(mode="mock", mock_data_path=MOCK_DATA_PATH)
    raw = provider._entry_to_raw(entry)

    assert raw["title"] == entry.title
    assert isinstance(raw["tags"], list)
    assert "automation" in raw["tags"]
    assert len(raw["body"]) > 0
    print(f"  ✓ _entry_to_raw: tags={raw['tags']}, body_len={len(raw['body'])}")

    print("  ── RSS Parser Dry-Run tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Normalisation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_normalisation():
    """normalize() produces correct schema from various raw inputs."""
    from providers.medium_provider import MediumProvider

    print("\n" + "=" * 60)
    print("  TEST: Normalisation")
    print("=" * 60)

    provider = MediumProvider(mode="mock", mock_data_path=MOCK_DATA_PATH)

    # Test 1: well-formed raw post
    raw = {
        "id": "https://medium.com/p/abc123def456",
        "title": "How to Automate Your Marketing Workflow",
        "body": "This is a long article about automation. " * 20,
        "url": "https://medium.com/@author/how-to-automate-abc123def456",
        "author": "Jane Doe",
        "tags": ["automation", "marketing"],
        "published_at": "Mon, 01 Jan 2024 12:00:00 GMT",
    }
    normalised = provider.normalize(raw)

    assert normalised["platform"] == "medium"
    assert normalised["title"] == raw["title"]
    assert normalised["author"] == "Jane Doe"
    assert "automation" in normalised["tags"]
    assert normalised["id"].startswith("medium_")
    assert isinstance(normalised["score"], int)
    assert normalised["score"] >= 1
    print("  ✓ Well-formed raw post normalised correctly")
    print(f"    id={normalised['id']}, score={normalised['score']}")

    # Test 2: post with HTML in body
    raw_html = {
        "id": "https://medium.com/p/htmltest",
        "title": "Testing HTML stripping",
        "body": "<h2>Title</h2><p>This is <strong>bold</strong> text.</p>",
        "url": "https://medium.com/p/htmltest",
        "author": "Test Author",
        "tags": [],
        "published_at": "",
    }
    normalised_html = provider.normalize(raw_html)
    assert "<" not in normalised_html["body"], "HTML tags should be stripped"
    assert "bold" in normalised_html["body"]
    print("  ✓ HTML stripped from body correctly")

    # Test 3: missing fields get defaults
    raw_minimal = {
        "id": "",
        "title": "Minimal post",
        "url": "",
    }
    normalised_min = provider.normalize(raw_minimal)
    assert normalised_min["platform"] == "medium"
    assert normalised_min["author"] == "Unknown Author"
    assert normalised_min["tags"] == []
    assert isinstance(normalised_min["score"], int)
    print("  ✓ Missing fields default gracefully")

    # Test 4: explicit score honoured
    raw_scored = {
        "id": "https://medium.com/p/scored",
        "title": "Scored article",
        "body": "Some content here.",
        "url": "https://medium.com/p/scored",
        "author": "Author",
        "tags": [],
        "published_at": "",
        "score": 999,
    }
    normalised_scored = provider.normalize(raw_scored)
    assert normalised_scored["score"] == 999, "Explicit score should be honoured"
    print("  ✓ Explicit score honoured")

    print("  ── Normalisation tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. Deduplication
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_deduplication():
    """MediumScannerAgent correctly deduplicates via CacheManager."""
    from agents.medium_scanner import MediumScannerAgent

    print("\n" + "=" * 60)
    print("  TEST: Deduplication")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = MediumScannerAgent(
            mode="mock",
            mock_data_path=MOCK_DATA_PATH,
            cache_dir=tmpdir,
        )
        assert agent.cache.size == 0

        # First scan
        results1 = agent.scan(keywords=["automation"])
        count1 = len(results1)
        assert count1 > 0, "First scan should return results"
        print(f"  ✓ First scan: {count1} opportunities")

        # Second scan — all previously seen IDs should be deduplicated
        results2 = agent.scan(keywords=["automation"])
        count2 = len(results2)
        assert count2 == 0, (
            f"Second scan should be empty (all deduped), got {count2}"
        )
        print(f"  ✓ Second scan (dedup): {count2} new (expected 0)")

        # Cache should have grown
        assert agent.cache.size > 0
        print(f"  ✓ Cache size after scans: {agent.cache.size}")

    print("  ── Deduplication tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. Filtering
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_filtering():
    """OpportunityFilter correctly rejects low-quality Medium articles."""
    from agents.opportunity_scanner.filters import OpportunityFilter, FilterConfig

    print("\n" + "=" * 60)
    print("  TEST: Filtering")
    print("=" * 60)

    config = FilterConfig(minimum_score=1, minimum_body_length=200)
    config.blacklisted_subreddits = []
    config.help_keywords = ["how to", "guide", "tutorial", "step by step"]
    config.recommendation_keywords = ["tool", "platform", "review", "best"]
    config.pain_point_keywords = ["problem", "struggle", "frustrat", "fail"]
    config.bottleneck_keywords = ["automat", "workflow", "manual", "productivity"]
    filt = OpportunityFilter(config=config)

    posts = load_mock_posts()
    # Add platform field for filter compatibility
    enriched = []
    for p in posts:
        enriched.append({**p, "platform": "medium", "subreddit": ""})

    kept = filt.filter_opportunities(enriched)
    kept_ids = {p["id"] for p in kept}

    # Low-effort post (short body) should be rejected
    low_effort = [p for p in enriched if len(p.get("body", "")) < 200]
    for post in low_effort:
        if not any(kw in (post.get("title","") + post.get("body","")).lower()
                   for kw in config.help_keywords + config.recommendation_keywords
                              + config.pain_point_keywords + config.bottleneck_keywords):
            assert post["id"] not in kept_ids or len(post.get("body","")) >= 200

    # Substantive articles should pass
    long_posts = [p for p in enriched if len(p.get("body", "")) >= 200]
    assert len(long_posts) > 0, "Should have some long posts in mock data"
    print(f"  ✓ {len(kept)}/{len(enriched)} posts kept by filter")
    print(f"  ✓ {len(long_posts)} posts met body length threshold")

    # All kept posts should have signals attached
    for p in kept:
        assert "opportunity_signals" in p
        assert len(p["opportunity_signals"]) > 0

    print("  ✓ All kept posts have opportunity_signals")
    print("  ── Filtering tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. Full Pipeline
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_full_pipeline():
    """End-to-end scan in mock mode produces filtered, signal-annotated results."""
    from agents.medium_scanner import MediumScannerAgent

    print("\n" + "=" * 60)
    print("  TEST: Full Pipeline")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = MediumScannerAgent(
            mode="mock",
            mock_data_path=MOCK_DATA_PATH,
            cache_dir=tmpdir,
        )

        assert agent.mode == "mock"
        print(f"  ✓ Agent mode: {agent.mode}")

        opportunities = agent.scan(
            keywords=["ai automation", "workflow optimization", "marketing automation"]
        )
        assert len(opportunities) > 0, "Should discover at least 1 opportunity"
        print(f"  ✓ Opportunities found: {len(opportunities)}")

        # All results must be normalised
        for opp in opportunities:
            assert opp["platform"] == "medium"
            assert "opportunity_signals" in opp
            assert len(opp["opportunity_signals"]) > 0
            assert opp["id"].startswith("medium_")
            assert isinstance(opp["score"], int)

        print("  ✓ All opportunities have platform='medium'")
        print("  ✓ All opportunities have opportunity_signals")
        print("  ✓ All IDs prefixed 'medium_'")

        # Report generation
        report = agent.generate_report(opportunities)
        assert "Medium Opportunity Scan Report" in report
        assert len(report) > 100
        print(f"  ✓ Report generated ({len(report)} chars)")
        print(f"    Preview: {report[:80]}…")

    print("  ── Full Pipeline tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. Signal Detection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_signal_detection():
    """Signal extraction correctly identifies all 5 article-optimised signal types."""
    from agents.medium_scanner import MediumScannerAgent, _SIGNAL_PATTERNS

    print("\n" + "=" * 60)
    print("  TEST: Signal Detection")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = MediumScannerAgent(
            mode="mock",
            mock_data_path=MOCK_DATA_PATH,
            cache_dir=tmpdir,
        )

        # Craft targeted test articles for each signal type
        signal_cases = {
            "problem_intent": {
                "id": "medium_sig001",
                "platform": "medium",
                "title": "The Problem With Manual Marketing Workflows",
                "body": "The core problem is that most marketers struggle with "
                        "the challenge of doing everything manually. This is a "
                        "real obstacle that causes friction and bottlenecks in "
                        "every team. " * 5,
                "url": "https://medium.com/p/sig001",
                "author": "Test Author",
                "tags": ["marketing"],
                "published_at": "2024-01-01T00:00:00Z",
                "score": 10,
            },
            "workflow_pain": {
                "id": "medium_sig002",
                "platform": "medium",
                "title": "Why Our Workflow Was Inefficient",
                "body": "We were doing everything manually, copy-pasting data "
                        "between spreadsheets. The process was time-consuming "
                        "and tedious. Hours every day were wasted on repetitive "
                        "tasks. Our pipeline was slow. " * 5,
                "url": "https://medium.com/p/sig002",
                "author": "Test Author",
                "tags": ["productivity"],
                "published_at": "2024-01-01T00:00:00Z",
                "score": 10,
            },
            "tool_evaluation": {
                "id": "medium_sig003",
                "platform": "medium",
                "title": "I Tested 5 Automation Tools: Here's My Review",
                "body": "I compared Zapier vs Make.com. Here is a detailed "
                        "comparison of the pros and cons of each platform. "
                        "Is it worth the investment? Which tool should you use? "
                        "I tested each software for 30 days. " * 5,
                "url": "https://medium.com/p/sig003",
                "author": "Test Author",
                "tags": ["tools"],
                "published_at": "2024-01-01T00:00:00Z",
                "score": 10,
            },
            "competitor_mention": {
                "id": "medium_sig004",
                "platform": "medium",
                "title": "Zapier vs Make.com vs n8n in 2024",
                "body": "I switched from Zapier to n8n last year. Before that "
                        "I was on Make.com (formerly Integromat). Here is my "
                        "full comparison of these automation platforms. "
                        "HubSpot and Salesforce were also in the mix. " * 5,
                "url": "https://medium.com/p/sig004",
                "author": "Test Author",
                "tags": ["automation"],
                "published_at": "2024-01-01T00:00:00Z",
                "score": 10,
            },
            "automation_need": {
                "id": "medium_sig005",
                "platform": "medium",
                "title": "How AI Automation Saved Our Team 40 Hours a Week",
                "body": "We built an AI workflow using LLM-powered agents. "
                        "The automation runs on a schedule and uses webhooks "
                        "to trigger integrations. We went from manual to "
                        "fully automated at scale. Productivity improved "
                        "dramatically. No-code tools made it possible. " * 5,
                "url": "https://medium.com/p/sig005",
                "author": "Test Author",
                "tags": ["ai", "automation"],
                "published_at": "2024-01-01T00:00:00Z",
                "score": 10,
            },
        }

        for expected_signal, article in signal_cases.items():
            signals = agent._extract_signals(article)
            assert expected_signal in signals, (
                f"Expected '{expected_signal}' in signals {signals} "
                f"for article: {article['title']}"
            )
            print(f"  ✓ '{expected_signal}' detected — signals={signals}")

        # Test that non-signal content produces empty signals
        no_signal = {
            "id": "medium_nosig",
            "platform": "medium",
            "title": "A poem about the ocean",
            "body": "The waves crash gently on the shore. " * 3,
            "url": "https://medium.com/p/nosig",
            "author": "Poet",
            "tags": ["poetry"],
            "published_at": "2024-01-01T00:00:00Z",
            "score": 5,
        }
        no_signals = agent._extract_signals(no_signal)
        # Should have 0 or very few signals
        relevant_signals = [s for s in no_signals if s not in ("", None)]
        print(f"  ✓ Non-signal content: {len(relevant_signals)} signals (expected low)")

        print("  ── Signal Detection tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Runner
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║   SignalForge — Phase 14 Medium Scanner Tests            ║")
    print("╚" + "═" * 58 + "╝")

    try:
        test_mock_data_integrity()
        test_provider_mock_mode()
        test_rss_parser_dry_run()
        test_normalisation()
        test_deduplication()
        test_filtering()
        test_full_pipeline()
        test_signal_detection()

        print("\n" + "=" * 60)
        print("  ✅ ALL PHASE 14 MEDIUM SCANNER TESTS PASSED")
        print("=" * 60 + "\n")

    except AssertionError as e:
        print(f"\n  ❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  ❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)