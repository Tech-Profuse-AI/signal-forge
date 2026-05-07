"""
SignalForge UI Session State Manager -- Phase 11.

Centralised helpers for reading and writing Streamlit session state.
All pipeline results, review actions, and log entries flow through here
so that every page sees a consistent view of the data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

logger = logging.getLogger("signalforge.ui.state")

# Keys used in st.session_state
_RUNS = "pipeline_runs"          # List[Dict] -- one entry per pipeline run
_ACTIVE_RUN = "active_run_idx"   # int -- index into _RUNS
_REVIEW_ACTIONS = "review_actions"  # Dict[str, Dict] -- keyed by opportunity id
_LOGS = "logs"                   # List[Dict] -- structured log entries
_QUERY = "current_query"         # str


# ------------------------------------------------------------------
# Initialisation
# ------------------------------------------------------------------

def init_state() -> None:
    """Ensure all required session-state keys exist."""
    if _RUNS not in st.session_state:
        st.session_state[_RUNS] = []
    if _ACTIVE_RUN not in st.session_state:
        st.session_state[_ACTIVE_RUN] = -1
    if _REVIEW_ACTIONS not in st.session_state:
        st.session_state[_REVIEW_ACTIONS] = {}
    if _LOGS not in st.session_state:
        st.session_state[_LOGS] = []
    if _QUERY not in st.session_state:
        st.session_state[_QUERY] = ""


# ------------------------------------------------------------------
# Query
# ------------------------------------------------------------------

def get_query() -> str:
    return st.session_state.get(_QUERY, "")


def set_query(query: str) -> None:
    st.session_state[_QUERY] = query


# ------------------------------------------------------------------
# Pipeline runs
# ------------------------------------------------------------------

def store_run(result: Dict[str, Any]) -> int:
    """Append a pipeline result and set it as the active run. Returns index."""
    init_state()
    st.session_state[_RUNS].append(result)
    idx = len(st.session_state[_RUNS]) - 1
    st.session_state[_ACTIVE_RUN] = idx
    return idx


def get_runs() -> List[Dict[str, Any]]:
    return st.session_state.get(_RUNS, [])


def get_active_run() -> Optional[Dict[str, Any]]:
    runs = get_runs()
    idx = st.session_state.get(_ACTIVE_RUN, -1)
    if 0 <= idx < len(runs):
        return runs[idx]
    return None


def get_active_run_index() -> int:
    return st.session_state.get(_ACTIVE_RUN, -1)


def set_active_run_index(idx: int) -> None:
    st.session_state[_ACTIVE_RUN] = idx


def get_final_results() -> List[Dict[str, Any]]:
    """Return the combined approved + rejected items from the active run."""
    run = get_active_run()
    if not run:
        return []
    return run.get("approved_items", []) + run.get("rejected_items", [])


def get_approved_items() -> List[Dict[str, Any]]:
    run = get_active_run()
    return run.get("approved_items", []) if run else []


def get_rejected_items() -> List[Dict[str, Any]]:
    run = get_active_run()
    return run.get("rejected_items", []) if run else []


def get_summary() -> Dict[str, Any]:
    run = get_active_run()
    return run.get("summary", {}) if run else {}


def get_queue_stats() -> Dict[str, int]:
    run = get_active_run()
    return run.get("review_queue_stats", {}) if run else {}


def get_errors() -> List[Dict[str, Any]]:
    run = get_active_run()
    return run.get("errors", []) if run else []


# ------------------------------------------------------------------
# Review actions
# ------------------------------------------------------------------

def store_review_action(opp_id: str, action: str, edited_draft: str = "") -> None:
    """Record a review action for a specific opportunity."""
    init_state()
    st.session_state[_REVIEW_ACTIONS][opp_id] = {
        "action": action,
        "edited_draft": edited_draft,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_review_action(opp_id: str) -> Optional[Dict[str, Any]]:
    return st.session_state.get(_REVIEW_ACTIONS, {}).get(opp_id)


def get_all_review_actions() -> Dict[str, Dict[str, Any]]:
    return st.session_state.get(_REVIEW_ACTIONS, {})


# ------------------------------------------------------------------
# Logs
# ------------------------------------------------------------------

def add_log(level: str, message: str, stage: str = "") -> None:
    """Append a structured log entry."""
    init_state()
    st.session_state[_LOGS].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "stage": stage,
        "message": message,
    })


def get_logs() -> List[Dict[str, Any]]:
    return st.session_state.get(_LOGS, [])


def clear_logs() -> None:
    st.session_state[_LOGS] = []


# ------------------------------------------------------------------
# Export
# ------------------------------------------------------------------

def export_results_json(output_path: str) -> str:
    """Export the active run results to a JSON file. Returns the path."""
    run = get_active_run()
    if not run:
        raise ValueError("No active pipeline run to export.")

    export_data = {
        **run,
        "review_actions": get_all_review_actions(),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(export_data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return str(path)
