"""
Reusable card components for the SignalForge UI.
"""

from __future__ import annotations
from typing import Any, Dict, Optional

import streamlit as st


def render_opportunity_card(item: Dict[str, Any], expanded: bool = False) -> None:
    """
    Render a single opportunity as an expandable card.

    Expects a FinalResult-shaped dict with keys:
      opportunity, intent, score, knowledge, draft, compliance
    """
    opp = item.get("opportunity", {})
    intent = item.get("intent", {})
    score = item.get("score", {})

    opp_id = opp.get("id", "unknown")
    title = opp.get("title", "Untitled")[:80]
    subreddit = opp.get("subreddit", "")
    priority = score.get("priority_label", "--")
    priority_score = score.get("priority_score", 0)
    intent_label = intent.get("intent", "--")
    confidence = intent.get("confidence", 0)

    # Colour-coded priority badge
    badge_colors = {"hot": "red", "warm": "orange", "cold": "blue", "ignore": "gray"}
    badge = f":{badge_colors.get(priority, 'gray')}[{priority.upper()}]"

    header = f"{badge}  **{title}**  |  r/{subreddit}  |  Score: {priority_score}"

    with st.expander(header, expanded=expanded):
        col1, col2, col3 = st.columns(3)
        col1.markdown(f"**Intent:** `{intent_label}`")
        col2.markdown(f"**Confidence:** `{confidence:.0%}`")
        col3.markdown(f"**Priority:** `{priority}` ({priority_score})")

        # Full post body
        body = opp.get("body", "")
        if body:
            st.markdown("---")
            st.markdown("**Original Post:**")
            st.text(body[:500] + ("..." if len(body) > 500 else ""))

        # Signals
        signals = opp.get("opportunity_signals", [])
        if signals:
            st.markdown(f"**Signals:** {', '.join(signals)}")

        # Score breakdown
        breakdown = score.get("scoring_breakdown", {})
        if breakdown:
            st.markdown("**Score Breakdown:**")
            bd_cols = st.columns(len(breakdown))
            for col, (k, v) in zip(bd_cols, breakdown.items()):
                col.metric(k.replace("_", " ").title(), f"{v:.1f}")

        # Author and URL
        author = opp.get("author", "")
        url = opp.get("url", "")
        meta_parts = []
        if author:
            meta_parts.append(f"u/{author}")
        if url:
            meta_parts.append(f"[Link]({url})")
        if meta_parts:
            st.caption(" | ".join(meta_parts))


def render_draft_card(item: Dict[str, Any]) -> None:
    """Render the draft and compliance info for a pipeline result."""
    draft = item.get("draft", {})
    compliance = item.get("compliance", {})

    draft_text = draft.get("draft", "No draft generated.")
    tone = draft.get("tone", "--")
    cta = draft.get("cta", "")
    reasoning = draft.get("reasoning", "")

    approved = compliance.get("approved", False)
    risk = compliance.get("risk_level", "--")
    violations = compliance.get("violations", [])
    safe_draft = compliance.get("safe_draft", "")
    recommendation = compliance.get("recommendation", "")

    status_icon = ":green[Compliance: AUTO-PASS]" if approved else ":red[Compliance: AUTO-FAIL]"

    st.markdown(f"### {status_icon}  |  Risk: `{risk}`  |  Tone: `{tone}`")

    st.markdown("**Generated Draft:**")
    st.info(draft_text)

    if cta:
        st.markdown(f"**CTA:** {cta}")

    if violations:
        st.markdown(f"**Violations:** `{', '.join(violations)}`")

    if safe_draft and safe_draft != draft_text:
        st.markdown("**Safe Draft (post-compliance):**")
        st.success(safe_draft)

    if recommendation:
        st.caption(f"Recommendation: {recommendation}")

    if reasoning:
        st.caption(f"Reasoning: {reasoning}")


def render_knowledge_card(item: Dict[str, Any]) -> None:
    """Render the knowledge context for a pipeline result."""
    knowledge = item.get("knowledge", {})

    summary = knowledge.get("summary", "No knowledge summary available.")
    sources = knowledge.get("sources", [])
    chunks = knowledge.get("relevant_context", [])

    st.markdown(f"**AI's Document Summary:** {summary}")

    if sources:
        st.markdown(f"**Sources:** {', '.join(str(s) for s in sources)}")

    if chunks:
        st.markdown("**Retrieved Chunks:**")
        for i, chunk in enumerate(chunks, 1):
            source = chunk.get("source", "unknown")
            content = chunk.get("content", "")
            distance = chunk.get("distance")
            
            # Format distance score if available
            score_badge = f" *(Distance: {distance:.3f})*" if distance is not None else ""
            
            st.markdown(f"**Chunk {i}** -- `{source}`{score_badge}")
            st.info(content[:600])
