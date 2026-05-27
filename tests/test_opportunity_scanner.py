#!/usr/bin/env python3
"""
Phase 2 Tests — OpportunityScannerAgent.

Validates the full discovery pipeline using mock data only.
No Reddit API credentials required.

Run:
    cd SignalForge
    python -m pytest tests/test_opportunity_scanner.py -v
    # or
    python -m tests.test_opportunity_scanner
"""

import json
import os
import sys
import tempfile
import logging
from datetime import datetime, timedelta, timezone

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-32s │ %(levelname)-7s │ %(message)s",
)
logger = logging.getLogger("test_phase2")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MOCK_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mock_reddit_posts.json",
)


def load_mock_posts():
    with open(MOCK_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Mock Data Integrity
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mock_data_exists():
    """Mock JSON file exists and is valid."""
    print("\n" + "=" * 60)
    print("  TEST: Mock Data Integrity")
    print("=" * 60)

    assert os.path.exists(MOCK_DATA_PATH), "mock_reddit_posts.json not found"
    posts = load_mock_posts()
    assert isinstance(posts, list), "Mock data should be a list"
    assert len(posts) >= 10, f"Expected ≥10 mock posts, got {len(posts)}"

    # Verify schema of each post
    required_keys = {"platform", "id", "title", "body", "url", "score", "author", "subreddit"}
    for post in posts:
        missing = required_keys - set(post.keys())
        assert not missing, f"Post {post.get('id')} missing keys: {missing}"

    print(f"  ✓ {len(posts)} mock posts loaded with valid schema")
    print("  ── Mock Data tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Filters
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_filters():
    """Filters correctly reject and keep expected post types."""
    from agents.opportunity_scanner.filters import OpportunityFilter, FilterConfig

    print("\n" + "=" * 60)
    print("  TEST: Opportunity Filters")
    print("=" * 60)

    filt = OpportunityFilter(FilterConfig(minimum_score=5, minimum_body_length=50))
    posts = load_mock_posts()

    kept = filt.filter_opportunities(posts)

    # Verify specific rejections
    kept_ids = {p["id"] for p in kept}

    # mock_003 = meme (empty body, meme subreddit, "lmao" title)
    assert "mock_003" not in kept_ids, "Meme post should be rejected"

    # mock_004 = deleted
    assert "mock_004" not in kept_ids, "Deleted post should be rejected"

    # mock_006 = bot/spam (negative score, bot-like author)
    assert "mock_006" not in kept_ids, "Bot/spam post should be rejected"

    # mock_008 = low effort (body is just ".")
    assert "mock_008" not in kept_ids, "Low-effort post should be rejected"

    # mock_010 = karma farming (blacklisted subreddit)
    assert "mock_010" not in kept_ids, "Karma farming should be rejected"

    # mock_012 = low effort (body is "ok")
    assert "mock_012" not in kept_ids, "Minimal post should be rejected"

    print("  ✓ Deleted posts rejected")
    print("  ✓ Meme posts rejected")
    print("  ✓ Bot/spam posts rejected")
    print("  ✓ Low-effort posts rejected")
    print("  ✓ Blacklisted subreddit posts rejected")

    # Verify keeps — these should survive
    assert "mock_001" in kept_ids, "Help request should be kept"
    assert "mock_005" in kept_ids, "Pain point post should be kept"
    assert "mock_007" in kept_ids, "Recommendation request should be kept"
    assert "mock_011" in kept_ids, "Bottleneck post should be kept"

    print("  ✓ Help requests kept")
    print("  ✓ Pain point posts kept")
    print("  ✓ Recommendation requests kept")
    print("  ✓ Bottleneck posts kept")

    # Check signals are attached
    for p in kept:
        assert "opportunity_signals" in p, f"Post {p['id']} missing signals"
        assert len(p["opportunity_signals"]) > 0, f"Post {p['id']} has no signals"

    print(f"  ✓ {len(kept)}/{len(posts)} posts kept with signals attached")
    print("  ── Filter tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. CacheManager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cache_manager():
    """CacheManager stores, retrieves, and clears seen post IDs."""
    from agents.opportunity_scanner.cache_manager import CacheManager

    print("\n" + "=" * 60)
    print("  TEST: Cache Manager")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = CacheManager(cache_dir=tmpdir)

        # Initially empty
        assert cache.size == 0, "Cache should start empty"
        assert not cache.has_seen("test_id_1"), "Should not be seen yet"
        print("  ✓ Fresh cache is empty")

        # Mark seen
        cache.mark_seen("test_id_1")
        assert cache.has_seen("test_id_1"), "Should be seen after marking"
        assert cache.size == 1
        print("  ✓ mark_seen works")

        # Idempotent
        cache.mark_seen("test_id_1")
        assert cache.size == 1, "Duplicate mark should not increase size"
        print("  ✓ Idempotent marking")

        # Batch
        count = cache.mark_seen_batch(["test_id_2", "test_id_3", "test_id_1"])
        assert count == 2, f"Expected 2 new, got {count}"
        assert cache.size == 3
        print("  ✓ Batch marking works")

        # Persistence — reload from same dir
        cache2 = CacheManager(cache_dir=tmpdir)
        assert cache2.has_seen("test_id_1"), "Should persist across instances"
        assert cache2.size == 3
        print("  ✓ Persistence verified")

        # Clear
        cache2.clear()
        assert cache2.size == 0
        assert not cache2.has_seen("test_id_1")
        print("  ✓ Clear works")

    print("  ── Cache Manager tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. RedditScanner (mock mode)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cache_manager_expires_old_entries():
    """CacheManager drops entries older than max_age_days when loading."""
    from agents.opportunity_scanner.cache_manager import CacheManager

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "seen_posts.json")
        now = datetime.now(timezone.utc)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "fresh_post": (now - timedelta(days=2)).isoformat(),
                    "stale_post": (now - timedelta(days=8)).isoformat(),
                },
                fh,
            )

        cache = CacheManager(cache_dir=tmpdir, max_age_days=7)

        assert cache.has_seen("fresh_post"), "Fresh entry should be retained"
        assert not cache.has_seen("stale_post"), "Stale entry should expire"
        assert cache.size == 1, "Only fresh entries should remain after load"


def test_cache_manager_uses_development_minute_ttl(monkeypatch):
    """Development mode should allow seen posts back after a short TTL."""
    from agents.opportunity_scanner.cache_manager import CacheManager

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SCANNER_CACHE_MAX_AGE_MINUTES", "10")
    monkeypatch.delenv("CACHE_MAX_AGE_DAYS", raising=False)
    monkeypatch.delenv("SCANNER_CACHE_MAX_AGE_DAYS", raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "seen_posts.json")
        now = datetime.now(timezone.utc)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "fresh_post": (now - timedelta(minutes=5)).isoformat(),
                    "stale_post": (now - timedelta(minutes=11)).isoformat(),
                },
                fh,
            )

        cache = CacheManager(cache_dir=tmpdir)

        assert cache.max_age_seconds == 600
        assert cache.has_seen("fresh_post"), "Fresh development entry should remain"
        assert not cache.has_seen("stale_post"), "Old development entry should expire"
        assert cache.size == 1


