"""
SignalForge LangGraph Orchestration -- Phase 8.

Connects the existing agents into a single executable workflow:

scanner -> intent -> scoring -> product_knowledge -> drafting -> compliance

This module does not rebuild any business logic. It only orchestrates the
existing agents and preserves structured metadata across all stages.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple, TypedDict

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
    opportunity: OpportunityPayload
    intent: IntentPayload
    score: ScorePayload
    knowledge: KnowledgePayload
    draft: DraftPayload
    compliance: CompliancePayload
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
        }

    def invoke(self, query: str) -> SignalForgeState:
        """Run the full graph and return the completed pipeline state."""
        state = self.initial_state(query)
        return self.graph.invoke(state)

    def run(self, query: str) -> List[FinalResult]:
        """Run the full graph and return only the final structured results."""
        return self.invoke(query)["final_results"]

    def scanner_node(self, state: SignalForgeState) -> Dict[str, Any]:
        logger.info("scanner phase start")
        errors = list(state.get("errors", []))

        try:
            keywords = [state["query"]] if state["query"].strip() else None
            opportunities = self._scanner_agent.scan(
                keywords=keywords,
                limit_per_keyword=self._limit_per_keyword,
                subreddit=self._subreddit,
                time_filter=self._time_filter,
            )
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

        with ThreadPoolExecutor(max_workers=4) as pool:
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

        with ThreadPoolExecutor(max_workers=4) as pool:
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

            final_results.append({
                "opportunity": opportunity,
                "intent": intent,
                "score": score,
                "knowledge": knowledge,
                "draft": draft,
                "compliance": compliance,
                "review_state": review_state,
            })

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
            opp_id = result.get("opportunity", {}).get("id", "")
            # Try matching by review-<opp_id> convention or direct id
            record = (
                queue_items.get(f"review-{opp_id}")
                or queue_items.get(opp_id)
            )
            if record is None:
                continue  # not in queue -- skip

            status = record.get("review_status", "pending")
            if status in ("approved", "edited"):
                updated = {**result, "review_state": "resumed"}
                if status == "edited" and record.get("final_draft"):
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
    )


__all__ = [
    "SignalForgeInputState",
    "SignalForgeState",
    "FinalResult",
    "SignalForgeGraph",
    "build_signalforge_graph",
]
