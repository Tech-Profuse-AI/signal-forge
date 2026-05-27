"""
SignalForge LangGraph Orchestration -- Phase 8.

Connects the existing agents into a single executable workflow:

scanner -> intent -> scoring -> product_knowledge -> drafting -> compliance

This module does not rebuild any business logic. It only orchestrates the
existing agents and preserves structured metadata across all stages.
"""

from __future__ import annotations

import logging
import inspect
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterator, List, Optional, Tuple, TypedDict

import langchain_core.messages as langchain_messages
import langchain_core.runnables.config as langchain_runnable_config
from langchain_core.messages import BaseMessage
from typing_extensions import NotRequired

from agents.compliance_agent import ComplianceAgent
from agents.drafting_agent import DraftingAgent
from agents.intent_agent import IntentAgent
from agents.opportunity_scanner.agent import OpportunityScannerAgent
from agents.product_knowledge_agent import ProductKnowledgeAgent
from agents.scoring_agent import OpportunityScoringAgent
from schemas.opportunity import serialize_opportunity

logger = logging.getLogger("signalforge.graph")


def _ensure_langgraph_compatibility() -> None:
    """
    Patch the local LangGraph/LangChain mismatch enough for StateGraph usage.

    The installed `langgraph` package expects a newer `langchain_core` surface
    than the one available in this workspace. StateGraph itself works once the
    missing compatibility symbols are restored.
    """
    if not hasattr(langchain_messages, "RemoveMessage"):
        class RemoveMessage(BaseMessage):
            type: str = "remove"

        langchain_messages.RemoveMessage = RemoveMessage

    if not hasattr(langchain_runnable_config, "CONFIG_KEYS"):
        langchain_runnable_config.CONFIG_KEYS = [
            "tags",
            "metadata",
            "callbacks",
            "run_name",
            "max_concurrency",
            "recursion_limit",
            "configurable",
            "run_id",
        ]

    if not hasattr(langchain_runnable_config, "COPIABLE_KEYS"):
        langchain_runnable_config.COPIABLE_KEYS = [
            "tags",
            "metadata",
            "callbacks",
            "configurable",
        ]


_ensure_langgraph_compatibility()

from langgraph.graph import END, START, StateGraph


OpportunityPayload = Dict[str, Any]
IntentPayload = Dict[str, Any]
ScorePayload = Dict[str, Any]
KnowledgePayload = Dict[str, Any]
DraftPayload = Dict[str, Any]
CompliancePayload = Dict[str, Any]


class FinalResult(TypedDict, total=False):
    id: str
    opportunity_id: str
    review_id: str
    platform: str
    title: str
    url: str
    draft: str
    score: int
    status: str
    intent: str
    confidence: int
    summary: str
    source: str
    priority_label: str
    compliance_approved: bool
    risk_level: str
    violations: List[str]
    review_state: str  # "paused" | "dropped" | "resumed"


class PipelineError(TypedDict):
    stage: str
    opportunity_id: Optional[str]
    error: str


class SignalForgeInputState(TypedDict):
    query: str


class SignalForgeState(TypedDict):
    query: str
    opportunities: List[OpportunityPayload]
    intent_results: List[IntentPayload]
    scored_results: List[ScorePayload]
    knowledge_results: List[KnowledgePayload]
    draft_results: List[DraftPayload]
    compliance_results: List[CompliancePayload]
    final_results: List[FinalResult]
    errors: NotRequired[List[PipelineError]]
    success_count: NotRequired[int]
    failure_count: NotRequired[int]
    timings: NotRequired[Dict[str, Any]]


