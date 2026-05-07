"""
SignalForge Review -- Page 3.

Human-in-the-loop review interface: view drafts, compliance status,
approve / reject / edit each result, and persist actions in session state.

Phase 12: syncs with ReviewQueue as the canonical source of truth so that
Slack-originated decisions are reflected in the UI automatically.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from ui import state
from ui.components.cards import render_draft_card
from ui.components.tables import render_review_actions_table
from workflows.review_queue import ReviewQueue

state.init_state()

# ------------------------------------------------------------------
# ReviewQueue (source of truth, shared with Slack handler)
# ------------------------------------------------------------------
_QUEUE_PATH = _PROJECT_ROOT / "outputs" / ".review_queue.json"

def _get_review_queue() -> ReviewQueue:
    """Return a ReviewQueue instance (cached per page load)."""
    return ReviewQueue(queue_path=str(_QUEUE_PATH))


def _queue_status_for_item(queue: ReviewQueue, opp_id: str) -> dict | None:
    """Look up a review item in the queue by opportunity id."""
    for record in queue.items:
        rid = record.get("review_id", "")
        if rid == f"review-{opp_id}" or rid == opp_id:
            return record
    return None


st.header("Human Review")
st.caption("Review generated drafts, approve, reject, or edit before publishing. This interface syncs directly with Slack.")

all_items = state.get_final_results()

if not all_items:
    st.info("No pipeline results yet. Go to the Dashboard and run the pipeline first.")
    st.stop()

# ------------------------------------------------------------------
# Load queue state
# ------------------------------------------------------------------
queue = _get_review_queue()
queue_stats = queue.stats

# ------------------------------------------------------------------
# Review summary
# ------------------------------------------------------------------
actions = state.get_all_review_actions()
reviewed_count = 0
approved_count = 0
rejected_count = 0
edited_count = 0

# Count from queue state (source of truth), fall back to session state
for idx, item in enumerate(all_items):
    opp = item.get("opportunity", {})
    opp_id = opp.get("id", f"item_{idx}")
    q_record = _queue_status_for_item(queue, opp_id)
    if q_record and q_record.get("review_status") != "pending":
        reviewed_count += 1
        status = q_record.get("review_status", "")
        if status == "approved":
            approved_count += 1
        elif status == "rejected":
            rejected_count += 1
        elif status == "edited":
            edited_count += 1
    elif opp_id in actions:
        reviewed_count += 1
        act = actions[opp_id].get("action", "")
        if act == "approve":
            approved_count += 1
        elif act == "reject":
            rejected_count += 1
        elif act == "edit":
            edited_count += 1

total = len(all_items)
remaining = total - reviewed_count

st.progress(reviewed_count / total if total > 0 else 0.0, text=f"Reviewed {reviewed_count} of {total} items")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Items", total)
col2.metric("Reviewed", reviewed_count)
col3.metric("Remaining", remaining)
col4.metric("Approved", approved_count)
col5.metric("Rejected / Edited", f"{rejected_count} / {edited_count}")

# Sync button
if st.button("🔄 Sync from Slack", help="Reload queue state to reflect Slack decisions"):
    st.rerun()

st.divider()

# ------------------------------------------------------------------
# Bulk Actions
# ------------------------------------------------------------------
st.subheader("Bulk Actions")
bulk_col1, bulk_col2 = st.columns(2)

with bulk_col1:
    if st.button("Approve all Auto-Passed", type="primary", use_container_width=True):
        changed = False
        for idx, item in enumerate(all_items):
            opp_id = item.get("opportunity", {}).get("id", f"item_{idx}")
            if item.get("compliance", {}).get("approved", False):
                q_record = _queue_status_for_item(queue, opp_id)
                existing = state.get_review_action(opp_id)
                status = (q_record.get("review_status") if q_record else "pending") if not existing else existing.get("action")
                if status == "pending":
                    # Update item natively
                    edited = item.get("draft", {}).get("draft", "")
                    if "draft" in item:
                        item["draft"]["draft"] = edited
                    item["final_draft"] = edited

                    state.store_review_action(opp_id, "approve", edited)
                    if q_record:
                        try: queue.handle_action({"review_id": q_record["review_id"], "action": "approve"})
                        except: pass
                    changed = True
        if changed:
            st.rerun()

with bulk_col2:
    if st.button("Reject all Cold Priority", use_container_width=True):
        changed = False
        for idx, item in enumerate(all_items):
            opp_id = item.get("opportunity", {}).get("id", f"item_{idx}")
            if item.get("score", {}).get("priority_label", "") == "cold":
                q_record = _queue_status_for_item(queue, opp_id)
                existing = state.get_review_action(opp_id)
                status = (q_record.get("review_status") if q_record else "pending") if not existing else existing.get("action")
                if status == "pending":
                    state.store_review_action(opp_id, "reject")
                    if q_record:
                        try: queue.handle_action({"review_id": q_record["review_id"], "action": "reject"})
                        except: pass
                    changed = True
        if changed:
            st.rerun()

st.divider()

# ------------------------------------------------------------------
# Queue stats sidebar
# ------------------------------------------------------------------
with st.sidebar:
    st.subheader("Queue Stats")
    for k, v in queue_stats.items():
        st.metric(k.capitalize(), v)

# ------------------------------------------------------------------
# Review each item
# ------------------------------------------------------------------
for idx, item in enumerate(all_items):
    opp = item.get("opportunity", {})
    opp_id = opp.get("id", f"item_{idx}")
    title = opp.get("title", "Untitled")[:60]
    draft = item.get("draft", {})
    compliance = item.get("compliance", {})

    # Determine status: queue first (Slack truth), then session state
    q_record = _queue_status_for_item(queue, opp_id)
    existing_action = state.get_review_action(opp_id)

    status_label = ""
    source_label = ""
    effective_status = ""

    if q_record and q_record.get("review_status") != "pending":
        effective_status = q_record["review_status"]
        source_label = " *(Slack)*"
    elif existing_action:
        effective_status = {
            "approve": "approved",
            "reject": "rejected",
            "edit": "edited",
        }.get(existing_action.get("action", ""), "")

    if effective_status == "approved":
        status_label = f" :green[[APPROVED]]{source_label}"
    elif effective_status == "rejected":
        status_label = f" :red[[REJECTED]]{source_label}"
    elif effective_status == "edited":
        status_label = f" :orange[[EDITED]]{source_label}"

    # Auto-expand pending items
    with st.expander(f"**{opp_id}** -- {title}{status_label}", expanded=(effective_status == "")):
        # Draft & compliance display
        render_draft_card(item)

        st.divider()

        # Editable draft text area
        draft_text = draft.get("draft", "")
        safe_text = compliance.get("safe_draft", "")

        # Use queue final_draft if available (Slack edit), then session, then default
        if q_record and q_record.get("final_draft") and q_record.get("review_status") == "edited":
            display_text = q_record["final_draft"]
        elif existing_action and existing_action.get("edited_draft"):
            display_text = existing_action["edited_draft"]
        else:
            display_text = safe_text if safe_text else draft_text

        edited = st.text_area(
            "Edit draft (optional)",
            value=display_text,
            height=120,
            key=f"edit_draft_{opp_id}",
        )

        # Action buttons
        btn_col1, btn_col2, btn_col3 = st.columns(3)

        with btn_col1:
            if st.button("Approve", key=f"approve_{opp_id}", type="primary", use_container_width=True):
                # Apply draft edit downstream (in case it was edited and then approved)
                if "draft" in item:
                    item["draft"]["draft"] = edited
                item["final_draft"] = edited

                # Dual-write: session state + ReviewQueue
                state.store_review_action(opp_id, "approve", edited)
                state.add_log("INFO", f"Approved: {opp_id}", "review")
                if q_record:
                    try:
                        queue.handle_action({
                            "review_id": q_record["review_id"],
                            "action": "approve",
                        })
                    except Exception:
                        pass  # queue update is best-effort from UI
                st.rerun()

        with btn_col2:
            if st.button("Reject", key=f"reject_{opp_id}", use_container_width=True):
                state.store_review_action(opp_id, "reject")
                state.add_log("INFO", f"Rejected: {opp_id}", "review")
                if q_record:
                    try:
                        queue.handle_action({
                            "review_id": q_record["review_id"],
                            "action": "reject",
                        })
                    except Exception:
                        pass
                st.rerun()

        with btn_col3:
            if st.button("Save Edit", key=f"edit_{opp_id}", use_container_width=True):
                # Update pipeline result item directly for downstream export!
                if "draft" in item:
                    item["draft"]["draft"] = edited
                item["final_draft"] = edited

                state.store_review_action(opp_id, "edit", edited)
                state.add_log("INFO", f"Edited: {opp_id}", "review")
                if q_record:
                    try:
                        queue.handle_action({
                            "review_id": q_record["review_id"],
                            "action": "edit",
                            "edited_draft": edited,
                        })
                    except Exception:
                        pass
                st.rerun()
                
        # Easy copy
        st.markdown("**Copy final draft:**")
        st.code(display_text, language="text")

# ------------------------------------------------------------------
# Review actions summary
# ------------------------------------------------------------------
st.divider()
st.subheader("Review Actions Log")

combined_actions = {}
# First load persistent actions from queue
for record in queue.items:
    if record.get("review_status") != "pending":
        opp_id = record.get("review_id", "").replace("review-", "")
        combined_actions[opp_id] = {
            "action": record.get("review_status"),
            "edited_draft": record.get("final_draft") if record.get("review_status") == "edited" else None,
            "timestamp": "From Queue (Persistent)"
        }
        
# Override with any session actions just taken
for k, v in state.get_all_review_actions().items():
    combined_actions[k] = v

render_review_actions_table(combined_actions)
