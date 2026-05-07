#!/usr/bin/env python3
"""
Phase 12 Tests -- Slack HITL Integration.

Validates the full Slack HITL loop:
  - Queue enqueue / dequeue
  - Slack payload generation
  - Approve / reject / edit actions via SlackActionsHandler
  - Workflow resume path via SignalForgeGraph.resume_reviewed_items
  - No duplicate queue entries when Slack cards are sent

Run:
    cd SignalForge
    python -m tests.test_slack_hitl
"""

import json
import logging
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from pprint import pprint
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
)

from integrations.slack_client import SlackClient
from integrations.slack_actions import SlackActionsHandler
from workflows.review_queue import ReviewQueue


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMP_ROOT = PROJECT_ROOT / "tests" / ".tmp_phase12"


class FakeSlackWebClient:
    """Capture Slack payloads without calling the network."""

    def __init__(self) -> None:
        self.calls = []

    def chat_postMessage(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ok": True,
            "channel": kwargs.get("channel", ""),
            "ts": f"{len(self.calls)}.000100",
        }


@contextmanager
def _workspace_tmpdir():
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = TMP_ROOT / f"run_{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _sample_item(
    suffix: str = "001",
    *,
    risk_level: str = "safe",
    approved: bool = True,
) -> dict:
    title = "Need help automating Reddit lead discovery"
    body = (
        "Our team is manually scanning Reddit threads for buyer intent and it is "
        "too slow to keep up with weekly demand."
    )
    draft_text = (
        "A simple way to make this manageable is to separate discovery from "
        "response, then rank threads by intent so the team only spends time on "
        "conversations that look actionable."
    )
    cta_text = "If useful, I can share a lightweight triage workflow."
    final_draft = f"{draft_text} {cta_text}"

    return {
        "review_channel": "#signalforge-review",
        "opportunity": {
            "id": f"opp-{suffix}",
            "title": title,
            "body": body,
            "subreddit": "saas",
            "url": "https://reddit.com/r/saas/example-thread",
            "score": 41,
        },
        "intent": {
            "intent": "buying_intent",
            "confidence": 0.91,
            "recommended_action": "respond",
        },
        "score": {
            "priority_score": 84.5,
            "priority_label": "hot",
            "recommended_action": "respond_immediately",
        },
        "draft": {
            "draft": draft_text,
            "tone": "expert",
            "cta": cta_text,
            "reasoning": "The reply is practical, specific, and low-pressure.",
        },
        "compliance": {
            "approved": approved,
            "risk_level": risk_level,
            "violations": [] if approved else ["excessive_product_mention"],
            "safe_draft": final_draft,
            "recommendation": "Ready for human review.",
        },
    }


# ==================================================================
# Test 1: Queue Enqueue
# ==================================================================

def test_queue_enqueue():
    """Queue items persist locally with correct pending status."""
    print("\n" + "=" * 60)
    print("  TEST 1: Queue Enqueue")
    print("=" * 60)

    with _workspace_tmpdir() as temp_dir:
        queue = ReviewQueue(queue_path=str(temp_dir / "review_queue.json"))

        first = queue.enqueue(_sample_item("001"))
        second = queue.enqueue(_sample_item("002", risk_level="review", approved=False))
        next_item = queue.dequeue()

        assert first["review_status"] == "pending", f"Expected pending, got {first['review_status']}"
        assert second["review_status"] == "pending", f"Expected pending, got {second['review_status']}"
        assert next_item is not None, "dequeue should return the next pending item"
        assert next_item["review_id"] == first["review_id"]

        print(f"  Enqueued item 1: review_id={first['review_id']}  status={first['review_status']}")
        print(f"  Enqueued item 2: review_id={second['review_id']}  status={second['review_status']}")
        print(f"  Dequeued item:   review_id={next_item['review_id']}")
        print("  Queue stats:", queue.stats)

        assert queue.stats["total"] == 2
        assert queue.stats["pending"] == 2
        print("  [OK] Queue Enqueue PASSED")


