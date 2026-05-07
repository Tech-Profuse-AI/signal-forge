"""
SignalForge Logs -- Page 5.

Shows pipeline execution logs, errors, and warnings from the active run
and from session-level structured log entries.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from ui import state
from ui.components.tables import render_errors_table, render_logs_table

state.init_state()

st.header("Pipeline Logs")
st.caption("View execution logs, errors, and warnings.")

if not state.get_runs():
    st.info("Run the pipeline on the Dashboard to see logs.")
    st.stop()

# ------------------------------------------------------------------
# Raw run data (collapsible) - Moved to TOP
# ------------------------------------------------------------------
run = state.get_active_run()
if run:
    with st.expander("Raw Pipeline Output (JSON) - Debug Data", expanded=False):
        st.json(run)
    st.divider()

# ------------------------------------------------------------------
# Pipeline errors from the active run
# ------------------------------------------------------------------
errors = state.get_errors()
st.subheader("Pipeline Errors")
render_errors_table(errors)

# ------------------------------------------------------------------
# Session logs
# ------------------------------------------------------------------
st.divider()
st.subheader("Session Logs")

logs = state.get_logs()

# Calculate counts
levels = {"INFO": 0, "WARNING": 0, "ERROR": 0}
stages = set()
for l in logs:
    lvl = l.get("level", "").upper()
    if lvl in levels:
        levels[lvl] += 1
    stages.add(l.get("stage", "unknown").lower())

st.caption(f"**{levels['ERROR']}** ERRORs | **{levels['WARNING']}** WARNINGs | **{levels['INFO']}** INFOs")

col1, col2 = st.columns(2)

with col1:
    # Safely get index for level
    level_opts = ["ALL", "INFO", "WARNING", "ERROR"]
    default_level = st.session_state.get("log_level_filter", "ALL")
    level_idx = level_opts.index(default_level) if default_level in level_opts else 0
    
    level_filter = st.selectbox(
        "Filter by Level",
        level_opts,
        index=level_idx,
        key="log_level_filter",
    )

with col2:
    # Safely get index for stage
    stage_options = ["ALL"] + sorted(list(stages))
    default_stage = st.session_state.get("log_stage_filter", "ALL")
    stage_idx = stage_options.index(default_stage) if default_stage in stage_options else 0
    
    stage_filter = st.selectbox(
        "Filter by Stage",
        stage_options,
        index=stage_idx,
        key="log_stage_filter",
    )

render_logs_table(logs, level_filter=level_filter, stage_filter=stage_filter)

# ------------------------------------------------------------------
# Clear logs
# ------------------------------------------------------------------
st.divider()
col_refresh, col_clear = st.columns([1, 4])
with col_refresh:
    if st.button("Refresh Logs"):
        st.rerun()
with col_clear:
    if st.button("Clear Session Logs", key="clear_logs_btn"):
        state.clear_logs()
        st.rerun()
