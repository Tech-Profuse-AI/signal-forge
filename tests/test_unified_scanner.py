import pytest
from unittest.mock import MagicMock
from agents.unified_scanner import UnifiedScannerAgent

@pytest.fixture
def unified_scanner():
    scanner = UnifiedScannerAgent()
    # Mock underlying scanners to strictly use scan
    scanner.reddit_scanner.scan = MagicMock(return_value=[{"id": "r1", "platform": "reddit", "title": "Reddit Title", "body": "body", "url": "https://www.reddit.com/r/python/comments/abc123/example", "score": 10}])
    scanner.quora_scanner.scan = MagicMock(return_value=[{"id": "q1", "platform": "quora", "title": "Quora Title", "body": "body", "url": "https://www.quora.com/How-do-I-build-a-workflow", "score": 15}])
    scanner.medium_scanner.scan = MagicMock(return_value=[{"id": "m1", "platform": "medium", "title": "Medium Title", "body": "body", "url": "https://medium.com/@author/how-i-built-a-workflow-abc123", "score": 5}])
    
    # Mock dedup agent to just pass through during this test
    scanner.dedup_agent.deduplicate = MagicMock(side_effect=lambda x: x)
    return scanner

def test_single_query(unified_scanner):
    results = unified_scanner.scan("Test Query")
    assert len(results) == 3
    platforms = [r["platform"] for r in results]
    assert "reddit" in platforms and "quora" in platforms and "medium" in platforms

def test_multi_query_batch(unified_scanner):
    results = unified_scanner.scan(["Query 1", "Query 2"])
    # In this mock setup, calling scan returns the mocked list once per scanner
    assert len(results) == 3

def test_platform_failure_simulation(unified_scanner):
    unified_scanner.quora_scanner.scan.side_effect = Exception("API Timeout")
    results = unified_scanner.scan("Test Query")
    
    platforms = [r["platform"] for r in results]
    assert len(results) == 2
    assert "reddit" in platforms and "medium" in platforms
    assert "quora" not in platforms


def test_invalid_scanner_urls_are_filtered(unified_scanner):
    unified_scanner.reddit_scanner.scan = MagicMock(return_value=[
        {"id": "bad-reddit", "platform": "reddit", "title": "Subreddit", "body": "body", "url": "https://www.reddit.com/t5_gj6rto", "score": 10},
    ])
    unified_scanner.quora_scanner.scan = MagicMock(return_value=[
        {"id": "bad-quora", "platform": "quora", "title": "Profile", "body": "body", "url": "https://www.quora.com/profile/Jane-Doe", "score": 10},
    ])
    unified_scanner.medium_scanner.scan = MagicMock(return_value=[
        {"id": "bad-medium", "platform": "medium", "title": "Tag", "body": "body", "url": "https://medium.com/tag/automation", "score": 10},
    ])

    assert unified_scanner.scan("Test Query") == []
