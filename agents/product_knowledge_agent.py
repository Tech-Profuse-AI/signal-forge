"""
SignalForge ProductKnowledgeAgent -- Phase 5.

Retrieves relevant product and business knowledge for a ranked opportunity
using the local vector store. The returned context is intended to ground a
future drafting phase without implementing drafting itself here.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from providers.vector_store import LocalChromaVectorStore

logger = logging.getLogger("signalforge.product_knowledge_agent")

_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "i", "in", "into", "is", "it", "its", "my", "need", "of", "on", "or",
    "our", "that", "the", "their", "this", "to", "us", "we", "with", "you",
    "your",
}


class ProductKnowledgeAgent:
    """
    Retrieves the most relevant product knowledge for a Phase 4 opportunity.
    """

    def __init__(
        self,
        vector_store: Optional[LocalChromaVectorStore] = None,
        top_k: int = 3,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be > 0")

        self._vector_store = vector_store or LocalChromaVectorStore()
        self._top_k = top_k
        logger.info(
            "ProductKnowledgeAgent initialised - top_k=%d, collection=%s",
            top_k,
            self._vector_store.collection_name,
        )

    def ingest_documents(self) -> Dict[str, Any]:
        """Convenience wrapper to build or rebuild the local knowledge index."""
        return self._vector_store.ingest_documents()

    def get_context(self, opportunity: Dict[str, Any]) -> Dict[str, Any]:
        """
        Retrieve product knowledge context for a ranked Phase 4 opportunity.

        Returns:
            {
                "relevant_context": [...],
                "summary": "...",
                "sources": [...],
            }
        """
        if not isinstance(opportunity, dict):
            raise TypeError(
                "opportunity must be a dict containing the ranked opportunity"
            )

        query = self._build_query(opportunity)
        relevant_context = self._vector_store.retrieve_context(
            query,
            top_k=self._top_k,
        )
        sources = list(dict.fromkeys(
            item["source"] for item in relevant_context if item.get("source")
        ))
        summary = self._build_summary(query, relevant_context)

        logger.info(
            "Retrieved product context for [%s] - %d chunks, %d sources",
            opportunity.get("id", "unknown"),
            len(relevant_context),
            len(sources),
        )
        return {
            "relevant_context": relevant_context,
            "summary": summary,
            "sources": sources,
        }

    def _build_query(self, opportunity: Dict[str, Any]) -> str:
        title = str(opportunity.get("title", "")).strip()
        body = str(opportunity.get("body", "")).strip()
        intent = str(opportunity.get("intent", "")).strip()
        subreddit = str(opportunity.get("subreddit", "")).strip()
        signals = opportunity.get("opportunity_signals", []) or []

        scoring = opportunity.get("_scoring", {})
        priority_label = str(
            opportunity.get("priority_label")
            or scoring.get("priority_label", "")
        ).strip()
        priority_score = (
            opportunity.get("priority_score")
            if "priority_score" in opportunity
            else scoring.get("priority_score")
        )

        parts: List[str] = []
        if title:
            parts.append(title)
        if body:
            parts.append(body)
        if intent:
            parts.append(f"Intent: {intent.replace('_', ' ')}")
        if subreddit:
            parts.append(f"Subreddit: r/{subreddit}")
        if signals:
            parts.append("Signals: " + ", ".join(str(item) for item in signals))
        if priority_label:
            parts.append(f"Priority label: {priority_label}")
        if priority_score is not None:
            parts.append(f"Priority score: {priority_score}")

        return "\n".join(parts).strip()

    def _build_summary(
        self,
        query: str,
        relevant_context: List[Dict[str, str]],
    ) -> str:
        if not relevant_context:
            return "No relevant product knowledge found for this opportunity."

        query_terms = self._meaningful_terms(query)
        candidates = []

        for rank, item in enumerate(relevant_context):
            for sentence_index, sentence in enumerate(
                self._split_sentences(item["content"])
            ):
                cleaned = sentence.strip()
                if len(cleaned) < 30:
                    continue

                lowered = cleaned.lower()
                overlap = sum(1 for term in query_terms if term in lowered)
                score = overlap + max(0, 3 - rank)
                candidates.append((score, rank, sentence_index, cleaned))

        candidates.sort(key=lambda item: (-item[0], item[1], item[2], len(item[3])))

        selected: List[str] = []
        for _, _, _, sentence in candidates:
            lowered = sentence.lower()
            if any(
                lowered == existing.lower()
                or lowered in existing.lower()
                or existing.lower() in lowered
                for existing in selected
            ):
                continue
            selected.append(sentence)
            if len(selected) == 3:
                break

        if not selected:
            selected.append(self._fallback_summary_sentence(relevant_context[0]["content"]))

        summary = " ".join(selected)
        if len(summary) > 700:
            return summary[:697].rstrip() + "..."
        return summary

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        normalised = re.sub(r"\s+", " ", text).strip()
        if not normalised:
            return []
        sentences = re.split(r"(?<=[.!?])\s+", normalised)
        return [sentence for sentence in sentences if sentence]

    @staticmethod
    def _fallback_summary_sentence(text: str) -> str:
        normalised = re.sub(r"\s+", " ", text).strip()
        if not normalised:
            return "Relevant product knowledge was retrieved but could not be summarised."
        if len(normalised) > 240:
            return normalised[:237].rstrip() + "..."
        return normalised

    @staticmethod
    def _meaningful_terms(text: str) -> List[str]:
        terms: List[str] = []
        for token in _TOKEN_PATTERN.findall(text.lower()):
            if len(token) <= 2 or token in _STOPWORDS:
                continue
            if token not in terms:
                terms.append(token)
        return terms

    def __repr__(self) -> str:
        return (
            f"<ProductKnowledgeAgent top_k={self._top_k} "
            f"collection='{self._vector_store.collection_name}'>"
        )

