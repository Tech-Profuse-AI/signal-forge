"""
SignalForge Publishing Coordinator.

Single entry point for all platform publishing after compliance approval.
Routes each approved item to the correct publisher based on its platform:

  - reddit  -> RedditPostProvider.post_reply()       (manual-assist)
  - quora   -> QuoraPostProvider.prepare_answer()    (manual-assist)
  - medium  -> MediumPublisher.publish()             (auto-publish when creds set)

Returns a structured result dict with three buckets:
  published, manual_required, failed.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from schemas.opportunity import serialize_opportunity

logger = logging.getLogger("signalforge.publishing_coordinator")


def _extract_title(item: Dict[str, Any]) -> str:
    """Best-effort title extraction from a pipeline item."""
    flat_title = str(item.get("title") or "").strip()
    if flat_title:
        return flat_title
    draft = item.get("draft", {})
    opp = item.get("opportunity", {})
    if isinstance(draft, dict):
        title = draft.get("title") or draft.get("subject") or ""
        if title:
            return str(title).strip()
    if isinstance(opp, dict):
        title = opp.get("title") or opp.get("query") or ""
        if title:
            return str(title).strip()
    return "Untitled"


def _extract_draft_text(item: Dict[str, Any]) -> str:
    """Best-effort draft body extraction from a pipeline item."""
    if isinstance(item.get("draft"), str):
        return str(item.get("draft", "")).strip()
    if item.get("final_draft"):
        return str(item.get("final_draft", "")).strip()
    draft = item.get("draft", {})
    if isinstance(draft, dict):
        text = draft.get("draft") or draft.get("body") or draft.get("content") or ""
        return str(text).strip()
    return ""


def _extract_url(item: Dict[str, Any]) -> str:
    """Return the canonical validated source URL for a pipeline item."""
    flat = serialize_opportunity(item)
    if flat.get("url_valid") is True and flat.get("url"):
        return str(flat.get("url", "")).strip()
    return ""


class PublishingCoordinator:
    """
    Unified publishing coordinator for all platforms.

    Args:
        reddit_post_provider:  Optional pre-built RedditPostProvider instance.
        quora_post_provider:   Optional pre-built QuoraPostProvider instance.
        medium_publisher:      Optional pre-built MediumPublisher instance.
    """

    def __init__(
        self,
        *,
        reddit_post_provider: Optional[Any] = None,
        quora_post_provider: Optional[Any] = None,
        medium_publisher: Optional[Any] = None,
    ) -> None:
        self._reddit_provider = reddit_post_provider
        self._quora_provider = quora_post_provider
        self._medium_publisher = medium_publisher
        logger.info("PublishingCoordinator initialised")

    # ── Lazy provider initialisation ──────────────────────────────────

    def _get_reddit_provider(self) -> Any:
        if self._reddit_provider is None:
            from providers.reddit_post_provider import RedditPostProvider
            self._reddit_provider = RedditPostProvider()
        return self._reddit_provider

    def _get_quora_provider(self) -> Any:
        if self._quora_provider is None:
            from providers.quora_post_provider import QuoraPostProvider
            self._quora_provider = QuoraPostProvider()
        return self._quora_provider

    def _get_medium_publisher(self) -> Any:
        if self._medium_publisher is None:
            from integrations.platform_publishers import MediumPublisher
            self._medium_publisher = MediumPublisher()
        return self._medium_publisher

    # ── Public API ────────────────────────────────────────────────────

    def publish_all(
        self,
        approved_items: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Route each approved item to the correct publisher.

        Args:
            approved_items: Items that passed compliance approval.
                            Each item must contain at minimum:
                            ``opportunity``, ``draft``, ``compliance``.

        Returns:
            ``{"published": [...], "manual_required": [...], "failed": [...]}``
        """
        published: List[Dict[str, Any]] = []
        manual_required: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        for item in approved_items:
            compliance = item.get("compliance", {})
            approved = item.get("compliance_approved")
            if approved is None and isinstance(compliance, dict):
                approved = compliance.get("approved")
            if approved is not True:
                continue

            platform = self._detect_platform(item)
            title = _extract_title(item)

            try:
                if platform == "reddit":
                    result = self._publish_reddit(item)
                elif platform == "quora":
                    result = self._publish_quora(item)
                elif platform == "medium":
                    result = self._publish_medium(item)
                else:
                    logger.warning(
                        "No publisher for platform '%s' — skipping: %s",
                        platform, title,
                    )
                    failed.append({
                        "item": item,
                        "platform": platform or "unknown",
                        "error": f"unsupported platform: {platform}",
                    })
                    continue

                # Classify the result into the correct bucket
                status = result.get("status", "")
                if status == "manual_required" or status == "pending_manual_post":
                    manual_required.append(result)
                    logger.info(
                        "Manual posting required [%s]: %s", platform, title,
                    )
                elif result.get("success"):
                    published.append(result)
                    logger.info(
                        "Published [%s]: %s — url=%s",
                        platform, title, result.get("published_url", ""),
                    )
                else:
                    failed.append({
                        "item": item,
                        "platform": platform,
                        "error": result.get("status", "unknown error"),
                        "result": result,
                    })
                    logger.warning(
                        "Publish failed [%s]: %s — %s",
                        platform, title, result.get("status", ""),
                    )

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Publish error [%s] for '%s': %s", platform, title, exc,
                )
                failed.append({
                    "item": item,
                    "platform": platform or "unknown",
                    "error": str(exc),
                })

        # ── Summary log ──────────────────────────────────────────────
        logger.info(
            "Publishing complete — published=%d manual_required=%d failed=%d",
            len(published), len(manual_required), len(failed),
        )

        return {
            "published": published,
            "manual_required": manual_required,
            "failed": failed,
        }

    # ── Per-platform handlers ─────────────────────────────────────────

    def _publish_reddit(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Route to RedditPostProvider.post_reply() (manual-assist)."""
        url = _extract_url(item)
        draft_text = _extract_draft_text(item)

        if not url:
            return {
                "success": False,
                "platform": "reddit",
                "status": "error: no thread URL found in opportunity",
            }
        if not draft_text:
            return {
                "success": False,
                "platform": "reddit",
                "status": "error: draft text is empty",
            }

        provider = self._get_reddit_provider()
        result = provider.post_reply(thread_url=url, draft_text=draft_text)
        result["platform"] = "reddit"
        result["title"] = _extract_title(item)
        return result

    def _publish_quora(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Route to QuoraPostProvider.prepare_answer() (manual-assist)."""
        url = _extract_url(item)
        draft_text = _extract_draft_text(item)

        if not url:
            return {
                "success": False,
                "platform": "quora",
                "status": "error: no question URL found in opportunity",
            }
        if not draft_text:
            return {
                "success": False,
                "platform": "quora",
                "status": "error: draft text is empty",
            }

        provider = self._get_quora_provider()
        result = provider.prepare_answer(question_url=url, draft_text=draft_text)
        result["platform"] = "quora"
        result["title"] = _extract_title(item)
        return result

    def _publish_medium(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Route to MediumPublisher.publish() (auto-publish when tokens set)."""
        medium_token = os.environ.get("MEDIUM_INTEGRATION_TOKEN", "").strip()
        medium_user_id = os.environ.get("MEDIUM_USER_ID", "").strip()

        if not medium_token or not medium_user_id:
            return {
                "success": False,
                "platform": "medium",
                "status": "error: MEDIUM_INTEGRATION_TOKEN or MEDIUM_USER_ID not set",
            }

        publisher = self._get_medium_publisher()
        flat = serialize_opportunity(item)
        pub_item = {
            "platform": "medium",
            "opportunity": flat,
            "draft": {
                "title": flat.get("title", ""),
                "draft": flat.get("draft", ""),
                "content": flat.get("draft", ""),
                "tags": flat.get("tags", []),
            },
            "compliance": {
                "approved": flat.get("compliance_approved", False),
                "risk_level": flat.get("risk_level", ""),
                "violations": flat.get("violations", []),
            },
        }
        result = publisher.publish(pub_item)
        result["title"] = _extract_title(item)
        return result

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _detect_platform(item: Dict[str, Any]) -> str:
        """Detect the target platform from the item's opportunity dict."""
        opp = item.get("opportunity", {})
        if isinstance(opp, dict):
            platform = opp.get("platform") or opp.get("source") or ""
            if platform:
                return str(platform).lower().strip()

        raw = item.get("platform", "")
        if raw:
            return str(raw).lower().strip()

        return "unknown"

    def __repr__(self) -> str:
        return "<PublishingCoordinator>"
