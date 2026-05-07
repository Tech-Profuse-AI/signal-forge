"""
SignalForge Opportunities -- Page 2.

Table view of all discovered opportunities with expandable detail cards.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from ui import state
from ui.components.tables import render_opportunities_table
from ui.components.cards import render_opportunity_card

state.init_state()

st.header("Opportunities")
st.caption("Browse all opportunities discovered by the pipeline.")

all_items = state.get_final_results()

if not all_items:
    st.info("No pipeline results yet. Go to the Dashboard and run the pipeline first.")
    st.stop()

# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------
st.subheader("Filters")
filter_col1, filter_col2, filter_col3 = st.columns(3)

# Collect unique values for filters
priorities = sorted(set(
    item.get("score", {}).get("priority_label", "unknown") for item in all_items
))
intents = sorted(set(
    item.get("intent", {}).get("intent", "unknown") for item in all_items
))
# Fix for Phase 13 Quora Integration
sources = sorted(set(
    item.get("opportunity", {}).get("subreddit") or item.get("opportunity", {}).get("topic", "unknown") for item in all_items
))

with filter_col1:
    selected_priority = st.multiselect(
        "Priority",
        priorities,
        default=st.session_state.get("opp_filter_priority", priorities),
        key="opp_filter_priority",
    )

with filter_col2:
    selected_intent = st.multiselect(
        "Intent",
        intents,
        default=st.session_state.get("opp_filter_intent", intents),
        key="opp_filter_intent",
    )

with filter_col3:
    selected_source = st.multiselect(
        "Source/Community",
        sources,
        default=st.session_state.get("opp_filter_source", sources),
        key="opp_filter_source",
    )

st.write("")
search_query = st.text_input("Search opportunities by title", placeholder="Type a keyword to filter titles...", key="opp_search_query")

# Apply filters
filtered = []
for item in all_items:
    source = item.get("opportunity", {}).get("subreddit") or item.get("opportunity", {}).get("topic", "unknown")
    if (
        item.get("score", {}).get("priority_label", "unknown") in selected_priority
        and item.get("intent", {}).get("intent", "unknown") in selected_intent
        and source in selected_source
    ):
        if search_query:
            if search_query.lower() in (item.get("opportunity", {}).get("title", "") or "").lower():
                filtered.append(item)
        else:
            filtered.append(item)

st.markdown(f"Showing **{len(filtered)}** of {len(all_items)} opportunities")

# ------------------------------------------------------------------
# Table view
# ------------------------------------------------------------------
st.subheader("Table View")
render_opportunities_table(filtered)

# ------------------------------------------------------------------
# Expandable cards
# ------------------------------------------------------------------
st.divider()

col_title, col_toggle = st.columns([3, 1])
with col_title:
    st.subheader("Detail Cards")
with col_toggle:
    show_cards = st.toggle("Show Detail Cards", value=False)

if show_cards:
    for item in filtered:
        render_opportunity_card(item)
else:
    st.info("Detail cards are hidden by default to reduce clutter. Toggle above to view full body text and reasoning.")
