"""
SignalForge UI -- Phase 11 Streamlit Application.

Entry point for the internal testing and demo UI.

Run:
    cd SignalForge
    streamlit run ui/app.py
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import streamlit as st

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from ui import state

# ------------------------------------------------------------------
# Page configuration
# ------------------------------------------------------------------
st.set_page_config(
    page_title="SignalForge",
    page_icon="SF",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------
# Custom CSS for a cleaner look
# ------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* Tighten sidebar */
    [data-testid="stSidebar"] {
        min-width: 220px;
        max-width: 300px;
    }
    /* Metric card tweaks */
    [data-testid="stMetric"] {
        background: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 8px;
        padding: 12px 16px;
    }
    /* Dark mode metric cards */
    @media (prefers-color-scheme: dark) {
        [data-testid="stMetric"] {
            background: #1a1a2e;
            border-color: #2a2a4e;
        }
    }
    /* Table header */
    thead tr th {
        font-weight: 600 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------
# Initialise shared state
# ------------------------------------------------------------------
state.init_state()

# ------------------------------------------------------------------
# Sidebar navigation
# ------------------------------------------------------------------
st.sidebar.title("SignalForge")
st.sidebar.caption("Internal Pipeline UI")
st.sidebar.divider()

page = st.sidebar.radio(
    "Navigate",
    [
        "Dashboard",
        "Opportunities",
        "Review",
        "Knowledge",
        "Logs",
    ],
    index=0,
    key="nav_radio",
)

# Sidebar status
run = state.get_active_run()
if run:
    summary = run.get("summary", {})
    st.sidebar.divider()
    st.sidebar.markdown("**Active Run**")
    st.sidebar.markdown(f"Query: `{run.get('query', '--')[:30]}`")
    st.sidebar.markdown(
        f"Results: {summary.get('total_opportunities', 0)} | "
        f"Approved: {summary.get('approved', 0)}"
    )

    actions = state.get_all_review_actions()
    if actions:
        approved = sum(1 for a in actions.values() if a["action"] == "approve")
        rejected = sum(1 for a in actions.values() if a["action"] == "reject")
        edited = sum(1 for a in actions.values() if a["action"] == "edit")
        st.sidebar.markdown(
            f"Reviewed: {approved} approved, {rejected} rejected, {edited} edited"
        )

total_runs = len(state.get_runs())
if total_runs > 0:
    st.sidebar.divider()
    st.sidebar.caption(f"{total_runs} pipeline run(s) this session")

# ------------------------------------------------------------------
# Page routing
# ------------------------------------------------------------------
# Using runpy.run_path so each page file gets __file__ set correctly,
# which is required for Path(__file__)-based project root resolution.

_PAGES_DIR = Path(__file__).resolve().parent / "pages"

_PAGE_MAP = {
    "Dashboard": _PAGES_DIR / "1_dashboard.py",
    "Opportunities": _PAGES_DIR / "2_opportunities.py",
    "Review": _PAGES_DIR / "3_review.py",
    "Knowledge": _PAGES_DIR / "4_knowledge.py",
    "Logs": _PAGES_DIR / "5_logs.py",
}

page_file = _PAGE_MAP.get(page)
if page_file and page_file.exists():
    runpy.run_path(str(page_file), run_name="__main__")
else:
    st.error(f"Page not found: {page}")

