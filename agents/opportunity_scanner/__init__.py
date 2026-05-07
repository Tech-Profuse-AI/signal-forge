"""
SignalForge Opportunity Scanner Agent Module.

Scans Reddit for high-value engagement opportunities — help requests,
recommendation threads, pain-point discussions, and workflow bottleneck
posts — using either live PRAW data or local mock JSON for testing.
"""

from agents.opportunity_scanner.agent import OpportunityScannerAgent
from agents.opportunity_scanner.reddit_scanner import RedditScanner
from agents.opportunity_scanner.cache_manager import CacheManager
from agents.opportunity_scanner.filters import OpportunityFilter

__all__ = [
    "OpportunityScannerAgent",
    "RedditScanner",
    "CacheManager",
    "OpportunityFilter",
]

__version__ = "2.0.0"
