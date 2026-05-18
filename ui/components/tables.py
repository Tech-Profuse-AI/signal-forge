"""
Reusable table components for the SignalForge UI.
"""

from __future__ import annotations
from typing import Any, Dict, List

import streamlit as st

from schemas.opportunity import serialize_opportunity


def render_opportunities_table(items: List[Dict[str, Any]]) -> None:
    """
    Render pipeline results as a sortable table.

    Each item should be a canonical flat Opportunity-shaped dict.
    """
    if not items:
        st.info("No opportunities to display.")
        return

    import pandas as pd

    rows = []
    for item in items:
        opp = serialize_opportunity(item)

        rows.append({
            "ID": opp.get("opportunity_id") or opp.get("id", "--"),
            "Title": (opp.get("title", "") or "")[:60],
            "Source/Community": opp.get("source", ""),
            "Intent": opp.get("intent", "--"),
            "Confidence (Intent)": round(opp.get("confidence", 0) / 100, 2),
            "Priority Score": opp.get("score", 0),
            "Priority": opp.get("priority_label", "--"),
            "Auto-approved (compliance)": "Yes" if opp.get("compliance_approved") else "No",
            "Risk": opp.get("risk_level", "--"),
        })

    df = pd.DataFrame(rows)
    if "Priority Score" in df.columns:
        df = df.sort_values(by="Priority Score", ascending=False)
        
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Priority Score": st.column_config.NumberColumn(
                help="Score indicating how actionable the thread is. Usually 0-100 scale.",
                format="%.1f"
            ),
            "Confidence (Intent)": st.column_config.NumberColumn(
                help="Confidence that the intent classification is correct.",
                format="%.0%%"
            ),
            "Auto-approved (compliance)": st.column_config.TextColumn(
                help="Automatically approved by the compliance checker."
            )
        },
    )


def render_errors_table(errors: List[Dict[str, Any]]) -> None:
    """Render pipeline errors as a table."""
    if not errors:
        st.success("No errors recorded.")
        return

    import pandas as pd

    rows = []
    for err in errors:
        rows.append({
            "Stage": err.get("stage", "--"),
            "Opportunity ID": err.get("opportunity_id", "--"),
            "Error": err.get("error", ""),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_review_actions_table(actions: Dict[str, Dict[str, Any]]) -> None:
    """Render all review actions taken during this session."""
    if not actions:
        st.info("No review actions taken yet.")
        return

    import pandas as pd

    rows = []
    for opp_id, action in actions.items():
        edited_val = action.get("edited_draft")
        rows.append({
            "Opportunity ID": opp_id,
            "Action": action.get("action", "--"),
            "Edited Draft": (f"{edited_val[:100]}..." if edited_val else "No"),
            "Timestamp": action.get("timestamp", ""),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_logs_table(logs: List[Dict[str, Any]], level_filter: str = "ALL", stage_filter: str = "ALL") -> None:
    """Render structured log entries as a table with optional level and stage filters."""
    if not logs:
        st.info("No log entries.")
        return

    import pandas as pd

    filtered = logs
    if level_filter != "ALL":
        filtered = [l for l in filtered if l.get("level", "").upper() == level_filter.upper()]
        
    if stage_filter != "ALL":
        filtered = [l for l in filtered if l.get("stage", "").lower() == stage_filter.lower()]

    if not filtered:
        st.info("No logs match the current filters.")
        return

    rows = []
    for entry in filtered:
        ts_raw = entry.get("timestamp", "")
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            ts = dt.strftime("%H:%M:%S")
        except:
            ts = ts_raw[-14:-5] if len(ts_raw) > 14 else ts_raw
            
        msg = entry.get("message", "")
        if "{" in msg and "}" in msg and len(msg) > 100:
            # Truncate long JSON-like messages
            msg = msg[:100] + " ... [See JSON export for details]"

        rows.append({
            "Time": ts,
            "Level": entry.get("level", "INFO").upper(),
            "Stage": entry.get("stage", ""),
            "Message": msg,
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