# ==================================================================
# Test 2: Slack Payload Generation
# ==================================================================

def test_slack_payload_generation():
    """Slack review payloads include the required summary fields and buttons."""
    print("\n" + "=" * 60)
    print("  TEST 2: Slack Payload Generation")
    print("=" * 60)

    fake_client = FakeSlackWebClient()
    slack_client = SlackClient(
        default_channel="#signalforge-review",
        client=fake_client,
    )

    queued_item = _sample_item("003")
    queued_item["review_id"] = "review-opp-003"
    results = slack_client.send_batch([queued_item])

    assert len(results) == 1
    assert len(fake_client.calls) == 1

    payload = fake_client.calls[0]
    blocks = payload["blocks"]
    payload_text = json.dumps(blocks, ensure_ascii=True)

    assert payload["channel"] == "#signalforge-review"
    assert "Opportunity summary" in payload_text, "Missing opportunity summary"
    assert "Intent" in payload_text, "Missing intent"
    assert "Priority score" in payload_text, "Missing priority score"
    assert "Draft" in payload_text, "Missing draft"
    assert "Compliance status" in payload_text, "Missing compliance status"
    assert "Approve" in payload_text, "Missing Approve button"
    assert "Reject" in payload_text, "Missing Reject button"
    assert "Edit" in payload_text, "Missing Edit button"
    assert results[0]["review_status"] == "pending"

    print(f"  Channel: {payload['channel']}")
    print(f"  Blocks count: {len(blocks)}")
    print(f"  Review status: {results[0]['review_status']}")
    print(f"  All required fields present: title, platform, intent, score, draft, compliance, buttons")
    print("  [OK] Slack Payload Generation PASSED")


# ==================================================================
# Test 3: Approve Action
# ==================================================================

def test_approve_action():
    """Approve via SlackActionsHandler updates queue status to approved."""
    print("\n" + "=" * 60)
    print("  TEST 3: Approve Action")
    print("=" * 60)

    with _workspace_tmpdir() as temp_dir:
        queue = ReviewQueue(queue_path=str(temp_dir / "review_queue.json"))
        fake_client = FakeSlackWebClient()
        slack_client = SlackClient(default_channel="#signalforge-review", client=fake_client)
        handler = SlackActionsHandler(slack_client=slack_client, review_queue=queue)

        record = queue.enqueue(_sample_item("020"))
        review_id = record["review_id"]

        print(f"  Before: review_id={review_id}  status={record['review_status']}")

        result = handler.handle_approve(review_id, reviewer="test_reviewer")

        print(f"  After:  review_id={review_id}  status={result['review_status']}  action={result['reviewer_action']}")

        assert result["review_status"] == "approved", f"Expected approved, got {result['review_status']}"
        assert result["reviewer_action"] == "approve"

        # Verify persisted state
        stored = {item["review_id"]: item for item in queue.items}
        assert stored[review_id]["review_status"] == "approved"
        print(f"  Persisted queue status: {stored[review_id]['review_status']}")
        print("  [OK] Approve Action PASSED")


# ==================================================================
# Test 4: Reject Action
# ==================================================================

def test_reject_action():
    """Reject via SlackActionsHandler updates queue status to rejected."""
    print("\n" + "=" * 60)
    print("  TEST 4: Reject Action")
    print("=" * 60)

    with _workspace_tmpdir() as temp_dir:
        queue = ReviewQueue(queue_path=str(temp_dir / "review_queue.json"))
        fake_client = FakeSlackWebClient()
        slack_client = SlackClient(default_channel="#signalforge-review", client=fake_client)
        handler = SlackActionsHandler(slack_client=slack_client, review_queue=queue)

        record = queue.enqueue(_sample_item("030"))
        review_id = record["review_id"]

        print(f"  Before: review_id={review_id}  status={record['review_status']}")

        result = handler.handle_reject(review_id, reviewer="test_reviewer_b")

        print(f"  After:  review_id={review_id}  status={result['review_status']}  action={result['reviewer_action']}")

        assert result["review_status"] == "rejected", f"Expected rejected, got {result['review_status']}"
        assert result["reviewer_action"] == "reject"

        stored = {item["review_id"]: item for item in queue.items}
        assert stored[review_id]["review_status"] == "rejected"
        print(f"  Persisted queue status: {stored[review_id]['review_status']}")
        print("  [OK] Reject Action PASSED")