class PipelineProfiler:
    """Thread-safe stage timing collector for pipeline execution."""

    def __init__(self, stage_logger: logging.Logger) -> None:
        self._logger = stage_logger
        self._lock = threading.Lock()
        self._stats: Dict[str, Dict[str, float]] = {}

    @contextmanager
    def measure(
        self,
        stage: str,
        opportunity_id: Optional[str] = None,
        **metadata: Any,
    ) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            with self._lock:
                stats = self._stats.setdefault(
                    stage,
                    {
                        "count": 0.0,
                        "total_ms": 0.0,
                        "min_ms": elapsed_ms,
                        "max_ms": 0.0,
                    },
                )
                stats["count"] += 1.0
                stats["total_ms"] += elapsed_ms
                stats["min_ms"] = min(stats["min_ms"], elapsed_ms)
                stats["max_ms"] = max(stats["max_ms"], elapsed_ms)

            extra = " ".join(f"{key}={value}" for key, value in metadata.items())
            self._logger.info(
                "TIMING stage=%s opportunity_id=%s elapsed_ms=%.2f%s%s",
                stage,
                opportunity_id or "-",
                elapsed_ms,
                " " if extra else "",
                extra,
            )

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            out: Dict[str, Any] = {}
            for stage, stats in self._stats.items():
                count = int(stats["count"])
                total_ms = stats["total_ms"]
                out[stage] = {
                    "count": count,
                    "total_ms": round(total_ms, 2),
                    "avg_ms": round(total_ms / count, 2) if count else 0.0,
                    "min_ms": round(stats["min_ms"], 2),
                    "max_ms": round(stats["max_ms"], 2),
                }
            return out


