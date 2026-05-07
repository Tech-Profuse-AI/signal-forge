"""
SignalForge Slack Actions Handler -- Phase 12.

Bridges interactive Slack actions (approve / reject / edit) into the local
ReviewQueue, and provides a convenience method to send review items to Slack
after they are enqueued.

This module does **not** rebuild the queue or the workflow graph.  It only
wires the existing ``SlackClient`` and ``ReviewQueue`` together so that
human decisions in Slack propagate back into the pipeline state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    pass

from integrations.slack_client import SlackClient, ReviewDispatchResult
from workflows.review_queue import ReviewQueue, ReviewActionResult

logger = logging.getLogger("signalforge.slack_actions")


class SlackActionsHandler:
    """Orchestrates Slack review cards and interactive action callbacks.

    Parameters
    ----------
    slack_client:
        An initialised ``SlackClient`` (real or mock).
    review_queue:
        The ``ReviewQueue`` instance that owns the canonical item state.
    """

    def __init__(
        self,
        slack_client: SlackClient,
        review_queue: ReviewQueue,
    ) -> None:
        self._slack = slack_client
        self._queue = review_queue
        self._dispatch_log: List[ReviewDispatchResult] = []
        logger.info(
            "SlackActionsHandler initialised - slack=%r queue=%r",
            self._slack,
            self._queue,
        )

    # ------------------------------------------------------------------
    # Send a review item to Slack
    # ------------------------------------------------------------------

    def send_review_item(self, item: Dict[str, Any]) -> ReviewDispatchResult:
        """Post a single review card to Slack.

        This is a **side-effect-only** call: the item must already exist in
        the ``ReviewQueue``.  No duplicate queue entries are created.

        Parameters
        ----------
        item:
            A dict with ``opportunity``, ``draft``, ``compliance`` (and
            optionally ``intent``, ``score``, ``review_channel``).

        Returns
        -------
        ReviewDispatchResult
            The Slack delivery metadata (review_id, channel, message_ts, …).
        """
        result = self._slack.send_review(item)
        self._dispatch_log.append(result)
        logger.info(
            "Review item sent to Slack - review_id=%s channel=%s",
            result.get("review_id", ""),
            result.get("channel", ""),
        )
        return result

    def send_review_batch(
        self, items: List[Dict[str, Any]]
    ) -> List[ReviewDispatchResult]:
        """Post multiple review cards to Slack sequentially.

        Each item must already be in the queue.  Returns one dispatch result
        per item.
        """
        logger.info("Sending Slack review batch - %d items", len(items))
        return [self.send_review_item(item) for item in items]

    # ------------------------------------------------------------------
    # Handle interactive Slack actions
    # ------------------------------------------------------------------

    def handle_action(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """Process an interactive Slack action and persist to ReviewQueue.

        Supported actions: ``approve``, ``reject``, ``edit``.

        Parameters
        ----------
        payload:
            A raw Slack interactive payload **or** a simplified dict with
            ``review_id``, ``action``, and optionally ``edited_draft`` and
            ``reviewer``.

        Returns
        -------
        dict
            ``{"review_status": ..., "reviewer_action": ..., "final_draft": ...}``
        """
        result = self._slack.handle_webhook_action(payload, self._queue)
        logger.info(
            "Slack action handled - review_id=%s status=%s action=%s",
            payload.get("review_id", ""),
            result.get("review_status", ""),
            result.get("reviewer_action", ""),
        )
        return result

    def handle_approve(
        self, review_id: str, *, reviewer: str = ""
    ) -> Dict[str, str]:
        """Shortcut: approve an item by review_id."""
        return self.handle_action({
            "review_id": review_id,
            "action": "approve",
            "reviewer": reviewer,
        })

    def handle_reject(
        self, review_id: str, *, reviewer: str = ""
    ) -> Dict[str, str]:
        """Shortcut: reject an item by review_id."""
        return self.handle_action({
            "review_id": review_id,
            "action": "reject",
            "reviewer": reviewer,
        })

    def handle_edit(
        self,
        review_id: str,
        edited_draft: str,
        *,
        reviewer: str = "",
    ) -> Dict[str, str]:
        """Shortcut: edit an item's draft by review_id."""
        return self.handle_action({
            "review_id": review_id,
            "action": "edit",
            "edited_draft": edited_draft,
            "reviewer": reviewer,
        })

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def dispatch_log(self) -> List[ReviewDispatchResult]:
        """Return a copy of all Slack dispatch results sent so far."""
        return list(self._dispatch_log)

    @property
    def queue(self) -> ReviewQueue:
        """Return the underlying ReviewQueue."""
        return self._queue

    @property
    def slack_client(self) -> SlackClient:
        """Return the underlying SlackClient."""
        return self._slack

    def __repr__(self) -> str:
        return (
            f"<SlackActionsHandler dispatched={len(self._dispatch_log)} "
            f"queue={self._queue!r}>"
        )


__all__ = ["SlackActionsHandler"]
