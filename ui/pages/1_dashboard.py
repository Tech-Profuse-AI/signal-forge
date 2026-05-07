"""
SignalForge Dashboard -- Page 1.

Shows pipeline metrics, query input, Run Pipeline button, and
distribution charts for priority labels and intent types.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import streamlit as st

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from ui import state
from ui.components.metrics import render_summary_metrics, render_queue_metrics, render_distribution_chart

state.init_state()

st.header("Dashboard")
st.warning("⚠️ **MOCK MODE**: The pipeline is currently running with fake data. No real external APIs are being hit.")
st.caption("Run the pipeline, view summary metrics, and explore distributions.")

# ------------------------------------------------------------------
# Query input + Run button
# ------------------------------------------------------------------
st.subheader("Pipeline Query")

query = st.text_input(
    "Enter a search query",
    value=state.get_query() or "AI automation workflow pain points",
    placeholder="e.g. social media scheduling tools",
    key="dashboard_query_input",
)

col_run, col_status = st.columns([1, 3])

with col_run:
    run_clicked = st.button("Run Pipeline", type="primary", use_container_width=True)

with col_status:
    if state.get_active_run():
        elapsed = state.get_active_run().get("elapsed_seconds", 0)
        st.success(f"Last run completed in {elapsed:.2f}s")

if run_clicked and query.strip():
    state.set_query(query.strip())
    state.add_log("INFO", f"Pipeline started for query: {query.strip()}", "runner")

    with st.spinner("Running SignalForge pipeline..."):
        try:
            from run_signalforge import run_pipeline
            result = run_pipeline(query.strip())
            state.store_run(result)
            state.add_log("INFO", f"Pipeline completed -- {result['summary']}", "runner")
            st.rerun()
        except Exception as exc:
            state.add_log("ERROR", f"Pipeline failed: {exc}", "runner")
            st.error(f"Pipeline failed: {exc}")

elif run_clicked:
    st.warning("Please enter a query before running the pipeline.")

# ------------------------------------------------------------------
# Run selector (if multiple runs exist)
# ------------------------------------------------------------------
runs = state.get_runs()

if runs:
    st.divider()
    st.subheader("Pipeline Runs")
    
    # Format runs properly with local time and query
    run_labels = []
    for i, r in enumerate(runs):
        ts = r.get("timestamp", "")
        # try to parse ISO timestamp and format nicely
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            ts_nice = dt.strftime("%H:%M:%S")
        except:
            ts_nice = ts[-8:] if ts else "?"
            
        q = r.get("query", "?")[:40]
        run_labels.append(f"Run {i+1} [{ts_nice}] — {q}")
        
    col_sel, col_clr = st.columns([4, 1])
    with col_sel:
        selected = st.selectbox(
            "Select run to view results:",
            range(len(runs)),
            index=state.get_active_run_index(),
            format_func=lambda i: run_labels[i],
            key="run_selector",
        )
        if selected != state.get_active_run_index():
            state.set_active_run_index(selected)
            st.rerun()
            
    with col_clr:
        st.write("") # spacing
        st.write("")
        if st.button("Clear Session", use_container_width=True):
            import streamlit as st
            st.session_state.clear()
            st.rerun()

# ------------------------------------------------------------------
# Summary metrics
# ------------------------------------------------------------------
st.divider()

summary = state.get_summary()

st.subheader("Current Run Metrics")
if not state.get_active_run():
    st.info("Run the pipeline to see results. Metrics will appear here.")
else:
    render_summary_metrics(summary)
    
    if summary.get("total_opportunities") == 0:
        st.warning("No opportunities found for this query.")

st.write("")
st.subheader("Review Queue (persistent)", help="Queue statistics are saved to disk and survive across runs/restarts.")

# Always try to fetch queue stats globally if not in a run, or from the run
queue_stats = state.get_queue_stats()
if not queue_stats:
    from workflows.review_queue import ReviewQueue
    queue_path = _PROJECT_ROOT / "outputs" / ".review_queue.json"
    if queue_path.exists():
        queue_stats = ReviewQueue(queue_path=str(queue_path)).stats

if not queue_stats:
    st.info("Queue is currently empty.")
else:
    render_queue_metrics(queue_stats)

# ------------------------------------------------------------------
# Distribution charts
# ------------------------------------------------------------------
all_items = state.get_final_results()

if all_items:
    st.divider()
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        render_distribution_chart(
            all_items,
            key="score.priority_label",
            title="Priority Distribution (Hot / Warm / Cold)",
        )

    with chart_col2:
        render_distribution_chart(
            all_items,
            key="intent.intent",
            title="Intent Distribution",
        )

# ------------------------------------------------------------------
# Export
# ------------------------------------------------------------------
if state.get_active_run():
    st.divider()
    st.subheader("Export")
    
    import json
    export_data = {
        **state.get_active_run(),
        "review_actions": state.get_all_review_actions(),
    }
    json_bytes = json.dumps(export_data, indent=2, ensure_ascii=False, default=str).encode("utf-8")
    
    st.download_button(
        label="Download Results as JSON",
        data=json_bytes,
        file_name="signalforge_export.json",
        mime="application/json",
        key="export_btn",
        type="primary"
    )