class SignalForgeGraph:
    """Executable LangGraph workflow for the full SignalForge pipeline."""

    def __init__(
        self,
        scanner_agent: OpportunityScannerAgent,
        intent_agent: IntentAgent,
        scoring_agent: OpportunityScoringAgent,
        product_knowledge_agent: ProductKnowledgeAgent,
        drafting_agent: DraftingAgent,
        compliance_agent: ComplianceAgent,
        *,
        limit_per_keyword: int = 25,
        subreddit: Optional[str] = None,
        time_filter: str = "week",
        progress_callback: Optional[Any] = None,
        max_workers: int = 1,
    ) -> None:
        self._scanner_agent = scanner_agent
        self._intent_agent = intent_agent
        self._scoring_agent = scoring_agent
        self._product_knowledge_agent = product_knowledge_agent
        self._drafting_agent = drafting_agent
        self._compliance_agent = compliance_agent
        self._limit_per_keyword = limit_per_keyword
        self._subreddit = subreddit
        self._time_filter = time_filter
        self._progress_callback = progress_callback
        self._max_workers = max(1, int(max_workers))
        self._max_total_scan_items = self._load_total_scan_cap()

        builder = StateGraph(
            SignalForgeState,
            input_schema=SignalForgeInputState,
            output_schema=SignalForgeState,
        )
        builder.add_node("scanner", self.scanner_node)
        builder.add_node("intent", self.intent_node)
        builder.add_node("scoring", self.scoring_node)
        builder.add_node("product_knowledge", self.knowledge_node)
        builder.add_node("drafting", self.drafting_node)
        builder.add_node("compliance", self.compliance_node)

        builder.add_edge(START, "scanner")
        builder.add_edge("scanner", "intent")
        builder.add_edge("intent", "scoring")
        builder.add_edge("scoring", "product_knowledge")
        builder.add_edge("product_knowledge", "drafting")
        builder.add_edge("drafting", "compliance")
        builder.add_edge("compliance", END)

        self.graph = builder.compile()
        self.graph.name = "SignalForgeGraph"
        logger.info("SignalForgeGraph compiled")

    def initial_state(self, query: str) -> SignalForgeState:
        """Construct a strongly typed initial state for graph invocation."""
        return {
            "query": query,
            "opportunities": [],
            "intent_results": [],
            "scored_results": [],
            "knowledge_results": [],
            "draft_results": [],
            "compliance_results": [],
            "final_results": [],
            "errors": [],
            "success_count": 0,
            "failure_count": 0,
            "timings": {},
        }

    def invoke(self, query: str) -> SignalForgeState:
        """Run the full graph and return the completed pipeline state."""
        state = self.initial_state(query)
        return self.graph.invoke(state)

    def run(self, query: str) -> List[FinalResult]:
        """Run the full graph and return only the final structured results."""
        return self.invoke(query)["final_results"]

    def run_progressive(self, query: str) -> SignalForgeState:
        """Run an item-level progressive pipeline with concurrent safe stages."""
        logger.info("progressive pipeline start")
        logger.info(
            "Concurrent execution plan: scanners=[reddit, quora, medium], "
            "item_workers=%d, item_ops=sequential, "
            "knowledge=serialized",
            self._max_workers,
        )

        state = self.initial_state(query)
        profiler = PipelineProfiler(logger)
        errors: List[PipelineError] = []
        discovered: List[OpportunityPayload] = []
        final_results: List[FinalResult] = []
        seen_keys: set[str] = set()
        futures = []
        knowledge_lock = threading.Lock()
        item_counter = 0

        logger.info(
            "Progressive pipeline using max_workers=%d (sequential=%s) total_scan_cap=%d",
            self._max_workers,
            self._max_workers <= 1,
            self._max_total_scan_items,
        )

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            for batch in self._scan_batches(query, profiler):
                platform = str(batch.get("platform", "unknown"))
                batch_error = batch.get("error")
                if batch_error:
                    errors.append({
                        "stage": f"{platform}_scanner",
                        "opportunity_id": None,
                        "error": str(batch_error),
                    })

                batch_results = list(batch.get("results", []) or [])
                for opportunity in self._dedupe_stream_batch(batch_results, seen_keys):
                    if item_counter >= self._max_total_scan_items:
                        logger.info(
                            "Early scan cap reached: platform=all cap=%d collected=%d",
                            self._max_total_scan_items,
                            item_counter,
                        )
                        continue
                    item_counter += 1
                    discovered_opportunity = {
                        **opportunity,
                        "pipeline_state": "discovered",
                    }
                    discovered.append(discovered_opportunity)
                    logger.info(
                        "Processing item %d/%d - platform=%s id=%s",
                        item_counter,
                        self._max_total_scan_items,
                        platform,
                        opportunity.get("id", "unknown"),
                    )
                    self._emit_opportunity_state(
                        "discovered",
                        opportunity=discovered_opportunity,
                        platform=platform,
                        timings=profiler.summary(),
                    )
                    futures.append(
                        pool.submit(
                            self._process_opportunity_progressive,
                            discovered_opportunity,
                            knowledge_lock,
                            profiler,
                        )
                    )

            for future in as_completed(futures):
                try:
                    item_result = future.result()
                except Exception as exc:
                    logger.exception("progressive item worker failed")
                    errors.append(self._build_error("progressive_worker", None, exc))
                    continue

                errors.extend(item_result.get("errors", []))
                final_result = item_result.get("final_result")
                if final_result:
                    final_results.append(final_result)

        actionable_results = [
            item for item in final_results
            if item.get("review_state") in {"paused", "dropped"}
        ]
        opportunities = list(actionable_results)
        intent_results = [
            {
                "intent": item.get("intent", ""),
                "confidence": item.get("confidence", 0) / 100
                if isinstance(item.get("confidence", 0), (int, float))
                else 0,
            }
            for item in actionable_results
        ]
        scored_results = [
            {
                "priority_score": item.get("score", 0),
                "priority_label": item.get("priority_label", ""),
            }
            for item in actionable_results
        ]
        knowledge_results = [
            {"summary": item.get("summary", "")}
            for item in actionable_results
        ]
        draft_results = [
            {
                "draft": item.get("draft", ""),
                "tone": item.get("tone", ""),
                "cta": item.get("cta", ""),
                "reasoning": item.get("reasoning", ""),
            }
            for item in actionable_results
        ]
        compliance_results = [
            {
                "approved": item.get("compliance_approved", False),
                "risk_level": item.get("risk_level", ""),
                "violations": item.get("violations", []),
                "recommendation": item.get("recommendation", ""),
            }
            for item in actionable_results
        ]
        success_count = sum(
            1 for item in compliance_results if item.get("approved") is True
        )
        failure_count = sum(
            1
            for item in compliance_results
            if item.get("approved") is False and item.get("violations")
        )

        state.update({
            "opportunities": opportunities,
            "intent_results": intent_results,
            "scored_results": scored_results,
            "knowledge_results": knowledge_results,
            "draft_results": draft_results,
            "compliance_results": compliance_results,
            "final_results": actionable_results,
            "errors": errors,
            "success_count": success_count,
            "failure_count": failure_count,
            "timings": profiler.summary(),
        })
        self._emit_progress(
            "complete",
            len(opportunities),
            {
                "event": "pipeline_complete",
                "discovered_count": len(discovered),
                "processed_count": len(actionable_results),
                "approved_count": success_count,
                "failure_count": failure_count,
                "timings": state["timings"],
            },
        )
        logger.info(
            "progressive pipeline end - discovered=%d processed=%d approved=%d failed=%d",
            len(discovered),
            len(actionable_results),
            success_count,
            failure_count,
        )
        return state

    def _scan_batches(
        self,
        query: str,
        profiler: PipelineProfiler,
    ) -> Iterator[Dict[str, Any]]:
        keywords = [query] if query.strip() else None
        scan_kwargs = {
            "keywords": keywords,
            "limit_per_keyword": self._limit_per_keyword,
            "subreddit": self._subreddit,
            "time_filter": self._time_filter,
        }

        if hasattr(self._scanner_agent, "scan_platform_batches"):
            with profiler.measure("scanner_total"):
                for batch in self._scanner_agent.scan_platform_batches(**scan_kwargs):
                    platform = str(batch.get("platform", "unknown"))
                    results = list(batch.get("results", []) or [])
                    elapsed_ms = batch.get("elapsed_ms")
                    payload = {
                        "event": "platform_batch",
                        "platform": platform,
                        "count": len(results),
                        "items": results[:5],
                        "elapsed_ms": elapsed_ms,
                    }
                    if batch.get("error"):
                        payload["error"] = batch["error"]
                    self._emit_progress(
                        f"{platform}_partial",
                        len(results),
                        payload,
                    )
                    yield batch
            return

        try:
            signature = inspect.signature(self._scanner_agent.scan)
            if "progress_callback" in signature.parameters:
                scan_kwargs["progress_callback"] = self._progress_callback
        except (TypeError, ValueError):
            pass

        with profiler.measure("scanner_total"):
            try:
                results = self._scanner_agent.scan(**scan_kwargs)
                yield {"platform": "all", "results": results}
            except Exception as exc:
                logger.exception("scanner phase failed")
                yield {"platform": "all", "results": [], "error": str(exc)}

    def _process_opportunity_progressive(
        self,
        opportunity: OpportunityPayload,
        knowledge_lock: threading.Lock,
        profiler: PipelineProfiler,
    ) -> Dict[str, Any]:
        errors: List[PipelineError] = []
        opportunity_id = str(opportunity.get("id", "unknown"))

        try:
            with profiler.measure("intent", opportunity_id):
                intent = self._intent_agent.classify(opportunity)
        except Exception as exc:
            logger.exception("intent phase failed for [%s]", opportunity_id)
            errors.append(self._build_error("intent", opportunity.get("id"), exc))
            intent = self._intent_fallback(str(exc))

        if intent.get("intent") == "ignore":
            self._emit_opportunity_state(
                "dropped",
                opportunity=opportunity,
                intent=intent,
                timings=profiler.summary(),
            )
            return {"final_result": None, "errors": errors}

        scoring_input = {**opportunity, **intent}
        try:
            with profiler.measure("scoring", opportunity_id):
                score = self._scoring_agent.score(scoring_input)
        except Exception as exc:
            logger.exception("scoring phase failed for [%s]", opportunity_id)
            errors.append(self._build_error("scoring", opportunity.get("id"), exc))
            score = self._scoring_fallback()

        self._emit_opportunity_state(
            "classified",
            opportunity=opportunity,
            intent=intent,
            score=score,
            timings=profiler.summary(),
        )

        ranked_opportunity = {
            **opportunity,
            **intent,
            **score,
            "_scoring": score,
        }
        try:
            with knowledge_lock:
                with profiler.measure("product_knowledge", opportunity_id):
                    knowledge = self._product_knowledge_agent.get_context(ranked_opportunity)
        except Exception as exc:
            logger.exception("product_knowledge phase failed for [%s]", opportunity_id)
            errors.append(
                self._build_error("product_knowledge", opportunity.get("id"), exc)
            )
            knowledge = self._knowledge_fallback(str(exc))

        draft_input = {
            "opportunity": opportunity,
            "intent_data": intent,
            "score_data": score,
            "knowledge_context": knowledge,
        }
        try:
            with profiler.measure("drafting", opportunity_id):
                draft = self._drafting_agent.generate_draft(draft_input)
        except Exception as exc:
            logger.exception("drafting phase failed for [%s]", opportunity_id)
            errors.append(self._build_error("drafting", opportunity.get("id"), exc))
            draft = self._draft_fallback(str(exc))

        self._emit_opportunity_state(
            "drafted",
            opportunity=opportunity,
            intent=intent,
            score=score,
            knowledge=knowledge,
            draft=draft,
            timings=profiler.summary(),
        )

        try:
            with profiler.measure("compliance", opportunity_id):
                compliance = self._compliance_agent.validate(draft)
        except Exception as exc:
            logger.exception("compliance phase failed for [%s]", opportunity_id)
            errors.append(self._build_error("compliance", opportunity.get("id"), exc))
            compliance = self._compliance_fallback(str(exc))

        approved = compliance.get("approved", False)
        pipeline_state = "approved" if approved else "drafted"
        review_state = "paused" if approved else "dropped"
        final_result: FinalResult = serialize_opportunity({
            **opportunity,
            "intent": intent,
            "score": score,
            "knowledge": knowledge,
            "draft": draft,
            "compliance": compliance,
            "review_state": review_state,
            "pipeline_state": pipeline_state,
            "status": pipeline_state,
        }, pipeline_state=pipeline_state, can_mutate=False)
        self._emit_opportunity_state(
            pipeline_state,
            opportunity=final_result,
            intent=intent,
            score=score,
            knowledge=knowledge,
            draft=draft,
            compliance=compliance,
            review_state=review_state,
            timings=profiler.summary(),
        )
        return {"final_result": final_result, "errors": errors}

    def _emit_opportunity_state(
        self,
        pipeline_state: str,
        *,
        opportunity: OpportunityPayload,
        platform: Optional[str] = None,
        intent: Optional[IntentPayload] = None,
        score: Optional[ScorePayload] = None,
        knowledge: Optional[KnowledgePayload] = None,
        draft: Optional[DraftPayload] = None,
        compliance: Optional[CompliancePayload] = None,
        review_state: Optional[str] = None,
        timings: Optional[Dict[str, Any]] = None,
    ) -> None:
        source: Dict[str, Any] = {
            **opportunity,
            "pipeline_state": pipeline_state,
            "status": pipeline_state,
        }
        if platform is not None:
            source["platform"] = platform
        if intent is not None:
            source["intent"] = intent
        if score is not None:
            source["score"] = score
        if knowledge is not None:
            source["knowledge"] = knowledge
        if draft is not None:
            source["draft"] = draft
        if compliance is not None:
            source["compliance"] = compliance
        if review_state is not None:
            source["review_state"] = review_state
        payload: Dict[str, Any] = {
            "event": "opportunity_state",
            **serialize_opportunity(
                source,
                pipeline_state=pipeline_state,
                can_mutate=False,
            ),
        }
        if timings is not None:
            payload["timings"] = timings
        self._emit_progress(pipeline_state, 0, payload)

    def _emit_progress(
        self,
        stage: str,
        items_found: int,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._progress_callback is None:
            return
        try:
            self._progress_callback(stage, items_found, payload)
        except TypeError:
            self._progress_callback(stage, items_found)

    @staticmethod
    def _dedupe_stream_batch(
        opportunities: List[OpportunityPayload],
        seen_keys: set[str],
    ) -> Iterator[OpportunityPayload]:
        for opportunity in opportunities:
            keys = SignalForgeGraph._stream_dedupe_keys(opportunity)
            if keys and any(key in seen_keys for key in keys):
                logger.info(
                    "DEDUP SKIP: platform=%s stage=progressive id=%s url=%s reason=duplicate_stream_key",
                    opportunity.get("platform", "-"),
                    opportunity.get("id", "-"),
                    opportunity.get("url", "-"),
                )
                continue
            seen_keys.update(keys)
            yield dict(opportunity)

    @staticmethod
    def _stream_dedupe_keys(opportunity: OpportunityPayload) -> set[str]:
        platform = str(opportunity.get("platform", "unknown")).strip().lower()
        post_id = str(opportunity.get("id", "")).strip()
        url = str(opportunity.get("url", "")).strip().lower()
        keys: set[str] = set()
        if post_id:
            keys.add(f"id:{platform}:{post_id}")
        if url:
            keys.add(f"url:{url}")
        return keys

    @staticmethod
    def _load_total_scan_cap() -> int:
        try:
            from config.settings import Settings

            return max(0, int(Settings().max_total_scan_items))
        except Exception:
            return 10

    def _cap_scan_items(
        self,
        opportunities: List[OpportunityPayload],
    ) -> List[OpportunityPayload]:
        if len(opportunities) <= self._max_total_scan_items:
            return opportunities
        logger.info(
            "Early scan cap reached: platform=all cap=%d collected=%d",
            self._max_total_scan_items,
            self._max_total_scan_items,
        )
        return opportunities[:self._max_total_scan_items]

    def scanner_node(self, state: SignalForgeState) -> Dict[str, Any]:
        logger.info("scanner phase start")
        errors = list(state.get("errors", []))

        try:
            keywords = [state["query"]] if state["query"].strip() else None
            scan_kwargs = {
                "keywords": keywords,
                "limit_per_keyword": self._limit_per_keyword,
                "subreddit": self._subreddit,
                "time_filter": self._time_filter,
            }
            try:
                signature = inspect.signature(self._scanner_agent.scan)
                if "progress_callback" in signature.parameters:
                    scan_kwargs["progress_callback"] = self._progress_callback
            except (TypeError, ValueError):
                pass
            opportunities = self._scanner_agent.scan(**scan_kwargs)
            opportunities = self._cap_scan_items(opportunities)
        except Exception as exc:
            logger.exception("scanner phase failed")
            errors.append(self._build_error("scanner", None, exc))
            opportunities = []

        logger.info("scanner phase end - %d opportunities", len(opportunities))
        return {
            "opportunities": opportunities,
            "intent_results": [],
            "scored_results": [],
            "knowledge_results": [],
            "draft_results": [],
            "compliance_results": [],
            "final_results": [],
            "errors": errors,
        }

    def intent_node(self, state: SignalForgeState) -> Dict[str, Any]:
        logger.info("intent phase start")
        errors = list(state.get("errors", []))
        results: List[IntentPayload] = []

        def process_opportunity(opportunity: Dict[str, Any]) -> Tuple[IntentPayload, Optional[PipelineError]]:
            try:
                res = self._intent_agent.classify(opportunity)
                return res, None
            except Exception as exc:
                logger.exception(
                    "intent phase failed for [%s]",
                    opportunity.get("id", "unknown"),
                )
                err = self._build_error("intent", opportunity.get("id"), exc)
                return self._intent_fallback(str(exc)), err

        with ThreadPoolExecutor(max_workers=1) as pool:
            mapped = pool.map(process_opportunity, state["opportunities"])

        for res, err in mapped:
            results.append(res)
            if err:
                errors.append(err)

        filtered_opportunities = []
        filtered_results = []
        filtered_count = 0
        for opp, res in zip(state["opportunities"], results):
            if res.get("intent") == "ignore":
                filtered_count += 1
            else:
                filtered_opportunities.append(opp)
                filtered_results.append(res)

        if filtered_count > 0:
            logger.info("Filtered out %d items with ignore intent", filtered_count)

        logger.info("intent phase end - %d results", len(filtered_results))
        return {
            "opportunities": filtered_opportunities,
            "intent_results": filtered_results,
            "errors": errors
        }

    def scoring_node(self, state: SignalForgeState) -> Dict[str, Any]:
        logger.info("scoring phase start")
        errors = list(state.get("errors", []))
        results: List[ScorePayload] = []

        for opportunity, intent in zip(state["opportunities"], state["intent_results"]):
            scoring_input = {**opportunity, **intent}
            try:
                result = self._scoring_agent.score(scoring_input)
            except Exception as exc:
                logger.exception(
                    "scoring phase failed for [%s]",
                    opportunity.get("id", "unknown"),
                )
                errors.append(self._build_error("scoring", opportunity.get("id"), exc))
                result = self._scoring_fallback()
            results.append(result)

        logger.info("scoring phase end - %d results", len(results))
        return {"scored_results": results, "errors": errors}

    def knowledge_node(self, state: SignalForgeState) -> Dict[str, Any]:
        logger.info("product_knowledge phase start")
        errors = list(state.get("errors", []))
        results: List[KnowledgePayload] = []

        for opportunity, intent, score in zip(
            state["opportunities"],
            state["intent_results"],
            state["scored_results"],
        ):
            ranked_opportunity = {
                **opportunity,
                **intent,
                **score,
                "_scoring": score,
            }
            try:
                result = self._product_knowledge_agent.get_context(ranked_opportunity)
            except Exception as exc:
                logger.exception(
                    "product_knowledge phase failed for [%s]",
                    opportunity.get("id", "unknown"),
                )
                errors.append(
                    self._build_error("product_knowledge", opportunity.get("id"), exc)
                )
                result = self._knowledge_fallback(str(exc))
            results.append(result)

        logger.info("product_knowledge phase end - %d results", len(results))
        return {"knowledge_results": results, "errors": errors}

    def drafting_node(self, state: SignalForgeState) -> Dict[str, Any]:
        logger.info("drafting phase start")
        errors = list(state.get("errors", []))
        results: List[DraftPayload] = []

        def process_draft(item: Tuple[Any, Any, Any, Any]) -> Tuple[DraftPayload, Optional[PipelineError]]:
            opp, intnt, scr, know = item
            draft_in = {
                "opportunity": opp,
                "intent_data": intnt,
                "score_data": scr,
                "knowledge_context": know,
            }
            try:
                res = self._drafting_agent.generate_draft(draft_in)
                return res, None
            except Exception as exc:
                logger.exception(
                    "drafting phase failed for [%s]",
                    opp.get("id", "unknown"),
                )
                err = self._build_error("drafting", opp.get("id"), exc)
                return self._draft_fallback(str(exc)), err

        items = zip(
            state["opportunities"],
            state["intent_results"],
            state["scored_results"],
            state["knowledge_results"],
        )

        with ThreadPoolExecutor(max_workers=1) as pool:
            mapped = pool.map(process_draft, items)

        for res, err in mapped:
            results.append(res)
            if err:
                errors.append(err)

        logger.info("drafting phase end - %d results", len(results))
        return {"draft_results": results, "errors": errors}

    def compliance_node(self, state: SignalForgeState) -> Dict[str, Any]:
        logger.info("compliance phase start")
        errors = list(state.get("errors", []))
        compliance_results: List[CompliancePayload] = []
        final_results: List[FinalResult] = []

        for opportunity, intent, score, knowledge, draft in zip(
            state["opportunities"],
            state["intent_results"],
            state["scored_results"],
            state["knowledge_results"],
            state["draft_results"],
        ):
            try:
                compliance = self._compliance_agent.validate(draft)
            except Exception as exc:
                logger.exception(
                    "compliance phase failed for [%s]",
                    opportunity.get("id", "unknown"),
                )
                errors.append(
                    self._build_error("compliance", opportunity.get("id"), exc)
                )
                compliance = self._compliance_fallback(str(exc))

            compliance_results.append(compliance)

            # -- Phase 12: tag review_state for pause/resume pattern ----
            if compliance.get("approved", False):
                review_state = "paused"  # requires human review
            else:
                review_state = "dropped"  # compliance rejected

            pipeline_state = "approved" if review_state == "paused" else "drafted"
            final_results.append(serialize_opportunity({
                **opportunity,
                "intent": intent,
                "score": score,
                "knowledge": knowledge,
                "draft": draft,
                "compliance": compliance,
                "review_state": review_state,
                "pipeline_state": pipeline_state,
                "status": pipeline_state,
            }, pipeline_state=pipeline_state, can_mutate=False))

        success_count = sum(
            1 for item in compliance_results if item.get("approved") is True
        )
        failure_count = sum(
            1
            for item in compliance_results
            if item.get("approved") is False and item.get("violations")
        )

        logger.info(
            "compliance phase end - %d final results, "
            "%d compliance successes, %d compliance failures",
            len(final_results),
            success_count,
            failure_count,
        )
        return {
            "compliance_results": compliance_results,
            "final_results": final_results,
            "errors": errors,
            "success_count": success_count,
            "failure_count": failure_count,
        }

    @staticmethod
    def _build_error(
        stage: str,
        opportunity_id: Optional[str],
        exc: Exception,
    ) -> PipelineError:
        return {
            "stage": stage,
            "opportunity_id": opportunity_id,
            "error": str(exc),
        }

    @staticmethod
    def _intent_fallback(reason: str) -> IntentPayload:
        return {
            "intent": "ignore",
            "confidence": 0.0,
            "reasoning": f"Intent fallback used because classification failed: {reason}",
            "business_relevance": "none",
            "recommended_action": "skip",
        }

    @staticmethod
    def _scoring_fallback() -> ScorePayload:
        return {
            "priority_score": 0.0,
            "priority_label": "ignore",
            "scoring_breakdown": {
                "intent_score": 0.0,
                "engagement_score": 0.0,
                "signal_boost": 0.0,
                "urgency_boost": 0.0,
            },
            "recommended_action": "skip",
        }

    @staticmethod
    def _knowledge_fallback(reason: str) -> KnowledgePayload:
        return {
            "relevant_context": [],
            "summary": f"No product knowledge available because retrieval failed: {reason}",
            "sources": [],
        }

    @staticmethod
    def _draft_fallback(reason: str) -> DraftPayload:
        return {
            "draft": (
                "A practical next step is to narrow the problem into a few clear "
                "workflow steps and focus on the conversations that actually need "
                "a thoughtful reply."
            ),
            "tone": "helpful",
            "cta": "",
            "reasoning": f"Draft fallback used because generation failed: {reason}",
        }

    @staticmethod
    def _compliance_fallback(reason: str) -> CompliancePayload:
        return {
            "approved": False,
            "risk_level": "reject",
            "violations": ["compliance_failure"],
            "safe_draft": (
                "A safer version would focus on the user's problem first and keep "
                "any product mention brief, optional, and non-promotional."
            ),
            "recommendation": (
                "Reject the original draft and re-run compliance because validation "
                f"failed: {reason}"
            ),
        }

    # ------------------------------------------------------------------
    # Phase 12: Pause / Resume helpers
    # ------------------------------------------------------------------

    @staticmethod
    def resume_reviewed_items(
        final_results: List[FinalResult],
        review_queue: Any,
    ) -> Tuple[List[FinalResult], List[FinalResult]]:
        """Split final results into resumed and dropped based on queue state.

        Reads the current review status from the ``ReviewQueue`` for each
        item.  Items that were approved or edited are *resumed*; items that
        were rejected are *dropped*.  Items still pending remain paused
        (included in neither list).

        Parameters
        ----------
        final_results:
            The ``final_results`` list from a completed pipeline run.
        review_queue:
            A ``ReviewQueue`` instance whose items hold the canonical
            review decisions.

        Returns
        -------
        (resumed, dropped)
            Two lists of ``FinalResult`` dicts.
        """
        queue_items = {item["review_id"]: item for item in review_queue.items}
        resumed: List[FinalResult] = []
        dropped: List[FinalResult] = []

        for result in final_results:
            legacy_opp = result.get("opportunity", {})
            opp_id = (
                result.get("opportunity_id")
                or result.get("id")
                or (legacy_opp.get("id", "") if isinstance(legacy_opp, dict) else "")
            )
            # Try matching by review-<opp_id> convention or direct id
            record = (
                queue_items.get(f"review-{opp_id}")
                or queue_items.get(opp_id)
                or queue_items.get(str(result.get("review_id", "")))
            )
            if record is None:
                continue  # not in queue -- skip

            status = record.get("review_status", "pending")
            if status in ("approved", "edited"):
                updated = {**result, "review_state": "resumed"}
                if status == "edited" and record.get("final_draft"):
                    updated["draft"] = record["final_draft"]
                    updated["final_draft"] = record["final_draft"]
                resumed.append(updated)
            elif status == "rejected":
                dropped.append({**result, "review_state": "dropped"})
            # else: still pending -- leave paused

        return resumed, dropped


def build_signalforge_graph(
    scanner_agent: OpportunityScannerAgent,
    intent_agent: IntentAgent,
    scoring_agent: OpportunityScoringAgent,
    product_knowledge_agent: ProductKnowledgeAgent,
    drafting_agent: DraftingAgent,
    compliance_agent: ComplianceAgent,
    *,
    limit_per_keyword: int = 25,
    subreddit: Optional[str] = None,
    time_filter: str = "week",
    progress_callback: Optional[Any] = None,
    max_workers: int = 1,
) -> SignalForgeGraph:
    """Factory helper for creating the executable SignalForge graph."""
    return SignalForgeGraph(
        scanner_agent=scanner_agent,
        intent_agent=intent_agent,
        scoring_agent=scoring_agent,
        product_knowledge_agent=product_knowledge_agent,
        drafting_agent=drafting_agent,
        compliance_agent=compliance_agent,
        limit_per_keyword=limit_per_keyword,
        subreddit=subreddit,
        time_filter=time_filter,
        progress_callback=progress_callback,
        max_workers=max_workers,
    )


__all__ = [
    "SignalForgeInputState",
    "SignalForgeState",
    "FinalResult",
    "SignalForgeGraph",
    "build_signalforge_graph",
]
