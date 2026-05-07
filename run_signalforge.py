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
    knowledge = ProductKnowledgeAgent(vector_store=vector_store, top_k=3)
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

def run_pipeline(query: str, *, live: bool = False) -> Dict[str, Any]:
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
    )

    logger.info("  Executing pipeline ...")
    state = workflow.invoke(query)

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

    total_opportunities = len(state.get("opportunities", []))
    final_results: List[Dict[str, Any]] = state.get("final_results", [])
    errors: List[Dict[str, Any]] = state.get("errors", [])

    # -- 4. Determine approved / rejected ------------------------------
    approved_items: List[Dict[str, Any]] = []
    rejected_items: List[Dict[str, Any]] = []

    for item in final_results:
        compliance = item.get("compliance", {})
        if compliance.get("approved", False):
            approved_items.append(item)
        else:
            rejected_items.append(item)

    # -- 5. Push approved items to review queue ------------------------
    queue_path = PROJECT_ROOT / "outputs" / ".review_queue.json"
    review_queue = ReviewQueue(queue_path=str(queue_path))
    enqueued_count = 0
    slack_sent_count = 0

    # -- Phase 12: set up Slack HITL handler (mock mode) ---------------
    from integrations.slack_actions import SlackActionsHandler
    from integrations.slack_client import SlackClient

    class _MockSlackWebClient:
        """Captures Slack payloads without calling the network."""
        def __init__(self):
            self.calls = []
        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "channel": kwargs.get("channel", ""), "ts": f"{len(self.calls)}.000100"}

    mock_slack = _MockSlackWebClient()
    slack_client = SlackClient(default_channel="#signalforge-review", client=mock_slack)
    slack_handler = SlackActionsHandler(slack_client=slack_client, review_queue=review_queue)

    for item in approved_items:
        try:
            review_queue.enqueue(item)
            enqueued_count += 1
            # Phase 12: also send Slack review card
            try:
                slack_handler.send_review_item(item)
                slack_sent_count += 1
            except Exception as slack_exc:
                logger.warning(
                    "Failed to send Slack card for %s: %s",
                    item.get("opportunity", {}).get("id", "unknown"),
                    slack_exc,
                )
        except Exception as exc:
            logger.warning(
                "Failed to enqueue item %s: %s",
                item.get("opportunity", {}).get("id", "unknown"),
                exc,
            )

    queue_stats = review_queue.stats
    wall_elapsed = time.time() - wall_start

    # -- 6. Build summary ----------------------------------------------
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
        "review_queue_stats": queue_stats,
    }

    # -- 7. Save to JSON ----------------------------------------------
    output_dir = PROJECT_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "final_results.json"
    output_path.write_text(
        json.dumps(full_output, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    logger.info("  Results saved -> %s", output_path)

    # -- 8. Print final summary ----------------------------------------
    _print_summary(summary, approved_items, queue_stats, wall_elapsed, live=live)

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
            opp_id = opp.get("id", "unknown")
            title = opp.get("title", opp.get("query", "--"))[:50]
            intent_label = intent.get("intent", "--")
            tone = draft.get("tone", "--")
            platform = opp.get("platform", "--")
            print(f"    {i}. [{opp_id}] [{platform}] {title}")
            print(f"       intent={intent_label}  tone={tone}")
        print("-" * 60)

    print(f"  Review Queue Count  : {queue_stats.get('pending', 0)} pending")
    print(f"                      : {queue_stats.get('total', 0)} total")
    print("=" * 60)
    print()


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
