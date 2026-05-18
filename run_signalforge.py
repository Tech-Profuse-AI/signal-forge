#!/usr/bin/env python3
"""
SignalForge -- Phase 29: Live Mode Runner.

End-to-end executable that supports both mock and live execution modes:
  1. Accepts a CLI query string
  2. Accepts --mock / --live mode flag
  3. Boots all agents (mock or live, depending on mode)
  4. Executes the full LangGraph pipeline
  5. Pushes approved items to the review queue
  6. Prints stage-by-stage logs and a final summary
  7. Saves structured results to outputs/final_results.json

Usage:
    python run_signalforge.py --mock "AI automation workflow pain points"
    python run_signalforge.py --live --query "community engagement scaling"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# -- Ensure project root is on sys.path --------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# -- Logging -----------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("signalforge.runner")


# ==================================================================
# Mock LLM Providers (deterministic -- no API keys needed)
# ==================================================================

from providers.llm_provider import BaseLLMProvider


class MockIntentLLMProvider(BaseLLMProvider):
    """Deterministic intent classifier for the demo runner."""

    def generate(self, prompt: str, **kwargs) -> str:
        text = prompt.lower()

        if "frustrated" in text or "rant" in text:
            return json.dumps({
                "intent": "churn_risk",
                "confidence": 0.87,
                "reasoning": "The user sounds frustrated with current tooling.",
                "business_relevance": "High - possible switch opportunity.",
                "recommended_action": "respond",
            })

        if "looking for" in text or "recommend" in text or "tool" in text:
            return json.dumps({
                "intent": "buying_intent",
                "confidence": 0.91,
                "reasoning": "The user appears to be evaluating workflow tools.",
                "business_relevance": "High - direct solution discovery.",
                "recommended_action": "respond",
            })

        return json.dumps({
            "intent": "problem_intent",
            "confidence": 0.79,
            "reasoning": "The user is describing a workflow pain point.",
            "business_relevance": "Medium - useful engagement opportunity.",
            "recommended_action": "respond",
        })

    def __repr__(self) -> str:
        return "<MockIntentLLMProvider>"


class MockDraftingLLMProvider(BaseLLMProvider):
    """Deterministic drafting provider for the demo runner."""

    def generate(self, prompt: str, **kwargs) -> str:
        text = prompt.lower()

        if "community" in text:
            return json.dumps({
                "draft": (
                    "A practical way to handle this is to set a few clear rules for "
                    "which conversations need a response first, then keep a lightweight "
                    "playbook for recurring questions so the team is not starting from "
                    "scratch every time."
                ),
                "tone": "casual",
                "cta": "If helpful, I can share a simple response workflow outline.",
                "reasoning": "This keeps the reply helpful and specific without sounding salesy.",
            })

        return json.dumps({
            "draft": (
                "It may help to split the workflow into discovery, prioritization, "
                "and response so the team can focus on the threads that show real "
                "intent instead of trying to answer everything the same way."
            ),
            "tone": "expert",
            "cta": "If useful, I can sketch a lightweight triage approach for that.",
            "reasoning": "The reply stays practical, product-aware, and low-pressure.",
        })

    def __repr__(self) -> str:
        return "<MockDraftingLLMProvider>"


# ==================================================================
# Agent Bootstrap
# ==================================================================

def _boot_agents(*, live: bool) -> Dict[str, Any]:
    """
    Initialise all pipeline agents.

    Args:
        live: If True, uses real LLM providers and live platform scanners.
              If False, uses mock providers and offline data.

    Returns a dict keyed by agent role name.
    """
    from agents.compliance_agent import ComplianceAgent
    from agents.drafting_agent import DraftingAgent
    from agents.intent_agent import IntentAgent
    from agents.product_knowledge_agent import ProductKnowledgeAgent
    from agents.scoring_agent import OpportunityScoringAgent
    from agents.unified_scanner import UnifiedScannerAgent
    from providers.vector_store import LocalChromaVectorStore

    knowledge_dir = PROJECT_ROOT / "knowledge" / "product_docs"
    vector_dir = PROJECT_ROOT / "outputs" / ".vector_cache"
    cache_dir = PROJECT_ROOT / "outputs" / ".scanner_cache"

    mode_label = "LIVE" if live else "MOCK"

    logger.info("=" * 60)
    logger.info("  Booting agents — mode: %s", mode_label)
    logger.info("=" * 60)

    # -- Scanner (UnifiedScannerAgent: Reddit + Quora + Medium) --------
    reddit_provider = None
    if live:
        try:
            from config.settings import Settings
            from providers.reddit_provider import RedditProvider

            settings = Settings()
            if settings.reddit_client_id and settings.reddit_client_secret:
                reddit_provider = RedditProvider(
                    client_id=settings.reddit_client_id,
                    client_secret=settings.reddit_client_secret,
                    user_agent=settings.reddit_user_agent,
                )
                logger.info("  |- RedditProvider            [OK]  (live)")
            else:
                logger.warning("  |- RedditProvider            [SKIP] (no credentials)")
        except Exception as exc:
            logger.warning("  |- RedditProvider            [SKIP] (%s)", exc)

    scanner = UnifiedScannerAgent(
        mock_mode=not live,
        reddit_provider=reddit_provider,
        cache_dir=str(cache_dir),
    )
    logger.info(
        "  |- UnifiedScannerAgent       [OK]  (%s) [reddit=%s, quora=%s, medium=%s]",
        mode_label.lower(),
        scanner.reddit_scanner.scanner.mode,
        scanner.quora_scanner.mode,
        scanner.medium_scanner.mode,
    )

    # -- LLM Providers -------------------------------------------------
    if live:
        from config.settings import Settings
        from providers.llm_provider import get_llm_provider

        settings = Settings()
        settings.validate_llm()
        api_key_map = {
            "gemini": settings.gemini_api_key,
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
        }
        llm = get_llm_provider(
            provider_name=settings.llm_provider,
            api_key=api_key_map[settings.llm_provider],
        )
        intent_llm = llm
        drafting_llm = llm
        logger.info("  |- LLM Provider              [OK]  (%s — live)", llm)
    else:
        intent_llm = MockIntentLLMProvider()
        drafting_llm = MockDraftingLLMProvider()
        logger.info("  |- LLM Provider              [OK]  (mock)")

    intent = IntentAgent(intent_llm)
    logger.info("  |- IntentAgent               [OK]")

    scoring = OpportunityScoringAgent()
    logger.info("  |- OpportunityScoringAgent    [OK]")

    gemini_key = ""
    if live:
        from config.settings import Settings
        settings = Settings()
        gemini_key = settings.gemini_api_key or ""

    vector_store = LocalChromaVectorStore(
        documents_path=str(knowledge_dir),
        persist_directory=str(vector_dir),
        chunk_size=320,
        chunk_overlap=60,
        gemini_api_key=gemini_key,
    )
    knowledge = ProductKnowledgeAgent(vector_store=vector_store, top_k=5)
    logger.info("  |- ProductKnowledgeAgent     [OK]")

    drafting = DraftingAgent(drafting_llm)
    logger.info("  |- DraftingAgent             [OK]")

    compliance = ComplianceAgent()
    logger.info("  |- ComplianceAgent           [OK]")

    logger.info("=" * 60)
    logger.info("  Active mode       : %s", mode_label)
    logger.info("  Active LLM        : %s", intent_llm)
    logger.info("  Active scanners   : Reddit, Quora, Medium (unified)")
    logger.info("  Publishing mode   : %s", os.environ.get("SIGNALFORGE_PUBLISH_MODE", "mock"))
    logger.info("=" * 60)

    return {
        "scanner": scanner,
        "intent": intent,
        "scoring": scoring,
        "knowledge": knowledge,
        "drafting": drafting,
        "compliance": compliance,
    }


# ==================================================================
# Pipeline Execution
# ==================================================================

def _emit_progress(callback: Any, stage: str, items_found: int, payload: Any = None) -> None:
    try:
        callback(stage, items_found, payload)
    except TypeError:
        callback(stage, items_found)


def run_pipeline(query: str, *, live: bool = False, progress_callback: Any = None) -> Dict[str, Any]:
    """
    Execute the full SignalForge pipeline end-to-end.

    Args:
        query: The search query.
        live:  If True, use live providers and real LLM.

    Returns a summary dict with counts and the full final results.
    """
    from workflows.signalforge_graph import SignalForgeGraph
    from workflows.review_queue import ReviewQueue

    wall_start = time.time()

    # -- 1. Boot agents ------------------------------------------------
    logger.info("=" * 60)
    logger.info("  SignalForge -- Phase 29 Runner")
    logger.info("=" * 60)
    logger.info("  Query: %s", query)
    logger.info("  Mode : %s", "LIVE" if live else "MOCK")
    logger.info("=" * 60)

    agents = _boot_agents(live=live)

    # -- 2. Build and run the graph ------------------------------------
    logger.info("-" * 60)
    logger.info("  Building LangGraph workflow ...")
    logger.info("-" * 60)

    workflow = SignalForgeGraph(
        scanner_agent=agents["scanner"],
        intent_agent=agents["intent"],
        scoring_agent=agents["scoring"],
        product_knowledge_agent=agents["knowledge"],
        drafting_agent=agents["drafting"],
        compliance_agent=agents["compliance"],
        progress_callback=progress_callback,
    )

    logger.info("  Executing pipeline (streaming) ...")

    if progress_callback:
        _emit_progress(progress_callback, "scanner", 0)

    state = workflow.run_progressive(query)

    # -- 3. Stage-by-stage log -----------------------------------------
    stages = [
        ("scanner", "opportunities"),
        ("intent", "intent_results"),
        ("scoring", "scored_results"),
        ("product_knowledge", "knowledge_results"),
        ("drafting", "draft_results"),
        ("compliance", "compliance_results"),
    ]

    logger.info("-" * 60)
    logger.info("  Stage Results")
    logger.info("-" * 60)
    for stage_name, key in stages:
        count = len(state.get(key, []))
        logger.info("  |- %-22s  %d items", stage_name, count)

    timings = state.get("timings", {})
    if timings:
        logger.info("-" * 60)
        logger.info("  Stage Timings")
        logger.info("-" * 60)
        for stage_name, stats in timings.items():
            logger.info(
                "  |- %-22s  count=%d avg=%.2fms max=%.2fms total=%.2fms",
                stage_name,
                int(stats.get("count", 0)),
                float(stats.get("avg_ms", 0.0)),
                float(stats.get("max_ms", 0.0)),
                float(stats.get("total_ms", 0.0)),
            )

    total_opportunities = len(state.get("opportunities", []))
    final_results: List[Dict[str, Any]] = state.get("final_results", [])
    errors: List[Dict[str, Any]] = state.get("errors", [])

    # -- 4. Determine approved / rejected ------------------------------
    approved_items: List[Dict[str, Any]] = []
    rejected_items: List[Dict[str, Any]] = []

    for item in final_results:
        compliance = item.get("compliance", {})
        approved = item.get("compliance_approved")
        if approved is None and isinstance(compliance, dict):
            approved = compliance.get("approved", False)
        if approved:
            approved_items.append(item)
        else:
            rejected_items.append(item)

    # -- 5. Push approved items to review queue ------------------------
    queue_path = PROJECT_ROOT / "outputs" / ".review_queue.json"
    review_queue = ReviewQueue(queue_path=str(queue_path))
    enqueued_count = 0
    slack_sent_count = 0

    from integrations.slack_client import SlackClient

    class _MockSlackWebClient:
        """Captures Slack payloads without calling the network."""
        def __init__(self):
            self.calls = []
        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "channel": kwargs.get("channel", ""), "ts": f"{len(self.calls)}.000100"}

    test_mode = os.environ.get("TEST_MODE", "").lower() in {"1", "true", "yes", "on"}
    if os.environ.get("SLACK_BOT_TOKEN") and not test_mode:
        from slack_sdk import WebClient
        slack_web_client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
        logger.info("  Slack client: live (SLACK_BOT_TOKEN set)")
    else:
        slack_web_client = _MockSlackWebClient()
        logger.info("  Slack client: mock (SLACK_BOT_TOKEN not set or TEST_MODE=true)")

    slack_channel = os.environ.get("SLACK_CHANNEL_ID") or os.environ.get("SLACK_CHANNEL", "#signalforge-review")
    slack_client = SlackClient(default_channel=slack_channel, client=slack_web_client)

    for item in approved_items:
        try:
            review_queue.enqueue(item)
            enqueued_count += 1
            # Phase 12: also send Slack review card
            try:
                slack_client.send_notification(item)
                slack_sent_count += 1
            except Exception as slack_exc:
                logger.warning(
                    "Failed to send Slack card for %s: %s",
                    item.get("opportunity_id") or item.get("id", "unknown"),
                    slack_exc,
                )
        except Exception as exc:
            logger.warning(
                "Failed to enqueue item %s: %s",
                item.get("opportunity_id") or item.get("id", "unknown"),
                exc,
            )

    queue_stats = review_queue.stats

    # -- 6. Platform publishing ----------------------------------------
    from integrations.publishing_coordinator import PublishingCoordinator

    publish_mode = os.environ.get("SIGNALFORGE_PUBLISH_MODE", "dry_run").lower().strip()
    published_count = 0
    manual_count = 0
    publish_failed_count = 0

    # Filter items for auto-publishing
    publishable_items = []
    for item in approved_items:
        opp = item.get("opportunity", {})
        intent_data = item.get("intent", {})
        platform = str(
            item.get("platform")
            or (opp.get("platform", "") if isinstance(opp, dict) else "")
        ).lower()
        intent_label = (
            str(intent_data.get("intent", "")).lower()
            if isinstance(intent_data, dict)
            else str(item.get("intent", "")).lower()
        )

        # Extract score
        score = 0
        score_block = item.get("score")
        if isinstance(score_block, dict):
            try:
                score = int(score_block.get("priority_score", 0))
            except (ValueError, TypeError):
                pass
        else:
            try:
                score = int(score_block or item.get("priority_score") or 0)
            except (ValueError, TypeError):
                pass

        if platform == "medium" or (intent_label == "buying_intent" and score >= 60):
            publishable_items.append(item)

    if publish_mode in ("dry_run", "mock"):
        for item in publishable_items:
            draft = item.get("draft", {})
            opp = item.get("opportunity", {})
            title = str(item.get("title") or "")
            if isinstance(draft, dict):
                title = draft.get("title") or draft.get("subject") or ""
            if not title and isinstance(opp, dict):
                title = opp.get("title") or ""
            title = title or "Untitled"
            platform = str(item.get("platform") or "")
            if isinstance(opp, dict):
                platform = platform or str(opp.get("platform", "")).lower()
            logger.info(
                "[DRY RUN] Would publish to %s: %s",
                platform or "unknown", title,
            )
    elif publish_mode == "live":
        coordinator = PublishingCoordinator()
        pub_results = coordinator.publish_all(publishable_items)
        published_count = len(pub_results.get("published", []))
        manual_count = len(pub_results.get("manual_required", []))
        publish_failed_count = len(pub_results.get("failed", []))
    else:
        logger.info("Publishing skipped (mode=%s)", publish_mode)

    wall_elapsed = time.time() - wall_start

    # -- 7. Build summary ----------------------------------------------
    scanner_agent = agents["scanner"]
    source_metrics = {
        "reddit": scanner_agent.reddit_scanner.stats,
        "quora": scanner_agent.quora_scanner.stats,
        "medium": scanner_agent.medium_scanner.stats,
    }

    summary: Dict[str, Any] = {
        "total_opportunities": total_opportunities,
        "processed": len(final_results),
        "approved": len(approved_items),
        "review_queue": queue_stats.get("pending", 0),
        "slack_sent": slack_sent_count,
        "published_count": published_count,
        "manual_count": manual_count,
        "publish_failed": publish_failed_count,
        "failed": len(errors),
        "source_metrics": source_metrics,
    }

    full_output: Dict[str, Any] = {
        "query": query,
        "mode": "live" if live else "mock",
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "elapsed_seconds": round(wall_elapsed, 2),
        "summary": summary,
        "approved_items": approved_items,
        "rejected_items": rejected_items,
        "errors": errors,
        "timings": timings,
        "review_queue_stats": queue_stats,
    }

    # -- 8. Save to JSON ----------------------------------------------
    output_dir = PROJECT_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "final_results.json"
    output_path.write_text(
        json.dumps(full_output, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    logger.info("  Results saved -> %s", output_path)

    # -- 9. Print final summary ----------------------------------------
    _print_summary(summary, approved_items, queue_stats, wall_elapsed, live=live)

    # -- 10. Slack pipeline-complete summary ----------------------------
    _send_slack_summary(
        query=query,
        total=total_opportunities,
        approved=len(approved_items),
        approved_items=approved_items,
        slack_web_client=slack_web_client,
    )

    return full_output


# ==================================================================
# Pretty-print helpers
# ==================================================================

def _print_summary(
    summary: Dict[str, Any],
    approved_items: List[Dict[str, Any]],
    queue_stats: Dict[str, int],
    elapsed: float,
    *,
    live: bool = False,
) -> None:
    """Print a human-readable pipeline summary to stdout."""
    print()
    print("=" * 60)
    print("  SignalForge -- Pipeline Summary")
    print("=" * 60)
    print(f"  Mode                : {'LIVE' if live else 'MOCK'}")
    print(f"  Total opportunities : {summary['total_opportunities']}")
    print(f"  Processed           : {summary['processed']}")
    print(f"  Approved            : {summary['approved']}")
    print(f"  Published           : {summary.get('published_count', 0)}")
    print(f"  Manual required     : {summary.get('manual_count', 0)}")
    print(f"  Publish failed      : {summary.get('publish_failed', 0)}")
    print(f"  Failed              : {summary['failed']}")
    print(f"  Review queue        : {summary['review_queue']}")
    print(f"  Slack cards sent    : {summary.get('slack_sent', 0)}")
    print(f"  Elapsed             : {elapsed:.2f}s")
    print("-" * 60)
    print("  Source Metrics:")
    for source, stats in summary.get("source_metrics", {}).items():
        print(f"    - {source.capitalize():<6}: {stats['fetched']} fetched -> {stats['deduped']} deduped -> {stats['filtered']} filtered")
    print("-" * 60)

    if approved_items:
        print("  Approved Items:")
        for i, item in enumerate(approved_items, 1):
            opp = item.get("opportunity", {})
            draft = item.get("draft", {})
            intent = item.get("intent", {})
            opp_id = item.get("opportunity_id") or item.get("id", "unknown")
            title = str(item.get("title") or "--")[:50]
            if not title.strip("-") and isinstance(opp, dict):
                title = str(opp.get("title", opp.get("query", "--")))[:50]
            intent_label = (
                intent.get("intent", "--")
                if isinstance(intent, dict)
                else item.get("intent", "--")
            )
            tone = (
                draft.get("tone", "--")
                if isinstance(draft, dict)
                else item.get("tone", "--")
            )
            platform = item.get("platform") or (
                opp.get("platform", "--") if isinstance(opp, dict) else "--"
            )
            print(f"    {i}. [{opp_id}] [{platform}] {title}")
            print(f"       intent={intent_label}  tone={tone}")
        print("-" * 60)

    print(f"  Review Queue Count  : {queue_stats.get('pending', 0)} pending")
    print(f"                      : {queue_stats.get('total', 0)} total")
    print("=" * 60)
    print()


# ==================================================================
# Slack Pipeline Summary
# ==================================================================

def _send_slack_summary(
    *,
    query: str,
    total: int,
    approved: int,
    approved_items: List[Dict[str, Any]],
    slack_web_client: Any,
) -> None:
    """
    Post a single Block Kit summary message to Slack when the pipeline finishes.

    If SLACK_BOT_TOKEN is not set (i.e. the client is the mock), log a warning
    and return silently.
    """
    # Guard: skip when running with the mock client
    test_mode = os.environ.get("TEST_MODE", "").lower() in {"1", "true", "yes", "on"}
    if not os.environ.get("SLACK_BOT_TOKEN") or test_mode:
        logger.warning(
            "SLACK_BOT_TOKEN not set or TEST_MODE=true -- skipping Slack pipeline summary"
        )
        return

    # -- Build top-items list (max 3, highest score first) -----------------
    def _extract_score(item: Dict[str, Any]) -> int:
        score_block = item.get("score")
        if isinstance(score_block, dict):
            try:
                return int(score_block.get("priority_score", 0))
            except (ValueError, TypeError):
                return 0
        try:
            return int(score_block or item.get("priority_score") or 0)
        except (ValueError, TypeError):
            return 0

    sorted_items = sorted(approved_items, key=_extract_score, reverse=True)[:3]

    top_lines: List[str] = []
    for item in sorted_items:
        opp = item.get("opportunity", {})
        platform = str(
            item.get("platform")
            or (opp.get("platform", "unknown") if isinstance(opp, dict) else "unknown")
        ).capitalize()
        title_raw = str(
            item.get("title")
            or (opp.get("title", opp.get("query", "Untitled")) if isinstance(opp, dict) else "Untitled")
        )
        title = (title_raw[:57] + "...") if len(title_raw) > 60 else title_raw
        score = _extract_score(item)
        intent_block = item.get("intent", {})
        intent_label = intent_block.get("intent", "unknown") if isinstance(intent_block, dict) else item.get("intent", "unknown")
        top_lines.append(f"• [{platform}] {title} — score: {score} — {intent_label}")

    top_section = "\n".join(top_lines) if top_lines else "_No approved items._"

    # -- Assemble Block Kit message ----------------------------------------
    channel = os.environ.get("SLACK_CHANNEL_ID") or os.environ.get("SLACK_CHANNEL", "#signalforge-review")

    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "\U0001f3af SignalForge Pipeline Complete",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Query*\n{query}"},
                {"type": "mrkdwn", "text": f"*Results*\nFound: {total} opportunities → {approved} approved"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Top items*\n{top_section}",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "→ <http://localhost:5173|Open Dashboard>",
            },
        },
    ]

    fallback_text = (
        f"\U0001f3af SignalForge Pipeline Complete\n"
        f"Query: {query}\n"
        f"Found: {total} opportunities → {approved} approved"
    )

    try:
        slack_web_client.chat_postMessage(
            channel=channel,
            text=fallback_text,
            blocks=blocks,
            unfurl_links=False,
            unfurl_media=False,
        )
        logger.info("Slack pipeline summary sent to %s", channel)
    except Exception as exc:
        logger.warning("Failed to send Slack pipeline summary: %s", exc)


# ==================================================================
# CLI Entry Point
# ==================================================================

def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="SignalForge -- Phase 29 Live Mode Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python run_signalforge.py --mock "AI automation workflow pain points"\n'
            '  python run_signalforge.py --live --query "community engagement scaling"\n'
        ),
    )
    parser.add_argument(
        "query_positional",
        nargs="?",
        default=None,
        help="Query string (positional).",
    )
    parser.add_argument(
        "--query", "-q",
        dest="query_flag",
        default=None,
        help="Query string (named flag).",
    )

    # Mode flags (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Run in mock mode (default). All providers use offline data.",
    )
    mode_group.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Run in live mode. Uses real LLM, live scanners, and real APIs.",
    )

    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    """CLI entry point -- parse args and run the full pipeline."""
    args = parse_args(argv)
    query = args.query_flag or args.query_positional

    if not query:
        print("Error: A query string is required.", file=sys.stderr)
        print('Usage: python run_signalforge.py --mock "your query here"', file=sys.stderr)
        sys.exit(1)

    # Default to mock if neither flag is set
    live = args.live

    return run_pipeline(query, live=live)


if __name__ == "__main__":
    main()
