#!/usr/bin/env python3
"""
Phase 13 Tests — QuoraScannerAgent.

Validates the Quora discovery pipeline using mock data only.
No API keys or network access required.

Test coverage:
  1. Mock data integrity (schema, required keys)
  2. QuoraProvider mock mode (load, filter, normalise)
  3. Normalisation correctness
  4. Deduplication (in-batch + cross-run)
  5. Filtering (rejection + keep signals)
  6. Full QuoraScannerAgent pipeline
  7. Signal detection (all 5 Quora signal types)

Run:
    cd SignalForge
    python -m pytest tests/test_quora_scanner.py -v
    # or
    python -m tests.test_quora_scanner
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

# ── Path setup ────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-36s │ %(levelname)-7s │ %(message)s",
)
logger = logging.getLogger("test_phase13")

# ── Mock data path ────────────────────────────────────────────────────
MOCK_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mock_quora_posts.json",
)

def load_mock_posts() -> List[Dict[str, Any]]:
    with open(MOCK_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Mock Data Integrity
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mock_data_integrity():
    """Mock JSON exists, is valid, and has the correct schema."""
    print("\n" + "=" * 62)
    print("  TEST 1: Mock Data Integrity")
    print("=" * 62)

    assert os.path.exists(MOCK_DATA_PATH), (
        f"mock_quora_posts.json not found at {MOCK_DATA_PATH}"
    )

    posts = load_mock_posts()
    assert isinstance(posts, list), "Mock data must be a list"
    assert len(posts) >= 10, f"Expected ≥10 mock posts, got {len(posts)}"

    required_keys = {"id", "platform", "title", "body", "url", "score", "author", "topic"}
    for post in posts:
        missing = required_keys - set(post.keys())
        assert not missing, f"Post {post.get('id')} missing keys: {missing}"
        assert post.get("platform") == "quora", (
            f"Post {post['id']} has wrong platform: {post.get('platform')}"
        )

    print(f"  ✓ {len(posts)} mock posts loaded")
    print("  ✓ All posts have required schema keys")
    print("  ✓ All posts have platform='quora'")
    print("  ── Mock Data tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. QuoraProvider — Mock Mode
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_quora_provider_mock_mode():
    """QuoraProvider in mock mode loads and filters data correctly."""
    from providers.quora_provider import QuoraProvider

    print("\n" + "=" * 62)
    print("  TEST 2: QuoraProvider Mock Mode")
    print("=" * 62)

    provider = QuoraProvider(mock_mode=True, mock_data_path=MOCK_DATA_PATH)
    assert repr(provider) == "<QuoraProvider mode='mock'>"
    print(f"  ✓ Provider repr: {provider!r}")

    # Broad query — should return results (fallback to all if no match)
    posts = provider.fetch_posts(query="marketing", limit=10)
    assert isinstance(posts, list), "fetch_posts must return a list"
    assert len(posts) > 0, "Should return at least one post"
    print(f"  ✓ 'marketing' query → {len(posts)} posts")

    # Specific query
    posts_crm = provider.fetch_posts(query="CRM", limit=5)
    assert len(posts_crm) <= 5, "Must respect limit"
    print(f"  ✓ 'CRM' query → {len(posts_crm)} posts (limit=5 respected)")

    # Unknown query falls back to all mock posts
    posts_xyz = provider.fetch_posts(query="xyzzy_impossible_query_12345", limit=10)
    assert len(posts_xyz) > 0, "Should fall back to all posts on no match"
    print(f"  ✓ Unknown query falls back to all posts ({len(posts_xyz)} returned)")

    print("  ── QuoraProvider mock mode PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Normalisation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_normalisation():
    """QuoraProvider.normalize() produces the correct schema."""
    from providers.quora_provider import QuoraProvider

    print("\n" + "=" * 62)
    print("  TEST 3: Normalisation")
    print("=" * 62)

    provider = QuoraProvider(mock_mode=True)

    raw = {
        "title": "  How do I automate my workflow?  ",
        "body": "I need help automating my social media replies.",
        "url": "https://www.quora.com/How-do-I-automate-my-workflow",
        "score": "42",         # string score — must be cast to int
        "author": " Jane Doe ",
        "topic": "Automation",
    }

    normalised = provider.normalize(raw)

    assert normalised["platform"] == "quora"
    assert normalised["title"] == "How do I automate my workflow?"
    assert isinstance(normalised["score"], int), "score must be int"
    assert normalised["score"] == 42
    assert normalised["author"] == "Jane Doe"
    assert normalised["topic"] == "Automation"
    assert normalised["id"].startswith("qra_"), (
        f"ID should start with 'qra_', got: {normalised['id']}"
    )

    print("  ✓ Title whitespace stripped")
    print("  ✓ Score cast to int")
    print("  ✓ Author whitespace stripped")
    print(f"  ✓ ID generated: {normalised['id']}")
    print("  ✓ Platform = 'quora'")

    # Pre-existing ID must be preserved
    raw_with_id = {**raw, "id": "qra_custom123"}
    normalised2 = provider.normalize(raw_with_id)
    assert normalised2["id"] == "qra_custom123", "Pre-existing ID must be kept"
    print("  ✓ Pre-existing ID preserved")

    print("  ── Normalisation tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Deduplication
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_deduplication():
    """QuoraScannerAgent deduplicates within-batch and across runs."""
    from agents.quora_scanner import QuoraScannerAgent

    print("\n" + "=" * 62)
    print("  TEST 4: Deduplication")
    print("=" * 62)

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = QuoraScannerAgent(
            force_mock=True,
            cache_dir=tmpdir,
            cache_filename="seen_quora_test.json",
        )
        agent._provider._mock_path = Path(MOCK_DATA_PATH)

        # First scan
        results1 = agent.scan(keywords=["automation", "workflow"], limit_per_keyword=10)
        assert len(results1) > 0, "First scan should return results"
        print(f"  ✓ First scan: {len(results1)} opportunities")

        ids_first = {r["id"] for r in results1}

        # Second scan — all IDs already seen
        results2 = agent.scan(keywords=["automation", "workflow"], limit_per_keyword=10)
        ids_second = {r["id"] for r in results2}
        overlap = ids_first & ids_second
        assert len(overlap) == 0, (
            f"Second scan returned already-seen posts: {overlap}"
        )
        print(f"  ✓ Second scan: {len(results2)} new (0 overlap — dedup works)")

        # New keyword should still find posts
        results3 = agent.scan(keywords=["pain point", "frustrat"], limit_per_keyword=10)
        print(f"  ✓ Fresh keyword scan: {len(results3)} new posts")

    print("  ── Deduplication tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. Filtering
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_filtering():
    """Low-quality posts are rejected; signal-bearing posts are kept."""
    from agents.quora_scanner import QuoraScannerAgent

    print("\n" + "=" * 62)
    print("  TEST 5: Filtering")
    print("=" * 62)

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = QuoraScannerAgent(
            force_mock=True,
            cache_dir=tmpdir,
            cache_filename="seen_quora_filter_test.json",
        )
        agent._provider._mock_path = Path(MOCK_DATA_PATH)

        results = agent.scan(keywords=["marketing", "automation"], limit_per_keyword=20)
        result_ids = {r["id"] for r in results}

        # Low-effort posts should be rejected
        assert "qra_low-effort-question" not in result_ids, (
            "Low-effort post (1-word body) should be rejected"
        )
        print("  ✓ Low-effort post rejected")

        # Deleted/empty posts should be rejected
        assert "qra_deleted-question" not in result_ids, (
            "Empty/deleted post should be rejected"
        )
        print("  ✓ Empty/deleted post rejected")

        # High-quality signal posts should be kept
        high_quality_ids = {
            "qra_automate-social-media-replies",
            "qra_pain-points-social-media-agencies",
        }
        found = high_quality_ids & result_ids
        assert len(found) > 0, (
            f"Expected at least one high-quality post; found: {found}"
        )
        print(f"  ✓ {len(found)} high-quality posts kept: {found}")

        # All kept posts have signals
        for r in results:
            assert "opportunity_signals" in r, (
                f"Post {r['id']} missing opportunity_signals"
            )
            assert len(r["opportunity_signals"]) > 0, (
                f"Post {r['id']} has empty signals"
            )
        print(f"  ✓ All {len(results)} kept posts have ≥1 signal")

    print("  ── Filtering tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. Full Pipeline
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_full_pipeline():
    """End-to-end QuoraScannerAgent pipeline in mock mode."""
    from agents.quora_scanner import QuoraScannerAgent

    print("\n" + "=" * 62)
    print("  TEST 6: Full Pipeline")
    print("=" * 62)

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = QuoraScannerAgent(
            force_mock=True,
            cache_dir=tmpdir,
            cache_filename="seen_quora_full_test.json",
        )
        agent._provider._mock_path = Path(MOCK_DATA_PATH)

        assert agent.mode == "mock"
        print(f"  ✓ Agent mode: {agent.mode}")

        results = agent.scan(
            keywords=["automation", "pain point", "recommend"],
            limit_per_keyword=15,
        )

        assert len(results) > 0, "Pipeline should return results"
        print(f"  ✓ Pipeline returned {len(results)} opportunities")

        # Verify schema of each result
        required = {"id", "platform", "title", "body", "url",
                    "score", "author", "topic", "opportunity_signals"}
        for r in results:
            missing = required - set(r.keys())
            assert not missing, f"Result {r.get('id')} missing: {missing}"
            assert r["platform"] == "quora", f"Wrong platform: {r['platform']}"

        print("  ✓ All results have correct schema")
        print("  ✓ All results have platform='quora'")

        # Report
        report = agent.generate_report(results)
        assert "Quora Opportunity Scan Report" in report
        assert len(report) > 100
        print(f"  ✓ Report generated: {len(report)} chars")

        # Platform field in report
        assert "quora" in report.lower()
        print("  ✓ Report contains platform information")

    print("  ── Full Pipeline tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. Signal Detection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_signal_detection():
    """All 5 Quora signal types are correctly detected."""
    from agents.quora_scanner import _detect_quora_signals

    print("\n" + "=" * 62)
    print("  TEST 7: Signal Detection (All 5 Types)")
    print("=" * 62)

    test_cases = [
        (
            "help_request",
            {
                "title": "How do I automate my social media replies?",
                "body": "I need help with setting up a workflow. Can someone explain?",
            },
        ),
        (
            "recommendation_request",
            {
                "title": "What tool do you recommend for content scheduling?",
                "body": "Looking for the best alternative to Hootsuite. Any suggestions?",
            },
        ),
        (
            "pain_point",
            {
                "title": "AI writing tools are frustrating and broken",
                "body": "This is becoming unsustainable. The tools don't work and it's killing my productivity.",
            },
        ),
        (
            "hiring_intent",
            {
                "title": "We are hiring a marketing automation specialist",
                "body": "We have a job opening for a contractor. Join our team if interested.",
            },
        ),
        (
            "bottleneck",
            {
                "title": "Manual engagement workflow takes too long",
                "body": "Our process is incredibly inefficient. It's a bottleneck and doesn't scale at all.",
            },
        ),
    ]

    for expected_signal, post in test_cases:
        signals = _detect_quora_signals(post)
        assert expected_signal in signals, (
            f"Expected signal '{expected_signal}' not found in {signals}\n"
            f"Post: {post}"
        )
        print(f"  ✓ '{expected_signal}' detected correctly → signals={signals}")

    # No signals for unrelated content
    empty_post = {
        "title": "The history of ancient Rome",
        "body": "Rome was founded in 753 BC according to tradition.",
    }
    no_signals = _detect_quora_signals(empty_post)
    assert "help_request" not in no_signals
    assert "hiring_intent" not in no_signals
    print(f"  ✓ Unrelated post has no spurious signals: {no_signals}")

    print("  ── Signal Detection tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. Live Parser Dry-Run (structure only, no network)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_live_parser_dry_run():
    """
    Test the HTML parsing helpers with synthetic HTML — no network needed.
    Verifies that meta-tag extraction and score parsing work correctly.
    """
    from providers.quora_provider import (
        _extract_meta,
        _extract_title_tag,
        _extract_score,
        _url_to_id,
    )

    print("\n" + "=" * 62)
    print("  TEST 8: Live Parser Dry-Run (no network)")
    print("=" * 62)

    # Synthetic Quora-like HTML
    fake_html = """
    <html>
    <head>
      <title>How do I build a workflow? - Quora</title>
      <meta property="og:title" content="How do I build a workflow?" />
      <meta property="og:description"
            content="A workflow can be built using several automation tools including Zapier and Make." />
      <meta name="author" content="John Expert" />
    </head>
    <body>
      <span>1.2K followers</span>
    </body>
    </html>
    """

    # og:title
    og_title = _extract_meta(fake_html, "og:title")
    assert og_title == "How do I build a workflow?", f"Got: {og_title}"
    print(f"  ✓ og:title extracted: '{og_title}'")

    # og:description
    og_desc = _extract_meta(fake_html, "og:description")
    assert "Zapier" in og_desc, f"Description not found: {og_desc}"
    print(f"  ✓ og:description extracted: '{og_desc[:50]}…'")

    # author
    author = _extract_meta(fake_html, "author")
    assert author == "John Expert", f"Got: {author}"
    print(f"  ✓ author extracted: '{author}'")

    # title tag fallback
    title = _extract_title_tag(fake_html)
    assert title == "How do I build a workflow?", f"Got: '{title}'"
    print(f"  ✓ <title> tag stripped of ' - Quora': '{title}'")

    # score parsing — "1.2K followers"
    score = _extract_score(fake_html)
    assert score >= 1200, f"Expected ≥1200 from '1.2K followers', got {score}"
    print(f"  ✓ Score parsed from '1.2K followers': {score}")

    # URL → ID
    uid = _url_to_id("https://www.quora.com/How-do-I-build-a-workflow")
    assert uid.startswith("qra_"), f"Got: {uid}"
    assert len(uid) > 4, f"ID too short: {uid}"
    print(f"  ✓ URL-to-ID: '{uid}'")

    print("  ── Live Parser Dry-Run PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 9. Advanced crawling upgrade (mocked)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_crawl_success_structured_extraction(monkeypatch):
    """
    Live fetch uses crawl-first extraction when available.
    No real network calls — Firecrawl scrape is mocked.
    """
    from providers.quora_provider import QuoraProvider

    provider = QuoraProvider(mock_mode=False, serp_api_key=None, request_delay=0.0)

    # Avoid search network
    monkeypatch.setattr(
        provider,
        "_search_quora_urls",
        lambda q, limit: ["https://www.quora.com/How-do-I-automate-my-social-media-replies"],
    )

    # Pretend Firecrawl is configured
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")

    # Mock Firecrawl payload
    monkeypatch.setattr(
        provider,
        "_firecrawl_scrape",
        lambda *, url, api_key, timeout=25: {
            "success": True,
            "data": {
                "metadata": {
                    "title": "How do I automate my social media replies?",
                    "author": "Jane Expert",
                },
                "markdown": (
                    "# How do I automate my social media replies?\n\n"
                    "I'm struggling with manual replies across platforms.\n\n"
                    "123 answers\n\n"
                    "Top answer: Use a triage framework and templates.\n"
                ),
            },
        },
    )

    posts = provider.fetch_posts("automation", limit=1)
    assert len(posts) == 1
    post = posts[0]
    required_keys = {"id", "platform", "title", "body", "url", "score", "author", "topic"}
    assert required_keys.issubset(set(post.keys()))
    assert post["platform"] == "quora"
    assert "automate my social media replies" in post["title"].lower()
    assert "Top answer" in post["body"]
    assert post["score"] >= 0


def test_crawl_failure_falls_back_to_html_parser(monkeypatch):
    """
    If crawling fails, provider falls back to the existing lightweight parser.
    """
    from providers.quora_provider import QuoraProvider

    provider = QuoraProvider(mock_mode=False, serp_api_key=None, request_delay=0.0)
    monkeypatch.setattr(
        provider,
        "_search_quora_urls",
        lambda q, limit: ["https://www.quora.com/How-do-I-build-a-workflow"],
    )

    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setattr(provider, "_firecrawl_scrape", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    # Force deterministic HTML parser output without network
    monkeypatch.setattr(
        provider,
        "_parse_quora_page",
        lambda url: {
            "id": "qra_fallback",
            "platform": "quora",
            "title": "Fallback title",
            "body": "Fallback body",
            "url": url,
            "score": 0,
            "author": "",
            "topic": "Automation",
        },
    )

    posts = provider.fetch_posts("workflow", limit=1)
    assert len(posts) == 1
    assert posts[0]["id"] == "qra_fallback"
    assert posts[0]["title"] == "Fallback title"


def test_crawl_disabled_without_key_uses_html_parser(monkeypatch):
    """
    Without FIRECRAWL_API_KEY, crawl is skipped and HTML parser is used.
    """
    from providers.quora_provider import QuoraProvider

    provider = QuoraProvider(mock_mode=False, serp_api_key=None, request_delay=0.0)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.setattr(provider, "_search_quora_urls", lambda q, limit: ["https://www.quora.com/How-x"])
    monkeypatch.setattr(
        provider,
        "_parse_quora_page",
        lambda url: {
            "id": "qra_html_only",
            "platform": "quora",
            "title": "HTML-only title",
            "body": "HTML-only body",
            "url": url,
            "score": 0,
            "author": "",
            "topic": "",
        },
    )
    posts = provider.fetch_posts("x", limit=1)
    assert posts[0]["id"] == "qra_html_only"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Runner
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    print("\n" + "╔" + "═" * 60 + "╗")
    print("║   SignalForge — Phase 13: Quora Integration Tests         ║")
    print("╚" + "═" * 60 + "╝")

    tests = [
        test_mock_data_integrity,
        test_quora_provider_mock_mode,
        test_normalisation,
        test_deduplication,
        test_filtering,
        test_full_pipeline,
        test_signal_detection,
        test_live_parser_dry_run,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"\n  ❌ {test_fn.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n  ❌ {test_fn.__name__} ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 62)
    if failed == 0:
        print(f"  ✅ ALL {passed} PHASE 13 TESTS PASSED")
    else:
        print(f"  ❌ {failed}/{passed + failed} TESTS FAILED")
    print("=" * 62 + "\n")

    if failed:
        sys.exit(1)