# ==================================================================
# Test 5: Edit Action
# ==================================================================

def test_edit_action():
    """Edit via SlackActionsHandler updates queue status and stores edited draft."""
    print("\n" + "=" * 60)
    print("  TEST 5: Edit Action")
    print("=" * 60)

    with _workspace_tmpdir() as temp_dir:
        queue = ReviewQueue(queue_path=str(temp_dir / "review_queue.json"))
        fake_client = FakeSlackWebClient()
        slack_client = SlackClient(default_channel="#signalforge-review", client=fake_client)
        handler = SlackActionsHandler(slack_client=slack_client, review_queue=queue)

        record = queue.enqueue(_sample_item("040"))
        review_id = record["review_id"]
        edited_text = (
            "A lighter way to approach this is to rank threads by buyer "
            "signals first, then keep a small response playbook so the "
            "team is not rewriting the same answer from scratch."
        )

        print(f"  Before: review_id={review_id}  status={record['review_status']}")

        result = handler.handle_edit(review_id, edited_text, reviewer="test_reviewer_c")

        print(f"  After:  review_id={review_id}  status={result['review_status']}  action={result['reviewer_action']}")
        print(f"  Edited draft: {result['final_draft'][:80]}...")

        assert result["review_status"] == "edited", f"Expected edited, got {result['review_status']}"
        assert result["reviewer_action"] == "edit"
        assert "rank threads by buyer signals first" in result["final_draft"]

        stored = {item["review_id"]: item for item in queue.items}
        assert stored[review_id]["review_status"] == "edited"
        assert "rank threads by buyer signals first" in stored[review_id]["final_draft"]
        print(f"  Persisted queue status: {stored[review_id]['review_status']}")
        print("  [OK] Edit Action PASSED")


# ==================================================================
# Test 6: Resume Path
# ==================================================================

def test_resume_path():
    """Enqueue items, simulate actions, then resume_reviewed_items splits correctly."""
    print("\n" + "=" * 60)
    print("  TEST 6: Resume Path")
    print("=" * 60)

    with _workspace_tmpdir() as temp_dir:
        queue = ReviewQueue(queue_path=str(temp_dir / "review_queue.json"))
        fake_client = FakeSlackWebClient()
        slack_client = SlackClient(default_channel="#signalforge-review", client=fake_client)
        handler = SlackActionsHandler(slack_client=slack_client, review_queue=queue)

        # Enqueue 3 items
        items = []
        for suffix in ["050", "051", "052"]:
            item = _sample_item(suffix)
            record = queue.enqueue(item)
            items.append(item)
            print(f"  Enqueued: review_id={record['review_id']}  status=pending")

        # Get review IDs
        queue_items = queue.items
        review_ids = [q["review_id"] for q in queue_items]

        # Simulate actions
        handler.handle_approve(review_ids[0], reviewer="alice")
        print(f"  Action: {review_ids[0]} -> approved")

        handler.handle_reject(review_ids[1], reviewer="bob")
        print(f"  Action: {review_ids[1]} -> rejected")

        edited_draft = "Revised response with better tone and clarity."
        handler.handle_edit(review_ids[2], edited_draft, reviewer="carol")
        print(f"  Action: {review_ids[2]} -> edited")

        # Build fake final_results matching the items
        final_results = []
        for item in items:
            final_results.append({
                "opportunity": item["opportunity"],
                "intent": item.get("intent", {}),
                "score": item.get("score", {}),
                "knowledge": {},
                "draft": item["draft"],
                "compliance": item["compliance"],
                "review_state": "paused",
            })

        # Import and call resume_reviewed_items
        from workflows.signalforge_graph import SignalForgeGraph

        resumed, dropped = SignalForgeGraph.resume_reviewed_items(final_results, queue)

        print(f"\n  Resume results:")
        print(f"    Resumed: {len(resumed)} items")
        for r in resumed:
            opp_id = r["opportunity"]["id"]
            print(f"      - {opp_id}  review_state={r['review_state']}")
        print(f"    Dropped: {len(dropped)} items")
        for d in dropped:
            opp_id = d["opportunity"]["id"]
            print(f"      - {opp_id}  review_state={d['review_state']}")

        assert len(resumed) == 2, f"Expected 2 resumed, got {len(resumed)}"
        assert len(dropped) == 1, f"Expected 1 dropped, got {len(dropped)}"

        resumed_ids = {r["opportunity"]["id"] for r in resumed}
        assert "opp-050" in resumed_ids, "Approved item should be resumed"
        assert "opp-052" in resumed_ids, "Edited item should be resumed"

        dropped_ids = {d["opportunity"]["id"] for d in dropped}
        assert "opp-051" in dropped_ids, "Rejected item should be dropped"

        # Check that the edited item carries the new draft
        edited_resumed = [r for r in resumed if r["opportunity"]["id"] == "opp-052"][0]
        assert edited_resumed.get("final_draft") == edited_draft

        for r in resumed:
            assert r["review_state"] == "resumed"
        for d in dropped:
            assert d["review_state"] == "dropped"

        print("\n  Queue state transitions:")
        pprint(queue.stats)
        print("  [OK] Resume Path PASSED")


