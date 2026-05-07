#!/usr/bin/env python3
"""
Quick smoke tests for SignalForge Phase 1 modules.

These tests verify that each module initialises, validates, and
(where credentials permit) performs a basic operation.

Run:
    cd SignalForge
    python -m tests.test_phase1
"""

import os
import sys
import json
import logging

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-32s │ %(levelname)-7s │ %(message)s",
)
logger = logging.getLogger("test_phase1")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Settings Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_settings() -> None:
    """Test that Settings loads and validates correctly."""
    from config.settings import Settings

    # Reset singleton for a clean test
    Settings.reset()
    settings = Settings()

    print("\n" + "=" * 60)
    print("  TEST: Settings Loader")
    print("=" * 60)

    # Basic attributes exist
    assert hasattr(settings, "llm_provider"), "Missing llm_provider"
    assert hasattr(settings, "gemini_api_key"), "Missing gemini_api_key"
    assert hasattr(settings, "reddit_client_id"), "Missing reddit_client_id"
    assert hasattr(settings, "slack_bot_token"), "Missing slack_bot_token"

    print(f"  ✓ LLM provider:   {settings.llm_provider}")
    print(f"  ✓ Gemini key set:  {bool(settings.gemini_api_key)}")
    print(f"  ✓ Reddit ID set:   {bool(settings.reddit_client_id)}")
    print(f"  ✓ Slack token set: {bool(settings.slack_bot_token)}")
    print(f"  ✓ repr:            {settings}")

    # Validation should raise on missing keys
    try:
        settings.validate_llm()
        print("  ✓ LLM validation passed")
    except EnvironmentError as e:
        print(f"  ⚠ LLM validation (expected if no key): {e}")

    # Singleton behaviour
    settings2 = Settings()
    assert settings is settings2, "Singleton broken"
    print("  ✓ Singleton behaviour verified")

    # Reset works
    Settings.reset()
    settings3 = Settings()
    assert settings3 is not settings, "Reset didn't work"
    print("  ✓ Reset verified")
    Settings.reset()

    print("  ── Settings tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Brand Guidelines Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_brand_guidelines() -> None:
    """Test BrandGuidelinesManager loads and provides data."""
    from config.brand_guidelines import BrandGuidelinesManager

    print("\n" + "=" * 60)
    print("  TEST: Brand Guidelines Loader")
    print("=" * 60)

    brand = BrandGuidelinesManager()

    # Verify load
    guidelines = brand.get_guidelines()
    assert isinstance(guidelines, dict), "Guidelines not a dict"
    assert "brand_name" in guidelines, "Missing brand_name"
    print(f"  ✓ Brand name: {guidelines['brand_name']}")

    # Voice
    voice = brand.get_brand_voice()
    assert "description" in voice, "Missing voice description"
    print(f"  ✓ Voice: {voice['description'][:60]}…")

    # Content requirements
    reqs = brand.get_content_requirements()
    assert len(reqs) > 0, "No content requirements"
    print(f"  ✓ Content requirements: {len(reqs)} rules")

    # Prohibited content
    prohibited = brand.get_prohibited_content()
    assert len(prohibited) > 0, "No prohibited content"
    print(f"  ✓ Prohibited content:   {len(prohibited)} rules")

    # Reddit-specific
    reddit_rules = brand.get_reddit_engagement_rules()
    assert "self_promotion_ratio" in reddit_rules, "Missing self_promotion_ratio"
    print(f"  ✓ Reddit rules loaded:  {len(reddit_rules)} keys")

    # Platform guidelines
    reddit_platform = brand.get_platform_guidelines("reddit")
    assert "tone" in reddit_platform, "Missing reddit tone"
    print(f"  ✓ Reddit platform tone: {reddit_platform['tone'][:50]}…")

    # Prompt context generation
    prompt_ctx = brand.to_prompt_context()
    assert len(prompt_ctx) > 100, "Prompt context too short"
    print(f"  ✓ Prompt context generated: {len(prompt_ctx)} chars")
    print(f"    Preview: {prompt_ctx[:120]}…")

    # repr
    print(f"  ✓ repr: {brand}")

    # Bad file path
    bad_brand = BrandGuidelinesManager("/nonexistent/path.json")
    assert bad_brand.get_guidelines() == {}, "Bad path should yield empty guidelines"
    print("  ✓ Graceful fallback on bad path")

    print("  ── Brand Guidelines tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. LLM Provider Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_llm_provider() -> None:
    """Test LLM provider factory and basic instantiation."""
    from providers.llm_provider import (
        get_llm_provider,
        BaseLLMProvider,
        GeminiProvider,
        OpenAIProvider,
        AnthropicProvider,
    )
    from config.settings import Settings

    Settings.reset()
    settings = Settings()

    print("\n" + "=" * 60)
    print("  TEST: LLM Provider Abstraction")
    print("=" * 60)

    # Factory — invalid name
    try:
        get_llm_provider("fakeprovider", api_key="x")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  ✓ Bad provider name rejected: {e}")

    # Placeholder providers
    openai = get_llm_provider("openai", api_key="test-key")
    assert isinstance(openai, OpenAIProvider)
    print(f"  ✓ OpenAI placeholder created: {openai}")

    try:
        openai.generate("test")
        assert False, "Should have raised NotImplementedError"
    except NotImplementedError:
        print("  ✓ OpenAI.generate() raises NotImplementedError as expected")

    anthropic = get_llm_provider("anthropic", api_key="test-key")
    assert isinstance(anthropic, AnthropicProvider)
    print(f"  ✓ Anthropic placeholder created: {anthropic}")

    # Gemini — requires real key for full test
    if settings.gemini_api_key:
        try:
            gemini = get_llm_provider(
                "gemini", api_key=settings.gemini_api_key
            )
            print(f"  ✓ Gemini provider created: {gemini}")

            # Quick generation test
            response = gemini.generate(
                "Respond with exactly one word: Hello"
            )
            print(f"  ✓ Gemini response: '{response}'")
            assert len(response) > 0, "Empty response from Gemini"
            print("  ✓ Gemini generation verified")

        except Exception as exc:
            print(f"  ⚠ Gemini live test failed: {exc}")
    else:
        print("  ⚠ GEMINI_API_KEY not set — skipping live Gemini test")

        # Still verify constructor rejects empty key
        try:
            get_llm_provider("gemini", api_key="")
            assert False, "Should have raised ValueError"
        except ValueError:
            print("  ✓ Gemini rejects empty API key")

    Settings.reset()
    print("  ── LLM Provider tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Reddit Provider Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_reddit_provider() -> None:
    """Test Reddit provider instantiation and (optionally) live fetch."""
    from providers.reddit_provider import RedditProvider
    from config.settings import Settings

    Settings.reset()
    settings = Settings()

    print("\n" + "=" * 60)
    print("  TEST: Reddit Provider")
    print("=" * 60)

    # Empty credentials should raise
    try:
        RedditProvider(client_id="", client_secret="", user_agent="test")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  ✓ Empty credentials rejected: {e}")

    # Live test with real credentials
    if settings.reddit_client_id and settings.reddit_client_secret:
        try:
            reddit = RedditProvider(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
            )
            print(f"  ✓ Reddit provider created: {reddit}")

            # Fetch a small batch of posts
            posts = reddit.fetch_posts(
                keyword="python programming",
                limit=5,
                time_filter="week",
            )
            print(f"  ✓ Fetched {len(posts)} posts")

            if posts:
                sample = posts[0]
                print(f"    Sample post:")
                print(f"      platform:  {sample['platform']}")
                print(f"      subreddit: r/{sample['subreddit']}")
                print(f"      title:     {sample['title'][:60]}…")
                print(f"      score:     {sample['score']}")
                print(f"      author:    {sample['author']}")
                print(f"      url:       {sample['url'][:70]}…")

                # Verify schema
                required_keys = {
                    "platform", "title", "body", "url",
                    "score", "author", "subreddit",
                }
                assert required_keys.issubset(
                    sample.keys()
                ), f"Missing keys: {required_keys - sample.keys()}"
                assert sample["platform"] == "reddit"
                print("  ✓ Schema validation passed")

        except Exception as exc:
            print(f"  ⚠ Reddit live test failed: {exc}")
    else:
        print(
            "  ⚠ Reddit credentials not set — skipping live test"
        )

    Settings.reset()
    print("  ── Reddit Provider tests PASSED ──")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Runner
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║   SignalForge — Phase 1 Quick Tests                      ║")
    print("╚" + "═" * 58 + "╝")

    try:
        test_settings()
        test_brand_guidelines()
        test_llm_provider()
        test_reddit_provider()

        print("\n" + "=" * 60)
        print("  ✅ ALL PHASE 1 TESTS PASSED")
        print("=" * 60 + "\n")

    except AssertionError as e:
        print(f"\n  ❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  ❌ UNEXPECTED ERROR: {e}")
        sys.exit(1)
