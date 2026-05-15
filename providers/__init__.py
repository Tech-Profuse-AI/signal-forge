"""SignalForge providers package."""

from __future__ import annotations

from typing import Any

__all__ = [
    "get_llm_provider",
    "BaseLLMProvider",
    "RedditProvider",
    "RedditPostProvider",
    "RedditRSSProvider",
    "QuoraPostProvider",
    "LocalChromaVectorStore",
    "ProductKnowledgeVectorStore",
]


def __getattr__(name: str) -> Any:
    if name in {"get_llm_provider", "BaseLLMProvider"}:
        from providers.llm_provider import BaseLLMProvider, get_llm_provider

        return {
            "get_llm_provider": get_llm_provider,
            "BaseLLMProvider": BaseLLMProvider,
        }[name]
    if name == "RedditProvider":
        from providers.reddit_provider import RedditProvider

        return RedditProvider
    if name == "RedditPostProvider":
        from providers.reddit_post_provider import RedditPostProvider

        return RedditPostProvider
    if name == "RedditRSSProvider":
        from providers.reddit_rss_provider import RedditRSSProvider

        return RedditRSSProvider
    if name == "QuoraPostProvider":
        from providers.quora_post_provider import QuoraPostProvider

        return QuoraPostProvider
    if name in {"LocalChromaVectorStore", "ProductKnowledgeVectorStore"}:
        from providers.vector_store import LocalChromaVectorStore, ProductKnowledgeVectorStore

        return {
            "LocalChromaVectorStore": LocalChromaVectorStore,
            "ProductKnowledgeVectorStore": ProductKnowledgeVectorStore,
        }[name]
    raise AttributeError(f"module 'providers' has no attribute {name!r}")