def test_cache_manager_keeps_production_day_ttl(monkeypatch):
    """Production defaults should retain the existing 7-day cache behavior."""
    from agents.opportunity_scanner.cache_manager import CacheManager

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CACHE_MAX_AGE_DAYS", raising=False)
    monkeypatch.delenv("SCANNER_CACHE_MAX_AGE_DAYS", raising=False)
    monkeypatch.delenv("SCANNER_CACHE_MAX_AGE_MINUTES", raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "seen_posts.json")
        now = datetime.now(timezone.utc)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "fresh_post": (now - timedelta(days=2)).isoformat(),
                    "stale_post": (now - timedelta(days=8)).isoformat(),
                },
                fh,
            )

        cache = CacheManager(cache_dir=tmpdir)

        assert cache.max_age_seconds == 7 * 24 * 60 * 60
        assert cache.has_seen("fresh_post"), "Production entry under 7 days should remain"
        assert not cache.has_seen("stale_post"), "Production entry over 7 days should expire"
        assert cache.size == 1


def test_reddit_scanner_mock():
    """RedditScanner in mock mode loads and filters data correctly."""
    from agents.opportunity_scanner.reddit_scanner import RedditScanner

    print("\n" + "=" * 60)
    print("  TEST: Reddit Scanner (Mock Mode)")
    print("=" * 60)

    scanner = RedditScanner(reddit_provider=None, force_mock=True)
    assert scanner.mode == "mock", "Should be in mock mode"
    print(f"  ✓ Scanner mode: {scanner.mode}")

    # Scan with no keywords returns all mock data
    all_posts = scanner.scan_keywords(keywords=[])
    assert len(all_posts) >= 10, f"Expected ≥10 posts, got {len(all_posts)}"
    print(f"  ✓ No-keyword scan: {len(all_posts)} posts")

    # Scan with specific keywords
    matched = scanner.scan_keywords(keywords=["automation", "workflow"])
    assert len(matched) > 0, "Should match some posts"
    print(f"  ✓ Keyword scan: {len(matched)} posts matched")

    unrelated = scanner.scan_keywords(keywords=["TVK Vijay", "Stranger Things"])
    assert unrelated == [], "Unrelated keywords should not fall back to all mock posts"
    print("  Unrelated keyword scan returns no posts")

    # Auto-fallback when provider is None
    scanner2 = RedditScanner(reddit_provider=None)
    assert scanner2.mode == "mock", "Should auto-fallback to mock"
    print("  ✓ Auto-fallback to mock when no provider")

    print("  ── Reddit Scanner tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. Full Pipeline (OpportunityScannerAgent)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_full_pipeline():
    """End-to-end scan in mock mode produces filtered opportunities."""
    from agents.opportunity_scanner.agent import OpportunityScannerAgent

    print("\n" + "=" * 60)
    print("  TEST: Full Pipeline (OpportunityScannerAgent)")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = OpportunityScannerAgent(
            reddit_provider=None,
            force_mock=True,
            cache_dir=tmpdir,
        )

        assert agent.scanner.mode == "mock"
        print(f"  ✓ Agent mode: {agent.scanner.mode}")

        # First scan
        opportunities = agent.scan(keywords=["tool", "workflow", "automation"])
        assert len(opportunities) > 0, "Should find opportunities"
        print(f"  ✓ First scan: {len(opportunities)} opportunities")

        # Verify all have signals
        for opp in opportunities:
            assert "opportunity_signals" in opp
            assert len(opp["opportunity_signals"]) > 0

        print("  ✓ All opportunities have signals attached")

        # Verify rejected posts are excluded
        opp_ids = {o["id"] for o in opportunities}
        assert "mock_003" not in opp_ids, "Meme leaked through"
        assert "mock_004" not in opp_ids, "Deleted leaked through"
        assert "mock_006" not in opp_ids, "Bot leaked through"
        print("  ✓ Rejected posts correctly excluded")

        # Deduplication — second scan should yield nothing new
        opportunities2 = agent.scan(keywords=["tool", "workflow", "automation"])
        assert len(opportunities2) == 0, (
            f"Second scan should yield 0 (dedup), got {len(opportunities2)}"
        )
        print("  ✓ Deduplication works (second scan = 0 new)")

        # Report generation
        report = agent.generate_report(opportunities)
        assert "Opportunity Scan Report" in report
        assert len(report) > 100
        print(f"  ✓ Report generated: {len(report)} chars")
        print(f"    Preview: {report[:80]}…")

    print("  ── Full Pipeline tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. Configurable Thresholds
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_configurable_thresholds():
    """Changing thresholds affects filter results."""
    from agents.opportunity_scanner.filters import OpportunityFilter, FilterConfig

    print("\n" + "=" * 60)
    print("  TEST: Configurable Thresholds")
    print("=" * 60)

    posts = load_mock_posts()

    # Strict thresholds
    strict = OpportunityFilter(FilterConfig(minimum_score=100, minimum_body_length=200))
    strict_kept = strict.filter_opportunities(posts)

    # Lenient thresholds
    lenient = OpportunityFilter(FilterConfig(minimum_score=1, minimum_body_length=10))
    lenient_kept = lenient.filter_opportunities(posts)

    assert len(lenient_kept) >= len(strict_kept), (
        "Lenient should keep ≥ strict"
    )
    print(f"  ✓ Strict: {len(strict_kept)} kept")
    print(f"  ✓ Lenient: {len(lenient_kept)} kept")
    print("  ✓ Thresholds correctly affect filtering")

    print("  ── Threshold tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Runner
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_quora_zero_score_long_body_fallback(caplog):
    """Long-form Quora posts with score=0 should bypass the score threshold."""
    from agents.opportunity_scanner.filters import OpportunityFilter, FilterConfig

    filt = OpportunityFilter(FilterConfig(minimum_score=5, minimum_body_length=50))
    posts = [
        {
            "id": "qra_long_form_zero_score",
            "platform": "quora",
            "title": "How do I automate this workflow without a full-time team?",
            "body": "I need help automating a repetitive process. " + ("workflow pain " * 20),
            "score": 0,
            "author": "Space Author",
            "subreddit": "",
        },
        {
            "id": "qra_short_zero_score",
            "platform": "quora",
            "title": "How do I automate this workflow without a full-time team?",
            "body": "I need help automating this workflow quickly.",
            "score": 0,
            "author": "Space Author",
            "subreddit": "",
        },
    ]

    with caplog.at_level(logging.INFO, logger="signalforge.filters"):
        kept = filt.filter_opportunities(posts)

    kept_ids = {post["id"] for post in kept}
    assert "qra_long_form_zero_score" in kept_ids, "Long-form zero-score Quora post should pass"
    assert "qra_short_zero_score" not in kept_ids, "Short zero-score Quora post should still fail"
    assert any(
        "Applying Quora zero-score fallback [qra_long_form_zero_score]" in record.message
        for record in caplog.records
    ), "Expected fallback log entry for long-form zero-score Quora post"


if __name__ == "__main__":
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║   SignalForge — Phase 2 Opportunity Scanner Tests         ║")
    print("╚" + "═" * 58 + "╝")

    try:
        test_mock_data_exists()
        test_filters()
        test_cache_manager()
        test_reddit_scanner_mock()
        test_full_pipeline()
        test_configurable_thresholds()

        print("\n" + "=" * 60)
        print("  ✅ ALL PHASE 2 TESTS PASSED")
        print("=" * 60 + "\n")

    except AssertionError as e:
        print(f"\n  ❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  ❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