# ==================================================================
# Test 7: No Duplicate Queue Entries
# ==================================================================

def test_no_duplicate_queue_entries():
    """send_review_item does not create duplicate queue records."""
    print("\n" + "=" * 60)
    print("  TEST 7: No Duplicate Queue Entries")
    print("=" * 60)

    with _workspace_tmpdir() as temp_dir:
        queue = ReviewQueue(queue_path=str(temp_dir / "review_queue.json"))
        fake_client = FakeSlackWebClient()
        slack_client = SlackClient(default_channel="#signalforge-review", client=fake_client)
        handler = SlackActionsHandler(slack_client=slack_client, review_queue=queue)

        item = _sample_item("060")

        # Enqueue first (this is what the runner does)
        record = queue.enqueue(item)
        print(f"  Enqueued: review_id={record['review_id']}")
        print(f"  Queue count after enqueue: {queue.stats['total']}")

        # Then send Slack card (should NOT add another queue entry)
        dispatch = handler.send_review_item(item)
        print(f"  Slack card sent: review_id={dispatch['review_id']}")
        print(f"  Queue count after Slack send: {queue.stats['total']}")

        assert queue.stats["total"] == 1, (
            f"Expected 1 queue item, got {queue.stats['total']}. "
            "send_review_item should not create duplicates."
        )
        assert len(fake_client.calls) == 1, "Exactly one Slack message should be sent"
        assert len(handler.dispatch_log) == 1, "Dispatch log should have 1 entry"

        print("  [OK] No Duplicate Queue Entries PASSED")


# ==================================================================
# Main
# ==================================================================

if __name__ == "__main__":
    print("\n+" + "=" * 58 + "+")
    print("|   SignalForge - Phase 12 Slack HITL Integration Tests    |")
    print("+" + "=" * 58 + "+")

    try:
        test_queue_enqueue()
        test_slack_payload_generation()
        test_approve_action()
        test_reject_action()
        test_edit_action()
        test_resume_path()
        test_no_duplicate_queue_entries()

        print("\n" + "=" * 60)
        print("  ALL PHASE 12 TESTS PASSED [OK]")
        print("=" * 60 + "\n")

    except AssertionError as exc:
        print(f"\n  [FAIL] TEST FAILED: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  [FAIL] UNEXPECTED ERROR: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
