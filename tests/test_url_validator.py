#!/usr/bin/env python3
"""Comprehensive tests for the URL validator and Reddit URL normalization."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from utils.url_validator import (
    clean_url,
    is_valid_post_url,
    is_valid_reddit_entry_id,
    normalize_reddit_url,
    reconstruct_reddit_url,
    validate_and_clean,
)


# ═══════════════════════════════════════════════════════════════════
# normalize_reddit_url
# ═══════════════════════════════════════════════════════════════════


class TestNormalizeRedditUrl:
    """Tests for the centralised normalize_reddit_url function."""

    def test_valid_permalink_accepted(self):
        url = "https://www.reddit.com/r/python/comments/abc123/example_post"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True
        assert normalised == url

    def test_valid_permalink_with_trailing_slash(self):
        url = "https://www.reddit.com/r/python/comments/abc123/example_post/"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True
        assert not normalised.endswith("/")

    def test_valid_shorthand_comments_url(self):
        url = "https://www.reddit.com/comments/abc123"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True

    def test_old_reddit_normalised(self):
        url = "https://old.reddit.com/r/python/comments/abc123/example"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True
        assert "www.reddit.com" in normalised
        assert "old.reddit.com" not in normalised

    def test_np_reddit_normalised(self):
        url = "https://np.reddit.com/r/python/comments/abc123/example"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True
        assert "www.reddit.com" in normalised

    def test_bare_reddit_domain_normalised(self):
        url = "https://reddit.com/r/python/comments/abc123/example"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True
        assert "www.reddit.com" in normalised

    def test_http_forced_to_https(self):
        url = "http://www.reddit.com/r/python/comments/abc123/example"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True
        assert normalised.startswith("https://")

    def test_tracking_params_stripped(self):
        url = "https://www.reddit.com/r/python/comments/abc123/example?utm_source=share&utm_medium=web"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True
        assert "utm_source" not in normalised
        assert "utm_medium" not in normalised

    def test_share_id_param_stripped(self):
        url = "https://www.reddit.com/r/python/comments/abc123/example?share_id=xyz&ref=native"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True
        assert "share_id" not in normalised
        assert "ref=" not in normalised

    def test_amp_segment_removed(self):
        url = "https://www.reddit.com/r/python/amp/comments/abc123/example"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True
        assert "/amp/" not in normalised

    def test_t5_entity_rejected(self):
        url = "https://www.reddit.com/t5_gj6rto"
        normalised, valid = normalize_reddit_url(url)
        assert valid is False

    def test_t5_entity_rejected_with_trailing_slash(self):
        url = "https://www.reddit.com/t5_fcql3z/"
        normalised, valid = normalize_reddit_url(url)
        assert valid is False

    def test_t1_entity_rejected(self):
        url = "https://www.reddit.com/t1_abc123"
        normalised, valid = normalize_reddit_url(url)
        assert valid is False

    def test_t3_entity_rejected(self):
        """t3_ in the path is still an entity URL, not a permalink."""
        url = "https://www.reddit.com/t3_abc123"
        normalised, valid = normalize_reddit_url(url)
        assert valid is False

    def test_bare_subreddit_rejected(self):
        url = "https://www.reddit.com/r/python"
        normalised, valid = normalize_reddit_url(url)
        assert valid is False

    def test_bare_subreddit_trailing_slash_rejected(self):
        url = "https://www.reddit.com/r/python/"
        normalised, valid = normalize_reddit_url(url)
        assert valid is False

    def test_user_profile_rejected(self):
        url = "https://www.reddit.com/user/someuser"
        normalised, valid = normalize_reddit_url(url)
        assert valid is False

    def test_u_profile_rejected(self):
        url = "https://www.reddit.com/u/someuser"
        normalised, valid = normalize_reddit_url(url)
        assert valid is False

    def test_empty_url_rejected(self):
        normalised, valid = normalize_reddit_url("")
        assert valid is False
        assert normalised == ""

    def test_none_url_rejected(self):
        normalised, valid = normalize_reddit_url(None)
        assert valid is False

    def test_non_reddit_domain_rejected(self):
        url = "https://www.example.com/r/python/comments/abc123"
        normalised, valid = normalize_reddit_url(url)
        assert valid is False

    def test_fragment_stripped(self):
        url = "https://www.reddit.com/r/python/comments/abc123/example#top"
        normalised, valid = normalize_reddit_url(url)
        assert valid is True
        assert "#" not in normalised


# ═══════════════════════════════════════════════════════════════════
# reconstruct_reddit_url
# ═══════════════════════════════════════════════════════════════════


class TestReconstructRedditUrl:
    """Tests for reconstruct_reddit_url focusing on entity ID handling."""

    def test_t3_post_id_accepted(self):
        result = reconstruct_reddit_url("t3_abc123")
        assert result == "https://www.reddit.com/comments/abc123"

    def test_t5_subreddit_id_rejected(self):
        result = reconstruct_reddit_url("t5_gj6rto")
        assert result == ""

    def test_t5_uppercase_rejected(self):
        result = reconstruct_reddit_url("T5_gj6rto")
        assert result == ""

    def test_t1_comment_id_rejected(self):
        result = reconstruct_reddit_url("t1_abc123")
        assert result == ""

    def test_t2_account_id_rejected(self):
        result = reconstruct_reddit_url("t2_abc123")
        assert result == ""

    def test_t4_message_id_rejected(self):
        result = reconstruct_reddit_url("t4_abc123")
        assert result == ""

    def test_bare_id_accepted(self):
        result = reconstruct_reddit_url("abc123")
        assert result == "https://www.reddit.com/comments/abc123"

    def test_empty_string_rejected(self):
        result = reconstruct_reddit_url("")
        assert result == ""

    def test_none_rejected(self):
        result = reconstruct_reddit_url(None)
        assert result == ""

    def test_unknown_prefix_rejected(self):
        result = reconstruct_reddit_url("x7_something")
        assert result == ""

    def test_whitespace_stripped(self):
        result = reconstruct_reddit_url("  t3_abc123  ")
        assert result == "https://www.reddit.com/comments/abc123"


# ═══════════════════════════════════════════════════════════════════
# is_valid_reddit_entry_id
# ═══════════════════════════════════════════════════════════════════


class TestIsValidRedditEntryId:
    """Tests for is_valid_reddit_entry_id."""

    def test_t3_is_valid(self):
        assert is_valid_reddit_entry_id("t3_abc123") is True

    def test_t5_is_invalid(self):
        assert is_valid_reddit_entry_id("t5_gj6rto") is False

    def test_t1_is_invalid(self):
        assert is_valid_reddit_entry_id("t1_abc123") is False

    def test_t2_is_invalid(self):
        assert is_valid_reddit_entry_id("t2_abc123") is False

    def test_t4_is_invalid(self):
        assert is_valid_reddit_entry_id("t4_abc123") is False

    def test_bare_id_is_valid(self):
        assert is_valid_reddit_entry_id("abc123") is True

    def test_url_is_valid(self):
        assert is_valid_reddit_entry_id("https://www.reddit.com/r/python/comments/abc123/example") is True

    def test_empty_is_invalid(self):
        assert is_valid_reddit_entry_id("") is False

    def test_none_is_invalid(self):
        assert is_valid_reddit_entry_id(None) is False


# ═══════════════════════════════════════════════════════════════════
# is_valid_post_url — Reddit-specific
# ═══════════════════════════════════════════════════════════════════


class TestIsValidPostUrlReddit:
    """Tests for is_valid_post_url with platform='reddit'."""

    def test_valid_full_permalink(self):
        assert is_valid_post_url(
            "https://www.reddit.com/r/python/comments/abc123/example_post",
            "reddit",
        )

    def test_valid_comments_shorthand(self):
        assert is_valid_post_url(
            "https://www.reddit.com/comments/abc123",
            "reddit",
        )

    def test_t5_path_rejected(self):
        assert not is_valid_post_url(
            "https://www.reddit.com/t5_gj6rto",
            "reddit",
        )

    def test_t3_path_rejected(self):
        """t3_ in path (not as /comments/) is still an entity URL."""
        assert not is_valid_post_url(
            "https://www.reddit.com/t3_abc123",
            "reddit",
        )

    def test_t1_path_rejected(self):
        assert not is_valid_post_url(
            "https://www.reddit.com/t1_abc123",
            "reddit",
        )

    def test_bare_subreddit_rejected(self):
        assert not is_valid_post_url(
            "https://www.reddit.com/r/python",
            "reddit",
        )

    def test_user_profile_rejected(self):
        assert not is_valid_post_url(
            "https://www.reddit.com/user/someuser",
            "reddit",
        )

    def test_u_shorthand_profile_rejected(self):
        assert not is_valid_post_url(
            "https://www.reddit.com/u/someuser",
            "reddit",
        )

    def test_no_comments_rejected(self):
        assert not is_valid_post_url(
            "https://www.reddit.com/r/python/hot",
            "reddit",
        )

    def test_empty_rejected(self):
        assert not is_valid_post_url("", "reddit")

    def test_short_url_rejected(self):
        assert not is_valid_post_url("https://reddit.com", "reddit")


# ═══════════════════════════════════════════════════════════════════
# validate_and_clean — delegated for Reddit
# ═══════════════════════════════════════════════════════════════════


class TestValidateAndClean:
    """Tests for validate_and_clean dispatch."""

    def test_reddit_delegates_to_normalize_reddit_url(self):
        url = "https://old.reddit.com/r/python/comments/abc123/example?utm_source=share"
        cleaned, valid = validate_and_clean(url, "reddit")
        assert valid is True
        assert "www.reddit.com" in cleaned
        assert "utm_source" not in cleaned

    def test_reddit_t5_rejected(self):
        url = "https://www.reddit.com/t5_gj6rto"
        cleaned, valid = validate_and_clean(url, "reddit")
        assert valid is False

    def test_quora_still_works(self):
        url = "https://www.quora.com/What-is-Python?share=1"
        cleaned, valid = validate_and_clean(url, "quora")
        assert valid is True

    def test_medium_still_works(self):
        url = "https://medium.com/@user/my-article-abc123?source=rss"
        cleaned, valid = validate_and_clean(url, "medium")
        assert valid is True


# ═══════════════════════════════════════════════════════════════════
# Real-world invalid URL examples
# ═══════════════════════════════════════════════════════════════════


class TestRealWorldInvalidUrls:
    """Tests using real-world examples of invalid URLs from the bug report."""

    @pytest.mark.parametrize("url", [
        "https://www.reddit.com/t5_gj6rto",
        "https://www.reddit.com/t5_fcql3z",
        "https://reddit.com/t5_gj6rto",
        "https://www.reddit.com/t5_gj6rto/",
    ])
    def test_reported_invalid_urls_rejected(self, url):
        _, valid = normalize_reddit_url(url)
        assert valid is False, f"Expected {url} to be rejected"

    @pytest.mark.parametrize("url", [
        "https://www.reddit.com/r/QualityAssurance/comments/1tbqyt8/from_claude_code_for_automation_scripting_a_full",
        "https://www.reddit.com/r/AiAutomations/comments/1tcsuvk/looking_to_partner_with_ai_automation_builders",
        "https://www.reddit.com/r/micro_saas/comments/1t7tlnp/i_studied_47_saas_products",
        "https://www.reddit.com/comments/1td0mux",
    ])
    def test_valid_pipeline_urls_accepted(self, url):
        _, valid = normalize_reddit_url(url)
        assert valid is True, f"Expected {url} to be accepted"

    @pytest.mark.parametrize("entry_id", [
        "t5_gj6rto",
        "t5_fcql3z",
        "t1_abc123",
        "t2_xyz789",
        "t4_msg001",
    ])
    def test_non_post_entry_ids_produce_no_url(self, entry_id):
        result = reconstruct_reddit_url(entry_id)
        assert result == "", f"Expected empty URL for {entry_id}"

    def test_t3_entry_id_produces_valid_url(self):
        result = reconstruct_reddit_url("t3_1tbqyt8")
        assert result == "https://www.reddit.com/comments/1tbqyt8"
        _, valid = normalize_reddit_url(result)
        assert valid is True
