"""
SignalForge Slack HITL client - Phase 9.

Builds Slack review payloads for compliant drafts and sends them through the
Slack SDK. Also provides a lightweight webhook-action handler that maps
interactive button clicks back into the local review queue.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, TypedDict
from uuid import uuid4

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
        self._default_channel = self._clean_text(default_channel or "")
        logger.info(
            "SlackClient initialised - default_channel=%s",
            self._default_channel or "[unset]",
        )

    def send_review(self, item: Dict[str, Any]) -> ReviewDispatchResult:
        """Send a single review item to Slack."""
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
            "reviewer_action": "queued",
            "final_draft": self._review_draft_text(item),
            "channel": channel,
            "message_ts": self._response_value(response, "ts"),
        }
        logger.info(
            "Slack review sent - review_id=%s channel=%s ts=%s",
            result["review_id"],
            channel,
            result["message_ts"] or "[unknown]",
        )
        return result

    def send_batch(self, items: List[Dict[str, Any]]) -> List[ReviewDispatchResult]:
        """Send a batch of review items to Slack sequentially."""
        if not isinstance(items, list):
            raise TypeError(f"items must be a list, got {type(items).__name__}")

        logger.info("Sending Slack review batch - %d items", len(items))
        return [self.send_review(item) for item in items]

    def build_review_payload(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Build a Slack Block Kit payload for a review item."""
        if not self._is_valid_item(item):
            raise ValueError(
                "Review item must include dict values for opportunity, draft, and compliance."
            )

        review_id = self._resolve_review_id(item)
        opportunity = item.get("opportunity", {})
        intent = self._intent_label(item)
        priority = self._priority_line(item)
        draft_text = self._review_draft_text(item)
        compliance_status = self._compliance_line(item)
        summary = self._opportunity_summary(opportunity)
        title = self._clean_text(str(opportunity.get("title", ""))) or "Untitled opportunity"
        subreddit = self._clean_text(str(opportunity.get("subreddit", ""))) or "unknown"
        url = self._clean_text(str(opportunity.get("url", "")))

        action_blocks = self._action_blocks(review_id)
        blocks: List[Dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "SignalForge Review Request",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Opportunity summary*\n{summary}\n\n"
                        f"*Intent*\n{intent}\n\n"
                        f"*Priority score*\n{priority}"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Draft*\n```{self._truncate(draft_text, 1400)}```\n\n"
                        f"*Compliance status*\n{compliance_status}"
                    ),
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"Review ID: `{review_id}` | "
                            f"r/{subreddit} | "
                            f"Title: {self._truncate(title, 90)}"
                        ),
                    }
                ],
            },
        ]

        if url:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Source thread*\n{url}",
                    },
                }
            )

        blocks.append(action_blocks)

        return {
            "review_id": review_id,
            "text": f"SignalForge review request {review_id}: {summary}",
            "blocks": blocks,
        }

    def handle_webhook_action(
        self,
        payload: Dict[str, Any],
        review_queue: "ReviewQueue",
    ) -> Dict[str, str]:
        """
        Handle an interactive Slack action and update the local review queue.

        Supports raw queue-style payloads as well as Slack-style payloads with
        an ``actions`` list whose first action contains a JSON ``value``.
        """
        action_payload = self._normalise_action_payload(payload)
        result = review_queue.handle_action(action_payload)
        logger.info(
            "Handled Slack review action - review_id=%s action=%s status=%s",
            action_payload["review_id"],
            action_payload["action"],
            result["review_status"],
        )
        return result

    def _action_blocks(self, review_id: str) -> Dict[str, Any]:
        buttons = []
        for action, label, style in [
            ("approve", "Approve", "primary"),
            ("reject", "Reject", "danger"),
            ("edit", "Edit", None),
        ]:
            button: Dict[str, Any] = {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": label,
                },
                "action_id": f"signalforge_{action}",
                "value": json.dumps(
                    {"review_id": review_id, "action": action},
                    ensure_ascii=True,
                ),
            }
            if style:
                button["style"] = style
            buttons.append(button)

        return {
            "type": "actions",
            "elements": buttons,
        }

    def _normalise_action_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError(f"payload must be a dict, got {type(payload).__name__}")

        action_payload: Dict[str, Any] = {
            "review_id": self._clean_text(str(payload.get("review_id", ""))),
            "action": self._clean_text(str(payload.get("action", ""))).lower(),
            "edited_draft": self._clean_text(str(payload.get("edited_draft", ""))),
            "reviewer": self._reviewer_name(payload),
        }

        actions = payload.get("actions", [])
        if isinstance(actions, list) and actions:
            first_action = actions[0] if isinstance(actions[0], dict) else {}
            parsed = self._parse_action_value(first_action.get("value", ""))
            action_payload["review_id"] = parsed.get("review_id") or action_payload["review_id"]
            action_payload["action"] = parsed.get("action", action_payload["action"]).lower()

        if action_payload["action"] not in VALID_REVIEW_ACTIONS:
            raise ValueError(
                f"Unsupported review action '{action_payload['action']}'. "
                f"Expected one of: {', '.join(sorted(VALID_REVIEW_ACTIONS))}"
            )
        if not action_payload["review_id"]:
            raise ValueError("Interactive review payload is missing review_id.")

        return action_payload

    @staticmethod
    def _parse_action_value(value: Any) -> Dict[str, str]:
        if isinstance(value, dict):
            return {
                "review_id": SlackClient._clean_text(str(value.get("review_id", ""))),
                "action": SlackClient._clean_text(str(value.get("action", ""))).lower(),
            }

        text = SlackClient._clean_text(str(value))
        if not text:
            return {}

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"action": text.lower()}

        if not isinstance(parsed, dict):
            return {}
        return {
            "review_id": SlackClient._clean_text(str(parsed.get("review_id", ""))),
            "action": SlackClient._clean_text(str(parsed.get("action", ""))).lower(),
        }

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
        opportunity_id = SlackClient._clean_text(str(opportunity.get("id", "")))
        if opportunity_id:
            return f"review-{opportunity_id}"
        return f"review-{uuid4().hex[:12]}"

    @staticmethod
    def _intent_label(item: Dict[str, Any]) -> str:
        intent_block = item.get("intent")
        opportunity = item.get("opportunity", {})

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

        for key in ("opportunity", "draft", "compliance"):
            if key not in item or not isinstance(item[key], dict):
                return False

        return bool(SlackClient._review_draft_text(item))

    def __repr__(self) -> str:
        return (
            f"<SlackClient default_channel='{self._default_channel or '[unset]'}'>"
        )
