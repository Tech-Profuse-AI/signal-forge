"""
SignalForge Phase 17 - Publisher Router.

Routes publish requests to the correct platform publisher and supports
batch publishing with per-item failure isolation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from integrations.platform_publishers import (
    BasePublisher,
    MediumPublisher,
    QuoraPublisher,
    RedditPublisher,
)

logger = logging.getLogger("signalforge.publisher")

_PLATFORM_MAP: Dict[str, BasePublisher] = {
    "reddit": RedditPublisher(),
    "quora": QuoraPublisher(),
    "medium": MediumPublisher(),
}


class PublisherRouter:
    """
    Routes publish requests to the correct platform publisher.

    Tracks success_count and failure_count across all publish calls
    since instantiation.
    """

    def __init__(self) -> None:
        self.success_count: int = 0
        self.failure_count: int = 0
        self._publishers: Dict[str, BasePublisher] = dict(_PLATFORM_MAP)

    def publish(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect platform from item and route to correct publisher.

        Args:
            item: dict with keys: opportunity, draft, platform

        Returns:
            Publisher result dict with: success, platform, published_url, status
        """
        platform = self._detect_platform(item)

        if platform is None:
            self.failure_count += 1
            logger.warning("publish() called with no recognisable platform - item=%r", item)
            return {
                "success": False,
                "platform": "unknown",
                "published_url": None,
                "status": "error: platform not recognised or not provided",
            }

        publisher = self._publishers.get(platform)
        if publisher is None:
            self.failure_count += 1
            logger.warning("No publisher registered for platform '%s'", platform)
            return {
                "success": False,
                "platform": platform,
                "published_url": None,
                "status": f"error: no publisher registered for '{platform}'",
            }

        # Normalise platform key in item before passing to publisher
        normalised = dict(item)
        normalised["platform"] = platform
        result = publisher.publish(normalised)

        if result.get("success"):
            self.success_count += 1
        else:
            self.failure_count += 1

        logger.info(
            "publish() complete - platform=%s success=%s status=%s",
            platform,
            result.get("success"),
            result.get("status"),
        )
        return result

    def publish_batch(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Publish a list of items, continuing if any individual item fails.

        Args:
            items: list of item dicts (same format as publish())

        Returns:
            List of publisher result dicts, one per input item.
        """
        results: List[Dict[str, Any]] = []
        for idx, item in enumerate(items):
            try:
                result = self.publish(item)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "publish_batch() unhandled error at index %d: %s", idx, exc
                )
                self.failure_count += 1
                result = {
                    "success": False,
                    "platform": self._detect_platform(item) or "unknown",
                    "published_url": None,
                    "status": f"error: unhandled exception - {exc}",
                }
            results.append(result)

        logger.info(
            "publish_batch() complete - total=%d success=%d failure=%d",
            len(items),
            self.success_count,
            self.failure_count,
        )
        return results

    def reset_counts(self) -> None:
        """Reset success and failure counters."""
        self.success_count = 0
        self.failure_count = 0

    @staticmethod
    def _detect_platform(item: Dict[str, Any]) -> Optional[str]:
        """
        Detect target platform from item dict.

        Checks item["platform"] first, then opportunity.get("platform"),
        then opportunity.get("source"). Returns lowercase string or None.
        """
        raw = item.get("platform", "")
        if raw:
            return str(raw).lower().strip()

        opportunity = item.get("opportunity", {})
        if isinstance(opportunity, dict):
            for key in ("platform", "source"):
                val = opportunity.get(key, "")
                if val:
                    return str(val).lower().strip()

        return None

    def __repr__(self) -> str:
        return (
            f"<PublisherRouter "
            f"success={self.success_count} "
            f"failure={self.failure_count} "
            f"platforms={list(self._publishers)}>"
        )