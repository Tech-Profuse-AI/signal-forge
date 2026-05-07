"""
Reusable metric display components for the SignalForge UI.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

import streamlit as st


def render_metric_row(metrics: List[Dict[str, Any]]) -> None:
    """
    Render a horizontal row of metric cards.

    Each metric dict should have:
      - label (str)
      - value (int | float | str)
      - delta (optional str)  -- e.g. "+3"
      - color (optional str)  -- "green", "red", "orange", "blue"
    """
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        delta = m.get("delta")
        col.metric(
            label=m["label"],
            value=m["value"],
            delta=delta,
        )


def render_summary_metrics(summary: Dict[str, Any]) -> None:
    """Render the standard pipeline summary as a metric row."""
    if not summary:
        st.info("Run the pipeline to see metrics.")
        return

    metrics = [
        {"label": "Total Opportunities", "value": summary.get("total_opportunities", 0)},
        {"label": "Processed", "value": summary.get("processed", 0)},
        {"label": "Approved", "value": summary.get("approved", 0)},
        {"label": "Failed", "value": summary.get("failed", 0)},
    ]
    render_metric_row(metrics)


def render_queue_metrics(stats: Dict[str, int]) -> None:
    """Render the persistent review queue stats."""
    if not stats:
        st.info("No queue statistics available.")
        return

    metrics = [
        {"label": "Pending", "value": stats.get("pending", 0)},
        {"label": "Approved", "value": stats.get("approved", 0)},
        {"label": "Rejected", "value": stats.get("rejected", 0)},
        {"label": "Edited", "value": stats.get("edited", 0)},
        {"label": "Total Queue", "value": stats.get("total", 0)},
    ]
    render_metric_row(metrics)


def render_distribution_chart(items: List[Dict[str, Any]], key: str, title: str) -> None:
    """
    Render a bar chart showing the distribution of a given key across items.

    Args:
        items: List of pipeline result dicts.
        key: Dot-separated key path e.g. "score.priority_label" or "intent.intent".
        title: Chart title.
    """
    if not items:
        return

    counts: Dict[str, int] = {}
    for item in items:
        parts = key.split(".")
        val = item
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part, "unknown")
            else:
                val = "unknown"
                break
        label = str(val) if val else "unknown"
        counts[label] = counts.get(label, 0) + 1

    if not counts:
        return

    import pandas as pd
    import altair as alt

    st.subheader(title)
    df = pd.DataFrame(
        {"Category": list(counts.keys()), "Count": list(counts.values())}
    )
    
    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X('Category', sort='-y', axis=alt.Axis(labelAngle=0)),
        y='Count'
    )
    text = chart.mark_text(
        align='center',
        baseline='bottom',
        dy=-5  # Nudge text up so it doesn't overlap with the bar
    ).encode(
        text='Count'
    )
    
    st.altair_chart(chart + text, use_container_width=True)
