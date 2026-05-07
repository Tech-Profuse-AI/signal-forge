"""
SignalForge Brand Guidelines Manager.

Adapted from social-media-agents BrandGuidelinesManager.
Loads brand-voice, content rules, and Reddit-specific engagement guidelines
from a JSON file and provides structured accessors for downstream agents.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("signalforge.brand_guidelines")

# Default path: config/brand_guidelines.json alongside this module
_DEFAULT_GUIDELINES_PATH = str(
    Path(__file__).resolve().parent / "brand_guidelines.json"
)


class BrandGuidelinesManager:
    """
    Manages brand guidelines for Reddit response generation.

    Mirrors the interface from the reference repo while adding
    Reddit-specific accessors required by SignalForge.
    """

    def __init__(self, guidelines_path: Optional[str] = None) -> None:
        """
        Args:
            guidelines_path: Absolute or relative path to the guidelines JSON.
                             Falls back to the bundled default if omitted.
        """
        self.logger = logging.getLogger(__name__)
        self.guidelines: Dict[str, Any] = {}

        path = guidelines_path or _DEFAULT_GUIDELINES_PATH
        self.load_guidelines(path)

    # ── Loading ───────────────────────────────────────────────────────

    def load_guidelines(self, guidelines_path: str) -> bool:
        """
        Load brand guidelines from a JSON file.

        Returns:
            True on success, False otherwise.
        """
        try:
            if not os.path.exists(guidelines_path):
                self.logger.warning(
                    "Guidelines file not found: %s — using empty defaults",
                    guidelines_path,
                )
                return False

            with open(guidelines_path, "r", encoding="utf-8") as fh:
                self.guidelines = json.load(fh)

            self.logger.info(
                "Loaded brand guidelines from %s (%d top-level keys)",
                guidelines_path,
                len(self.guidelines),
            )
            return True

        except json.JSONDecodeError as exc:
            self.logger.error(
                "Invalid JSON in guidelines file %s: %s",
                guidelines_path,
                exc,
            )
            return False

        except Exception as exc:
            self.logger.error("Error loading guidelines: %s", exc)
            return False

    # ── Core Accessors ────────────────────────────────────────────────

    def get_guidelines(self) -> Dict[str, Any]:
        """Return the full guidelines dictionary."""
        return self.guidelines

    def get_brand_voice(self) -> Dict[str, Any]:
        """Return voice/tone guidelines."""
        return self.guidelines.get("voice", {})

    def get_content_requirements(self) -> List[str]:
        """Return the list of content requirements."""
        return self.guidelines.get("content_requirements", [])

    def get_prohibited_content(self) -> List[str]:
        """Return the list of prohibited content types."""
        return self.guidelines.get("prohibited_content", [])

    def get_product_mentions(self) -> Dict[str, Any]:
        """Return product-mention formatting rules."""
        return self.guidelines.get("product_mentions", {})

    def get_target_audience(self) -> Dict[str, Any]:
        """Return target-audience definitions."""
        return self.guidelines.get("target_audience", {})

    def get_compliance(self) -> Dict[str, Any]:
        """Return compliance / disclosure rules."""
        return self.guidelines.get("compliance", {})

    # ── Reddit-Specific Accessors ─────────────────────────────────────

    def get_reddit_engagement_rules(self) -> Dict[str, Any]:
        """Return Reddit-specific engagement rules (tone, ratio, ethics)."""
        return self.guidelines.get("reddit_engagement_rules", {})

    def get_platform_guidelines(self, platform: str = "reddit") -> Dict[str, Any]:
        """
        Return platform-specific guidelines.

        Args:
            platform: Platform key (defaults to 'reddit').
        """
        platforms = self.guidelines.get("platforms", {})
        return platforms.get(platform.lower(), {})

    # ── Prompt Helpers ────────────────────────────────────────────────

    def to_prompt_context(self) -> str:
        """
        Serialize the most relevant guidelines into a prompt-friendly
        text block that can be injected into LLM system prompts.
        """
        voice = self.get_brand_voice()
        requirements = self.get_content_requirements()
        prohibited = self.get_prohibited_content()
        reddit_rules = self.get_reddit_engagement_rules()

        sections = []

        if voice:
            traits = voice.get("traits", [])
            sections.append(
                "## Brand Voice\n"
                + voice.get("description", "")
                + "\n"
                + "\n".join(f"- {t}" for t in traits)
            )

        if requirements:
            sections.append(
                "## Content Requirements\n"
                + "\n".join(f"- {r}" for r in requirements)
            )

        if prohibited:
            sections.append(
                "## Prohibited Content\n"
                + "\n".join(f"- {p}" for p in prohibited)
            )

        if reddit_rules:
            ethics = reddit_rules.get("engagement_ethics", [])
            sections.append(
                "## Reddit Engagement Rules\n"
                + f"- Tone: {reddit_rules.get('tone', 'N/A')}\n"
                + f"- Self-promotion ratio: {reddit_rules.get('self_promotion_ratio', 'N/A')}\n"
                + f"- Disclosure: {reddit_rules.get('disclosure', 'N/A')}\n"
                + "\n".join(f"- {e}" for e in ethics)
            )

        return "\n\n".join(sections)

    def __repr__(self) -> str:
        name = self.guidelines.get("brand_name", "unknown")
        return f"<BrandGuidelinesManager brand='{name}'>"
