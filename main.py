#!/usr/bin/env python3
"""
SignalForge — Phase 1 Entry Point.

Initialises the four foundational modules:
  1. Settings      — environment-driven configuration
  2. LLM Provider  — swappable Gemini / OpenAI / Anthropic
  3. Reddit Provider — PRAW-based post fetching
  4. Brand Guidelines — Reddit-first engagement rules

No business logic, no agents, no LangGraph, no orchestration.
Run this to verify that the foundation boots correctly.
"""

import logging
import sys

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-32s │ %(levelname)-7s │ %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("signalforge")


def main() -> None:
    """Boot the SignalForge foundation and print a status summary."""

    logger.info("=" * 60)
    logger.info("  SignalForge — Phase 1 Initialisation")
    logger.info("=" * 60)

    # ── 1. Settings ───────────────────────────────────────────────────
    from config.settings import Settings

    settings = Settings()
    logger.info("Settings loaded: %s", settings)

    # ── 2. Brand Guidelines ───────────────────────────────────────────
    from config.brand_guidelines import BrandGuidelinesManager

    brand = BrandGuidelinesManager()
    logger.info("Brand guidelines loaded: %s", brand)
    logger.info(
        "  Voice: %s",
        brand.get_brand_voice().get("description", "N/A")[:80],
    )
    logger.info(
        "  Reddit engagement rules loaded: %d keys",
        len(brand.get_reddit_engagement_rules()),
    )

    # ── 3. LLM Provider ──────────────────────────────────────────────
    from providers.llm_provider import get_llm_provider

    try:
        settings.validate_llm()
        api_key_map = {
            "gemini": settings.gemini_api_key,
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
        }
        llm = get_llm_provider(
            provider_name=settings.llm_provider,
            api_key=api_key_map[settings.llm_provider],
        )
        logger.info("LLM Provider ready: %s", llm)
    except (EnvironmentError, ValueError) as exc:
        logger.warning("LLM Provider skipped — %s", exc)
        llm = None

    # ── 4. Reddit Provider ────────────────────────────────────────────
    from providers.reddit_provider import RedditProvider

    try:
        settings.validate_reddit()
        reddit = RedditProvider(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        logger.info("Reddit Provider ready: %s", reddit)
    except (EnvironmentError, ValueError) as exc:
        logger.warning("Reddit Provider skipped — %s", exc)
        reddit = None

    # ── Summary ───────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  Phase 1 Foundation Status")
    logger.info("  ├─ Settings:        ✓ loaded")
    logger.info(
        "  ├─ Brand Guidelines: ✓ loaded (%s)",
        brand.get_guidelines().get("brand_name", "unknown"),
    )
    logger.info(
        "  ├─ LLM Provider:    %s",
        f"✓ {llm}" if llm else "⚠ not configured",
    )
    logger.info(
        "  └─ Reddit Provider:  %s",
        f"✓ {reddit}" if reddit else "⚠ not configured",
    )
    logger.info("=" * 60)
    logger.info("  Phase 1 initialisation complete. Ready for Phase 2.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
