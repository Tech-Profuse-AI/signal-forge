"""
SignalForge Slack HITL client - Phase 9.

Builds Slack review payloads for compliant drafts and sends them through the
Slack SDK. Also provides a lightweight webhook-action handler that maps
interactive button clicks back into the local review queue.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, TypedDict
from uuid import uuid4

from schemas.opportunity import serialize_opportunity

try:
    from slack_sdk import WebClient
except ImportError:  # pragma: no cover - covered via injected fake client
    WebClient = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from workflows.review_queue import ReviewQueue

logger = logging.getLogger("signalforge.slack_client")

VALID_REVIEW_ACTIONS = frozenset(["approve", "reject", "edit"])


class SlackApiClient(Protocol):
    """Protocol for real or fake Slack WebClient instances."""

    def chat_postMessage(self, **kwargs: Any) -> Any:
        ...


class ReviewDispatchResult(TypedDict, total=False):
    """Structured result for review-message delivery."""

    review_id: str
    review_status: str
    reviewer_action: str
    final_draft: str
    channel: str
    message_ts: str


class SlackClient:
    """Slack review-message client for SignalForge human-in-the-loop flows."""

    def __init__(
        self,
        token: Optional[str] = None,
        default_channel: Optional[str] = None,
        client: Optional[SlackApiClient] = None,
    ) -> None:
        if client is None:
            if WebClient is None:
                raise ImportError(
                    "slack-sdk is required for SlackClient when no client is injected."
                )
            if not token:
                raise ValueError(
                    "token is required when creating a real Slack WebClient."
                )
            client = WebClient(token=token)

        self._client = client
        self._default_channel = self._clean_text(
            os.environ.get("SLACK_CHANNEL_ID")
            or os.environ.get("SLACK_CHANNEL")
            or default_channel
            or ""
        )
        logger.info(
            "SlackClient initialised - default_channel=%s",
            self._default_channel or "[unset]",
        )

    def send_notification(self, item: Dict[str, Any]) -> ReviewDispatchResult:
        """Send a simple Slack notification for a new opportunity."""
        payload = self.build_review_payload(item)
        channel = self._resolve_channel(item)
        response = self._client.chat_postMessage(
            channel=channel,
            text=payload["text"],
            blocks=payload["blocks"],
            unfurl_links=False,
            unfurl_media=False,
        )

        result: ReviewDispatchResult = {
            "review_id": payload["review_id"],
            "review_status": "pending",
            "reviewer_action": "notified",
            "final_draft": self._review_draft_text(item),
            "channel": channel,
            "message_ts": self._response_value(response, "ts"),
        }
        logger.info(
            "Slack notification sent - review_id=%s channel=%s ts=%s",
            result["review_id"],
            channel,
            result["message_ts"] or "[unknown]",
        )
        return result

    def send_batch(self, items: List[Dict[str, Any]]) -> List[ReviewDispatchResult]:
        """Send a batch of notifications to Slack sequentially."""
        if not isinstance(items, list):
            raise TypeError(f"items must be a list, got {type(items).__name__}")

        logger.info("Sending Slack notification batch - %d items", len(items))
        return [self.send_notification(item) for item in items]

    def build_review_payload(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Build a simple Slack notification payload for a review item."""
        if not self._is_valid_item(item):
            raise ValueError(
                "Review item must include dict values for opportunity, draft, and compliance."
            )

        opportunity = serialize_opportunity(item)
        intent = self._intent_label(item)
        priority = self._priority_line(item)
        draft_text = self._review_draft_text(item)

        platform = self._clean_text(str(opportunity.get("platform", ""))).upper() or "UNKNOWN"
        title = self._clean_text(str(opportunity.get("title", ""))) or "Untitled opportunity"
        title_display = self._truncate(title, 80)
        url = self._clean_text(str(opportunity.get("url", "")))
        
        draft_preview = self._truncate(draft_text, 200)
        
        message_text = (
            f"🎯 *New opportunity found*\n\n"
            f"*Platform:* {platform}\n"
            f"*Title:* {title_display}\n"
            f"*Intent:* {intent}  |  *Score:* {priority}\n"
            f"*URL:* {url}\n\n"
            f"*Draft preview:*\n"
            f"\"{draft_preview}...\"\n\n"
            f"→ Review in dashboard: http://localhost:5173"
        )

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message_text
                }
            }
        ]

        return {
            "review_id": self._resolve_review_id(item),
            "text": f"New opportunity on {platform}: {title_display}",
            "blocks": blocks,
        }

    def send_review(self, item: Dict[str, Any]) -> ReviewDispatchResult:
        """Backward-compatible alias for sending a review card."""
        return self.send_notification(item)

    def build_review_payload(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Build a Slack review payload for a canonical opportunity item."""
        if not self._is_valid_item(item):
            raise ValueError(
                "Review item must include a valid opportunity, URL, and draft."
            )

        opportunity = serialize_opportunity(item)
        intent = self._intent_label(item)
        priority = self._priority_line(item)
        draft_text = self._review_draft_text(item)
        compliance = self._compliance_line(item)
        review_id = self._resolve_review_id(item)

        platform = self._clean_text(str(opportunity.get("platform", ""))).upper() or "UNKNOWN"
        title = self._clean_text(str(opportunity.get("title", ""))) or "Untitled opportunity"
        title_display = self._truncate(title, 80)
        url = self._clean_text(str(opportunity.get("url", "")))
        draft_preview = self._truncate(draft_text, 700)
        summary = self._opportunity_summary(opportunity)
        message_text = f"New opportunity on {platform}: {title_display}"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Opportunity summary*\n"
                        f"*Platform:* {platform}\n"
                        f"*Title:* {title_display}\n"
                        f"*URL:* {url or 'unavailable'}\n"
                        f"{summary}"
                    ),
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Intent*\n{intent}"},
                    {"type": "mrkdwn", "text": f"*Priority score*\n{priority}"},
                    {"type": "mrkdwn", "text": f"*Compliance status*\n{compliance}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Draft*\n{draft_preview}"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "approve",
                        "value": review_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "action_id": "reject",
                        "value": review_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit"},
                        "action_id": "edit",
                        "value": review_id,
                    },
                ],
            },
        ]

        return {
            "review_id": review_id,
            "text": message_text,
            "blocks": blocks,
        }

    def handle_webhook_action(
        self,
        payload: Dict[str, Any],
        review_queue: "ReviewQueue",
    ) -> ReviewDispatchResult:
        """Persist a simplified Slack action payload into the review queue."""
        if not isinstance(payload, dict):
            raise TypeError(f"payload must be a dict, got {type(payload).__name__}")
        return review_queue.handle_action({
            "review_id": payload.get("review_id", ""),
            "action": payload.get("action") or payload.get("reviewer_action", ""),
            "final_draft": payload.get("final_draft", ""),
            "edited_draft": payload.get("edited_draft", ""),
            "reviewer": self._reviewer_name(payload),
        })


    def _resolve_channel(self, item: Dict[str, Any]) -> str:
        channel = self._clean_text(
            str(
                item.get("review_channel")
                or item.get("channel")
                or self._default_channel
            )
        )
        if not channel:
            raise ValueError(
                "A Slack review channel is required. "
                "Provide review_channel on the item or default_channel on SlackClient."
            )
        return channel

    @staticmethod
    def _resolve_review_id(item: Dict[str, Any]) -> str:
        review_id = SlackClient._clean_text(str(item.get("review_id", "")))
        if review_id:
            return review_id

        opportunity = item.get("opportunity", {})
        opportunity_id = SlackClient._clean_text(
            str(
                item.get("opportunity_id")
                or item.get("id")
                or (
                    opportunity.get("id", "")
                    if isinstance(opportunity, dict)
                    else ""
                )
            )
        )
        if opportunity_id:
            return f"review-{opportunity_id}"
        return f"review-{uuid4().hex[:12]}"

    @staticmethod
    def _intent_label(item: Dict[str, Any]) -> str:
        intent_block = item.get("intent")
        opportunity = item.get("opportunity", {})

        flat_intent = SlackClient._clean_text(str(item.get("intent", "")))
        if flat_intent and not isinstance(intent_block, dict):
            confidence = item.get("confidence", "")
            if confidence != "":
                return f"{flat_intent} (confidence: {confidence})"
            return flat_intent

        if isinstance(intent_block, dict):
            intent = SlackClient._clean_text(str(intent_block.get("intent", "")))
            confidence = intent_block.get("confidence", "")
            if intent and confidence != "":
                return f"{intent} (confidence: {confidence})"
            if intent:
                return intent

        return SlackClient._clean_text(str(opportunity.get("intent", ""))) or "unknown"

    @staticmethod
    def _priority_line(item: Dict[str, Any]) -> str:
        score_block = item.get("score")
        opportunity = item.get("opportunity", {})

        if not isinstance(score_block, dict) and score_block not in (None, ""):
            label = SlackClient._clean_text(str(item.get("priority_label", "")))
            if label:
                return f"{score_block} ({label})"
            return str(score_block)

        if isinstance(score_block, dict):
            score = score_block.get("priority_score", "")
            label = SlackClient._clean_text(str(score_block.get("priority_label", "")))
            if score != "" and label:
                return f"{score} ({label})"
            if score != "":
                return str(score)

        scoring = opportunity.get("_scoring")
        if isinstance(scoring, dict):
            score = scoring.get("priority_score", "")
            label = SlackClient._clean_text(str(scoring.get("priority_label", "")))
            if score != "" and label:
                return f"{score} ({label})"
            if score != "":
                return str(score)

        score = opportunity.get("priority_score", "")
        return str(score) if score != "" else "unknown"

    @staticmethod
    def _review_draft_text(item: Dict[str, Any]) -> str:
        final_draft = SlackClient._clean_text(str(item.get("final_draft", "")))
        if final_draft:
            return final_draft

        if isinstance(item.get("draft"), str):
            draft_text = SlackClient._clean_text(str(item.get("draft", "")))
            if draft_text:
                return draft_text

        compliance = item.get("compliance", {})
        draft = item.get("draft", {})

        safe_draft = ""
        if isinstance(compliance, dict):
            safe_draft = SlackClient._clean_text(str(compliance.get("safe_draft", "")))
        if safe_draft:
            return safe_draft

        if isinstance(draft, dict):
            main = SlackClient._clean_text(str(draft.get("draft", "")))
            cta = SlackClient._clean_text(str(draft.get("cta", "")))
            if main and cta and cta.lower() not in main.lower():
                return f"{main} {cta}"
            return main

        return ""

    @staticmethod
    def _compliance_line(item: Dict[str, Any]) -> str:
        if "compliance_approved" in item:
            risk = SlackClient._clean_text(str(item.get("risk_level", "unknown")))
            approved = bool(item.get("compliance_approved", False))
            violations = item.get("violations", [])
            if not isinstance(violations, list):
                violations = []
            violation_text = ", ".join(str(v) for v in violations) if violations else "none"
            return f"{risk} | approved={approved} | violations={violation_text}"

        compliance = item.get("compliance", {})
        if not isinstance(compliance, dict):
            return "unknown"

        risk = SlackClient._clean_text(str(compliance.get("risk_level", "unknown")))
        approved = bool(compliance.get("approved", False))
        violations = compliance.get("violations", [])
        if not isinstance(violations, list):
            violations = []
        violation_text = ", ".join(str(v) for v in violations) if violations else "none"
        return f"{risk} | approved={approved} | violations={violation_text}"

    @staticmethod
    def _opportunity_summary(opportunity: Dict[str, Any]) -> str:
        title = SlackClient._clean_text(str(opportunity.get("title", "")))
        body = SlackClient._clean_text(str(opportunity.get("body", "")))
        if title and body:
            return SlackClient._truncate(f"{title} - {body}", 280)
        return SlackClient._truncate(title or body or "No summary available.", 280)

    @staticmethod
    def _reviewer_name(payload: Dict[str, Any]) -> str:
        reviewer = SlackClient._clean_text(str(payload.get("reviewer", "")))
        if reviewer:
            return reviewer

        user = payload.get("user", {})
        if not isinstance(user, dict):
            return ""

        return (
            SlackClient._clean_text(str(user.get("username", "")))
            or SlackClient._clean_text(str(user.get("name", "")))
            or SlackClient._clean_text(str(user.get("id", "")))
        )

    @staticmethod
    def _response_value(response: Any, key: str) -> str:
        if isinstance(response, dict):
            return SlackClient._clean_text(str(response.get(key, "")))
        return SlackClient._clean_text(str(getattr(response, key, "")))

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        cleaned = SlackClient._clean_text(text)
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3].rstrip() + "..."

    @staticmethod
    def _clean_text(text: str) -> str:
        return " ".join(str(text).split()).strip()

    @staticmethod
    def _is_valid_item(item: Any) -> bool:
        if not isinstance(item, dict):
            return False

        normalized = serialize_opportunity(item)
        return bool(
            normalized.get("title")
            and normalized.get("url")
            and SlackClient._review_draft_text(item)
        )

    def __repr__(self) -> str:
        return (
            f"<SlackClient default_channel='{self._default_channel or '[unset]'}'>"
        )
