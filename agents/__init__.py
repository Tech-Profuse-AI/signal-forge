"""
SignalForge Agents Module.

Contains individual agents for the SignalForge pipeline:
  - Phase 2: OpportunityScannerAgent -- Reddit opportunity discovery
  - Phase 3: IntentAgent -- intent classification via LLM
  - Phase 4: OpportunityScoringAgent -- priority scoring
  - Future:  DraftGenerator, ComplianceChecker, etc.
"""

from agents.opportunity_scanner import (
    OpportunityScannerAgent,
    RedditScanner,
    CacheManager,
    OpportunityFilter,
)
from agents.intent_agent import IntentAgent
from agents.compliance_agent import ComplianceAgent
from agents.drafting_agent import DraftingAgent
from agents.product_knowledge_agent import ProductKnowledgeAgent
from agents.scoring_agent import OpportunityScoringAgent

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
