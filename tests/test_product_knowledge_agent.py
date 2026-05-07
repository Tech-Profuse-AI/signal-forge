#!/usr/bin/env python3
"""
Phase 5 Tests -- ProductKnowledgeAgent and Vector Store.

Tests the local RAG pipeline using the product knowledge markdown docs.
No external APIs are required because the vector store falls back to a
deterministic local embedding implementation when Gemini is unavailable.

Run:
    cd SignalForge
    python -m tests.test_product_knowledge_agent
"""

import logging
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("test_phase5")

from agents.product_knowledge_agent import ProductKnowledgeAgent
from providers.vector_store import LocalChromaVectorStore


PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge" / "product_docs"
TMP_ROOT = PROJECT_ROOT / "tests" / ".tmp_phase5"

TEST_QUERIES = [
    "Need help automating Reddit lead discovery",
    "Looking for social media workflow automation",
    "Need AI-based community engagement workflow",
]


def _build_store(persist_directory: str) -> LocalChromaVectorStore:
    return LocalChromaVectorStore(
        documents_path=str(KNOWLEDGE_DIR),
        persist_directory=persist_directory,
        chunk_size=320,
        chunk_overlap=60,
        gemini_api_key="",
    )


@contextmanager
def _persist_dir():
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = TMP_ROOT / f"run_{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield str(temp_dir)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _print_context_block(context_payload):
    print("\n  Retrieved Chunks:")
    print("  " + "-" * 72)
    for index, item in enumerate(context_payload["relevant_context"], 1):
        preview = item["content"][:180].replace("\n", " ")
        print(f"  #{index} [{item['source']}] {preview}")
    print("  " + "-" * 72)
    print(f"  Summary: {context_payload['summary']}")
    print(f"  Sources: {context_payload['sources']}")


def test_ingestion():
    """Knowledge docs are chunked, embedded, persisted, and metadata is stored."""
    print("\n" + "=" * 60)
    print("  TEST: Product Knowledge Ingestion")
    print("=" * 60)

    with _persist_dir() as temp_dir:
        store = _build_store(temp_dir)
        stats = store.ingest_documents()

        assert stats["documents_loaded"] == 4, (
            f"Expected 4 docs, got {stats['documents_loaded']}"
        )
        assert stats["chunks_stored"] > stats["documents_loaded"], (
            "Expected chunking to create more chunks than source docs"
        )
        assert store.document_count == stats["chunks_stored"]
        print(f"  + Ingestion stats: {stats}")

        snapshot = store.collection.get(limit=1, include=["metadatas", "documents"])
        metadata = snapshot["metadatas"][0]
        assert "source" in metadata
        assert "chunk_index" in metadata
        assert "document_total_chunks" in metadata
        assert "document_name" in metadata
        print(f"  + Metadata sample: {metadata}")

        reopened_store = _build_store(temp_dir)
        assert reopened_store.document_count == store.document_count, (
            "Persistent Chroma store should keep chunks across instances"
        )
        print(f"  + Persistence verified: {reopened_store.document_count} chunks available")

        print("  -- Product Knowledge Ingestion PASSED --")


def test_retrieval():
    """Retrieval returns relevant context for the requested sample queries."""
    print("\n" + "=" * 60)
    print("  TEST: Product Knowledge Retrieval")
    print("=" * 60)

    expected_keywords = {
        TEST_QUERIES[0]: ("lead", "discovery", "buying", "reddit"),
        TEST_QUERIES[1]: ("workflow", "social media", "automation"),
        TEST_QUERIES[2]: ("community", "engagement", "workflow"),
    }
    valid_sources = {
        "product_overview.md",
        "features.md",
        "use_cases.md",
        "faqs.md",
    }

    with _persist_dir() as temp_dir:
        store = _build_store(temp_dir)
        store.ingest_documents()

        for query in TEST_QUERIES:
            results = store.retrieve_context(query, top_k=3)
            assert results, f"No context returned for query: {query}"
            assert len(results) <= 3

            sources = {Path(item["source"]).name for item in results}
            assert sources <= valid_sources, (
                f"Unexpected source names for query '{query}': {sources}"
            )
            joined_content = " ".join(item["content"].lower() for item in results)
            assert any(keyword in joined_content for keyword in expected_keywords[query]), (
                f"Retrieved chunks did not contain expected concepts for query '{query}'"
            )

            print(f"\n  Query: {query}")
            for index, item in enumerate(results, 1):
                preview = item["content"][:160]
                print(f"  #{index} [{item['source']}] {preview}")

        print("\n  -- Product Knowledge Retrieval PASSED --")


def test_source_tracking():
    """Agent output includes retrieved chunks, summary, and deduped sources."""
    print("\n" + "=" * 60)
    print("  TEST: ProductKnowledgeAgent Source Tracking")
    print("=" * 60)

    ranked_opportunity = {
        "id": "phase4_001",
        "title": "Need help automating Reddit lead discovery",
        "body": (
            "Our marketing team is manually searching Reddit for buying intent "
            "threads and needs a workflow that can scale community engagement."
        ),
        "subreddit": "marketing",
        "score": 91,
        "intent": "buying_intent",
        "opportunity_signals": ["help_request", "recommendation_request", "pain_point"],
        "_scoring": {
            "priority_score": 88.4,
            "priority_label": "hot",
            "recommended_action": "respond_immediately",
        },
    }

    with _persist_dir() as temp_dir:
        store = _build_store(temp_dir)
        agent = ProductKnowledgeAgent(vector_store=store, top_k=3)
        agent.ingest_documents()

        context_payload = agent.get_context(ranked_opportunity)

        assert "relevant_context" in context_payload
        assert "summary" in context_payload
        assert "sources" in context_payload
        assert context_payload["relevant_context"], "Expected retrieved context"
        assert context_payload["summary"], "Expected non-empty summary"
        assert context_payload["sources"], "Expected at least one tracked source"
        assert len(context_payload["sources"]) == len(set(context_payload["sources"]))

        for item in context_payload["relevant_context"]:
            assert item["source"] in context_payload["sources"]
            assert item["content"]

        _print_context_block(context_payload)
        print("  -- ProductKnowledgeAgent Source Tracking PASSED --")


if __name__ == "__main__":
    print("\n+" + "=" * 58 + "+")
    print("|   SignalForge -- Phase 5 ProductKnowledgeAgent Tests     |")
    print("+" + "=" * 58 + "+")

    try:
        test_ingestion()
        test_retrieval()
        test_source_tracking()

        print("\n" + "=" * 60)
        print("  ALL PHASE 5 TESTS PASSED")
        print("=" * 60 + "\n")

    except AssertionError as exc:
        print(f"\n  TEST FAILED: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  UNEXPECTED ERROR: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
