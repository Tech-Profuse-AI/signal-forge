"""
SignalForge Slack Webhook -- Interactive Actions Endpoint.

FastAPI app that receives Slack interactive payloads (button clicks from
review cards) and routes them to the ReviewQueue and PublishingCoordinator.

Endpoint:
    POST /slack/actions  (application/x-www-form-urlencoded)

Actions:
    approve_{review_id}  -> mark approved, trigger PublishingCoordinator
    edit_{review_id}     -> open modal with draft text for editing
    reject_{review_id}   -> mark rejected
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse

# -- Ensure project root on sys.path ------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger("signalforge.slack_webhook")

app = FastAPI(
    title="SignalForge Slack Webhook",
    description="Handles interactive Slack actions for human-in-the-loop review.",
    version="1.0.0",
)


# ── Helpers ───────────────────────────────────────────────────────────

def _verify_slack_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    signing_secret: str,
) -> bool:
    """
    Verify the request originated from Slack using HMAC-SHA256.

    See: https://api.slack.com/authentication/verifying-requests-from-slack
    """
    if not signing_secret:
        logger.warning("SLACK_SIGNING_SECRET not set -- skipping verification")
        return True

    # Reject requests older than 5 minutes to prevent replay attacks
    try:
        if abs(time.time() - float(timestamp)) > 300:
            logger.warning("Slack request timestamp too old: %s", timestamp)
            return False
    except (ValueError, TypeError):
        logger.warning("Invalid Slack timestamp: %s", timestamp)
        return False

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


def _parse_action_value(value: str) -> tuple[str, str]:
    """
    Parse action value like 'approve_review-abc123' into (action, review_id).

    Returns (action, review_id) or ("", "") if unparseable.
    """
    if not value or "_" not in value:
        return ("", "")

    # Split on the first underscore only
    action, _, review_id = value.partition("_")
    return (action.strip().lower(), review_id.strip())


def _get_review_queue():
    """Lazily build and return a ReviewQueue instance."""
    from workflows.review_queue import ReviewQueue

    queue_path = PROJECT_ROOT / "outputs" / ".review_queue.json"
    return ReviewQueue(queue_path=str(queue_path))


def _get_publishing_coordinator():
    """Lazily build and return a PublishingCoordinator instance."""
    from integrations.publishing_coordinator import PublishingCoordinator

    return PublishingCoordinator()


# ── Endpoints ─────────────────────────────────────────────────────────

@app.post("/slack/actions")
async def handle_slack_action(request: Request):
    """
    Handle interactive Slack action payloads.

    Slack sends an ``application/x-www-form-urlencoded`` body with a
    ``payload`` field containing the JSON action data.
    """
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "").strip()

    # -- Read raw body for signature verification --------------------------
    raw_body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if signing_secret and not _verify_slack_signature(
        raw_body, timestamp, signature, signing_secret
    ):
        logger.warning("Slack signature verification failed")
        return JSONResponse(
            status_code=403,
            content={"error": "Invalid request signature"},
        )

    # -- Parse the form-encoded payload ------------------------------------
    form_data = await request.form()
    payload_raw = form_data.get("payload", "")
    if not payload_raw:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing payload field"},
        )

    try:
        payload: Dict[str, Any] = json.loads(str(payload_raw))
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON in payload"},
        )

    # -- Extract action from the payload -----------------------------------
    actions = payload.get("actions", [])
    if not actions or not isinstance(actions, list):
        return JSONResponse(
            status_code=400,
            content={"error": "No actions found in payload"},
        )

    first_action = actions[0] if isinstance(actions[0], dict) else {}
    action_value = first_action.get("value", "")
    action, review_id = _parse_action_value(action_value)

    if not action or not review_id:
        return JSONResponse(
            status_code=400,
            content={"error": f"Could not parse action value: {action_value}"},
        )

    logger.info(
        "Slack action received -- action=%s review_id=%s",
        action, review_id,
    )

    # -- Route the action --------------------------------------------------
    review_queue = _get_review_queue()

    if action == "approve":
        return _handle_approve(review_id, review_queue, payload)
    elif action == "edit":
        return _handle_edit(review_id, review_queue, payload)
    elif action == "reject":
        return _handle_reject(review_id, review_queue)
    else:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unsupported action: {action}"},
        )


# ── Action handlers ──────────────────────────────────────────────────

def _handle_approve(
    review_id: str,
    review_queue,
    payload: Dict[str, Any],
) -> JSONResponse:
    """Mark approved and trigger PublishingCoordinator."""
    try:
        result = review_queue.handle_action({
            "review_id": review_id,
            "action": "approve",
            "reviewer": _extract_reviewer(payload),
        })
        logger.info("Review approved -- review_id=%s", review_id)
    except (KeyError, ValueError) as exc:
        logger.error("Approve failed for %s: %s", review_id, exc)
        return JSONResponse(
            status_code=200,
            content={"text": f"Failed to approve {review_id}: {exc}"},
        )

    # Trigger publishing for the approved item
    publish_mode = os.environ.get("SIGNALFORGE_PUBLISH_MODE", "dry_run").lower().strip()
    if publish_mode == "live":
        try:
            coordinator = _get_publishing_coordinator()
            # Find the full item from the queue for publishing
            items = review_queue.items
            approved_item = None
            for item in items:
                if item.get("review_id") == review_id:
                    approved_item = item
                    break

            if approved_item:
                pub_result = coordinator.publish_all([approved_item])
                published = len(pub_result.get("published", []))
                manual = len(pub_result.get("manual_required", []))
                logger.info(
                    "Publishing triggered for %s -- published=%d manual=%d",
                    review_id, published, manual,
                )
        except Exception as exc:
            logger.error("Publishing failed for %s: %s", review_id, exc)

    return JSONResponse(
        status_code=200,
        content={
            "text": f"Approved {review_id}. Status: {result.get('review_status', 'approved')}",
        },
    )


def _handle_edit(
    review_id: str,
    review_queue,
    payload: Dict[str, Any],
) -> JSONResponse:
    """
    Open a Slack modal with the draft text for editing.

    The modal submission is handled by a separate trigger_id-based flow.
    For now, return the modal view payload that Slack will render.
    """
    # Find the item to get the current draft
    items = review_queue.items
    current_draft = ""
    for item in items:
        if item.get("review_id") == review_id:
            current_draft = item.get("final_draft", "")
            if not current_draft:
                draft_block = item.get("draft", {})
                if isinstance(draft_block, dict):
                    current_draft = draft_block.get("draft", "")
            break

    trigger_id = payload.get("trigger_id", "")

    if trigger_id:
        # Try to open a Slack modal via the API
        slack_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
        if slack_token:
            try:
                _open_edit_modal(slack_token, trigger_id, review_id, current_draft)
                return JSONResponse(
                    status_code=200,
                    content={"text": f"Opening editor for {review_id}..."},
                )
            except Exception as exc:
                logger.error("Failed to open edit modal for %s: %s", review_id, exc)

    # Fallback: just acknowledge and log
    return JSONResponse(
        status_code=200,
        content={
            "text": (
                f"Edit requested for {review_id}. "
                f"Current draft ({len(current_draft)} chars) is ready for revision."
            ),
        },
    )


def _handle_reject(review_id: str, review_queue) -> JSONResponse:
    """Mark rejected."""
    try:
        result = review_queue.handle_action({
            "review_id": review_id,
            "action": "reject",
        })
        logger.info("Review rejected -- review_id=%s", review_id)
    except (KeyError, ValueError) as exc:
        logger.error("Reject failed for %s: %s", review_id, exc)
        return JSONResponse(
            status_code=200,
            content={"text": f"Failed to reject {review_id}: {exc}"},
        )

    return JSONResponse(
        status_code=200,
        content={
            "text": f"Rejected {review_id}. Status: {result.get('review_status', 'rejected')}",
        },
    )


# ── Slack modal helper ───────────────────────────────────────────────

def _open_edit_modal(
    token: str,
    trigger_id: str,
    review_id: str,
    current_draft: str,
) -> None:
    """Open a Slack modal with the draft text for editing."""
    import urllib.request

    modal_view = {
        "type": "modal",
        "callback_id": f"signalforge_edit_{review_id}",
        "title": {
            "type": "plain_text",
            "text": "Edit Draft",
        },
        "submit": {
            "type": "plain_text",
            "text": "Save",
        },
        "close": {
            "type": "plain_text",
            "text": "Cancel",
        },
        "blocks": [
            {
                "type": "input",
                "block_id": "draft_input",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "draft_text",
                    "multiline": True,
                    "initial_value": current_draft[:3000],
                },
                "label": {
                    "type": "plain_text",
                    "text": f"Draft for {review_id}",
                },
            }
        ],
        "private_metadata": json.dumps({"review_id": review_id}),
    }

    body = json.dumps({
        "trigger_id": trigger_id,
        "view": modal_view,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://slack.com/api/views.open",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(f"Slack views.open failed: {result.get('error', 'unknown')}")

    logger.info("Edit modal opened for %s", review_id)


# ── Utility ──────────────────────────────────────────────────────────

def _extract_reviewer(payload: Dict[str, Any]) -> str:
    """Extract reviewer username from Slack payload."""
    user = payload.get("user", {})
    if isinstance(user, dict):
        return (
            user.get("username", "")
            or user.get("name", "")
            or user.get("id", "")
        )
    return ""


# ── Health check ─────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Simple health check."""
    return {"status": "ok", "service": "signalforge-slack-webhook"}
