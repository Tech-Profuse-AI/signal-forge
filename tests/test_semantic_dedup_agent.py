import pytest
from unittest.mock import MagicMock
from agents.semantic_dedup_agent import SemanticDedupAgent

@pytest.fixture
def dedup_agent():
    agent = SemanticDedupAgent()
    
    # Mocking _get_safe_embedding directly to isolate the test from VectorStore implementation
    def mock_embedding(text):
        if "exact" in text.lower() or "near" in text.lower():
            return [1.0, 0.0, 0.0]
        elif "cross" in text.lower():
            return [0.95, 0.1, 0.0]
        elif "fail" in text.lower():
            return []  # Simulate failure fallback
        else:
            return [0.0, 1.0, 0.0]

    agent._get_safe_embedding = MagicMock(side_effect=mock_embedding)
    return agent

def test_exact_duplicates(dedup_agent):
    opportunities = [
        {"id": "1", "platform": "reddit", "title": "Exact Title", "body": "Body text", "url": "url1", "score": 50},
        {"id": "2", "platform": "reddit", "title": "Exact Title", "body": "Body text", "url": "url2", "score": 30}
    ]
    res = dedup_agent.find_duplicates(opportunities)
    assert len(res["kept"]) == 1
    assert len(res["duplicates"]) == 1
    assert res["kept"][0]["id"] == "1"

def test_cross_platform_duplicates(dedup_agent):
    opportunities = [
        {"id": "1", "platform": "quora", "title": "Cross topic", "body": "some text", "url": "url1", "score": 20},
        {"id": "2", "platform": "medium", "title": "Cross topic", "body": "some text", "url": "url2", "score": 80}
    ]
    res = dedup_agent.find_duplicates(opportunities)
    assert len(res["kept"]) == 1
    assert res["kept"][0]["id"] == "2"
    assert res["kept"][0]["duplicate_sources"][0]["platform"] == "quora"

def test_embedding_failure_fallback(dedup_agent):
    opportunities = [
        {"id": "1", "platform": "reddit", "title": "Fail Title", "body": "Body text", "url": "url1", "score": 50},
        {"id": "2", "platform": "quora", "title": "Exact Title", "body": "Body text", "url": "url2", "score": 30}
    ]
    res = dedup_agent.find_duplicates(opportunities)
    # The first one fails embedding and is auto-kept. The second one has no other embeddings to match, so it's kept too.
    assert len(res["kept"]) == 2