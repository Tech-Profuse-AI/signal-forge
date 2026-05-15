"""SignalForge agents package."""

from __future__ import annotations

from typing import Any

__all__ = [
    "OpportunityScannerAgent",
    "RedditScanner",
    "CacheManager",
    "OpportunityFilter",
    "IntentAgent",
    "ComplianceAgent",
    "DraftingAgent",
    "ProductKnowledgeAgent",
    "OpportunityScoringAgent",
]


def __getattr__(name: str) -> Any:
    if name in {"OpportunityScannerAgent", "RedditScanner", "CacheManager", "OpportunityFilter"}:
        from agents import opportunity_scanner as scanner_pkg

        return getattr(scanner_pkg, name)
    if name == "IntentAgent":
        from agents.intent_agent import IntentAgent

        return IntentAgent
    if name == "ComplianceAgent":
        from agents.compliance_agent import ComplianceAgent

        return ComplianceAgent
    if name == "DraftingAgent":
        from agents.drafting_agent import DraftingAgent

        return DraftingAgent
    if name == "ProductKnowledgeAgent":
        from agents.product_knowledge_agent import ProductKnowledgeAgent

        return ProductKnowledgeAgent
    if name == "OpportunityScoringAgent":
        from agents.scoring_agent import OpportunityScoringAgent

        return OpportunityScoringAgent
    raise AttributeError(f"module 'agents' has no attribute {name!r}")

