"""
SignalForge Knowledge -- Page 4.

Shows retrieved RAG chunks, sources, and summaries for each
pipeline result's product knowledge context.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from ui import state
from ui.components.cards import render_knowledge_card

state.init_state()

st.header("Product Knowledge Used")
st.caption("This shows which parts of your product docs the AI referenced when writing each reply.")

all_items = state.get_final_results()

if not all_items:
    st.info("No pipeline results yet. Go to the Dashboard and run the pipeline first.")
    st.stop()

# ------------------------------------------------------------------
# Per-item knowledge display
# ------------------------------------------------------------------
col_title, col_toggle = st.columns([3, 1])
with col_toggle:
    st.write("")
    expand_all = st.toggle("Expand All", value=False)

for idx, item in enumerate(all_items):
    opp = item.get("opportunity", {})
    opp_id = opp.get("id", f"item_{idx}")
    title = opp.get("title", "Untitled")[:60]
    knowledge = item.get("knowledge", {})
    draft = item.get("draft", {}).get("draft", "No draft available.")

    chunks = knowledge.get("relevant_context", [])
    sources = knowledge.get("sources", [])
    chunk_count = len(chunks)
    source_count = len(sources)

    is_expanded = expand_all or (idx == 0)

    with st.expander(
        f"**{opp_id}** -- {title}  |  Used {chunk_count} text chunks from {source_count} documents",
        expanded=is_expanded,
    ):
        col_draft, col_know = st.columns(2)
        with col_draft:
            st.markdown("**Generated Draft:**")
            st.info(draft)
        with col_know:
            render_knowledge_card(item)

# ------------------------------------------------------------------
# Test Retrieval
# ------------------------------------------------------------------
st.divider()
st.subheader("Test RAG Retrieval")
st.caption("Type any custom query to see which knowledge chunks are retrieved from the product docs.")
test_query = st.text_input("Custom query", placeholder="e.g. Do we support Slack integration?", key="knowledge_test_query")
if test_query:
    with st.spinner("Retrieving knowledge..."):
        try:
            from agents.product_knowledge_agent import ProductKnowledgeAgent
            agent = ProductKnowledgeAgent()
            result = agent.get_context({"title": test_query})
            st.success(f"Retrieved {len(result['relevant_context'])} chunks")
            render_knowledge_card({"knowledge": result})
        except Exception as e:
            st.error(f"Retrieval failed: {e}")
