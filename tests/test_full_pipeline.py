#!/usr/bin/env python3
"""
Phase 10 Tests -- Full Pipeline Integration.

Validates:
  1. Full pipeline execution returns the expected summary shape
  2. Output file creation at outputs/final_results.json
  3. Summary field validation (counts, types, keys)
  4. Review queue receives approved items
  5. CLI argument parsing

Run:
    cd SignalForge
    python -m tests.test_full_pipeline
"""

import json
import logging
import os
import shutil
import sys
from pathlib import Path

# -- Ensure project root on sys.path -----------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("test_phase10")


# ==================================================================
# Helpers
# ==================================================================

OUTPUTS_DIR = PROJECT_ROOT / "outputs"
RESULTS_FILE = OUTPUTS_DIR / "final_results.json"
REVIEW_QUEUE_FILE = OUTPUTS_DIR / ".review_queue.json"

# Backup paths in case outputs already exist
_BACKUP_RESULTS = OUTPUTS_DIR / "_backup_final_results.json"
_BACKUP_QUEUE = OUTPUTS_DIR / "_backup_review_queue.json"


def _backup_existing():
    """Move aside existing output files so the test runs clean."""
    if RESULTS_FILE.exists():
        RESULTS_FILE.rename(_BACKUP_RESULTS)
    if REVIEW_QUEUE_FILE.exists():
        REVIEW_QUEUE_FILE.rename(_BACKUP_QUEUE)


def _restore_existing():
    """Restore backed-up output files after the test."""
    if _BACKUP_RESULTS.exists():
        if RESULTS_FILE.exists():
            RESULTS_FILE.unlink()
        _BACKUP_RESULTS.rename(RESULTS_FILE)
    if _BACKUP_QUEUE.exists():
        if REVIEW_QUEUE_FILE.exists():
            REVIEW_QUEUE_FILE.unlink()
        _BACKUP_QUEUE.rename(REVIEW_QUEUE_FILE)


# ==================================================================
# Test 1 -- Full pipeline execution
# ==================================================================

def test_full_pipeline_execution():
    """The runner executes end-to-end and returns valid output."""
    print("\n" + "=" * 60)
    print("  TEST 1: Full pipeline execution")
    print("=" * 60)

    from run_signalforge import run_pipeline

    result = run_pipeline("AI automation workflow pain points")

    # Basic shape
    assert isinstance(result, dict), "run_pipeline must return a dict"
    assert "query" in result, "Result must contain 'query'"
    assert "summary" in result, "Result must contain 'summary'"
    assert "approved_items" in result, "Result must contain 'approved_items'"
    assert "rejected_items" in result, "Result must contain 'rejected_items'"
    assert "errors" in result, "Result must contain 'errors'"
    assert "timestamp" in result, "Result must contain 'timestamp'"
    assert "elapsed_seconds" in result, "Result must contain 'elapsed_seconds'"
    assert "review_queue_stats" in result, "Result must contain 'review_queue_stats'"

    assert result["query"] == "AI automation workflow pain points"
    assert result["elapsed_seconds"] >= 0

    print("  [OK] Pipeline returned valid output dict")
    print("  -- TEST 1 PASSED --")
    return result


# ==================================================================
# Test 2 -- Output file creation
# ==================================================================

def test_output_file_creation():
    """outputs/final_results.json is created and is valid JSON."""
    print("\n" + "=" * 60)
    print("  TEST 2: Output file creation")
    print("=" * 60)

    assert RESULTS_FILE.exists(), (
        f"Expected output file at {RESULTS_FILE}"
    )

    content = RESULTS_FILE.read_text(encoding="utf-8")
    data = json.loads(content)

    assert isinstance(data, dict), "Output JSON must be a dict"
    assert "summary" in data, "Output JSON must contain 'summary'"

    file_size = RESULTS_FILE.stat().st_size
    print(f"  [OK] Output file exists: {RESULTS_FILE}")
    print(f"  [OK] Valid JSON, size: {file_size:,} bytes")
    print("  -- TEST 2 PASSED --")
    return data


# ==================================================================
# Test 3 -- Summary validation
# ==================================================================

def test_summary_validation(result: dict):
    """The summary block has the exact required shape and valid counts."""
    print("\n" + "=" * 60)
    print("  TEST 3: Summary validation")
    print("=" * 60)

    summary = result["summary"]
    required_keys = {
        "total_opportunities",
        "processed",
        "approved",
        "review_queue",
        "failed",
    }

    missing = required_keys - set(summary.keys())
    assert not missing, f"Summary is missing keys: {missing}"

    for key in required_keys:
        assert isinstance(summary[key], int), (
            f"summary['{key}'] must be int, got {type(summary[key]).__name__}"
        )

    assert summary["total_opportunities"] >= 0
    assert summary["processed"] >= 0
    assert summary["approved"] >= 0
    assert summary["review_queue"] >= 0
    assert summary["failed"] >= 0

    # processed should equal total (every opportunity goes through all stages)
    assert summary["processed"] == summary["total_opportunities"], (
        f"processed ({summary['processed']}) should equal "
        f"total_opportunities ({summary['total_opportunities']})"
    )

    # approved + items not approved <= total
    assert summary["approved"] <= summary["total_opportunities"], (
        f"approved ({summary['approved']}) cannot exceed "
        f"total_opportunities ({summary['total_opportunities']})"
    )

    print(f"  [OK] Summary keys present: {sorted(required_keys)}")
    print(f"  [OK] total_opportunities = {summary['total_opportunities']}")
    print(f"  [OK] processed           = {summary['processed']}")
    print(f"  [OK] approved            = {summary['approved']}")
    print(f"  [OK] review_queue        = {summary['review_queue']}")
    print(f"  [OK] failed              = {summary['failed']}")
    print("  -- TEST 3 PASSED --")


# ==================================================================
# Test 4 -- Review queue integration
# ==================================================================

def test_review_queue_populated(result: dict):
    """Approved items are pushed to the review queue file."""
    print("\n" + "=" * 60)
    print("  TEST 4: Review queue populated")
    print("=" * 60)

    queue_stats = result.get("review_queue_stats", {})
    approved_count = result["summary"]["approved"]

    if approved_count > 0:
        assert REVIEW_QUEUE_FILE.exists(), (
            "Review queue file should exist when items are approved"
        )
        queue_data = json.loads(
            REVIEW_QUEUE_FILE.read_text(encoding="utf-8")
        )
        assert isinstance(queue_data.get("items"), list), (
            "Review queue must contain an 'items' list"
        )
        pending = queue_stats.get("pending", 0)
        assert pending >= approved_count, (
            f"Queue pending ({pending}) should be >= approved ({approved_count})"
        )
        print(f"  [OK] Review queue file exists")
        print(f"  [OK] {pending} pending item(s) in queue")
    else:
        print("  [OK] No approved items, queue correctly empty or unchanged")

    print(f"  [OK] Queue stats: {queue_stats}")
    print("  -- TEST 4 PASSED --")


# ==================================================================
# Test 5 -- Approved items have correct structure
# ==================================================================

def test_approved_items_structure(result: dict):
    """Each approved item contains all six pipeline stage keys."""
    print("\n" + "=" * 60)
    print("  TEST 5: Approved items structure")
    print("=" * 60)

    approved = result.get("approved_items", [])
    required_stage_keys = {
        "opportunity", "intent", "score", "knowledge", "draft", "compliance",
    }

    for i, item in enumerate(approved):
        missing = required_stage_keys - set(item.keys())
        assert not missing, (
            f"Approved item {i} is missing stage keys: {missing}"
        )
        assert item["compliance"].get("approved") is True, (
            f"Approved item {i} should have compliance.approved == True"
        )

    print(f"  [OK] {len(approved)} approved item(s) validated")
    print(f"  [OK] All items contain keys: {sorted(required_stage_keys)}")
    print("  -- TEST 5 PASSED --")


# ==================================================================
# Test 6 -- CLI argument parsing
# ==================================================================

def test_cli_argument_parsing():
    """The runner correctly parses positional and --query flag arguments."""
    print("\n" + "=" * 60)
    print("  TEST 6: CLI argument parsing")
    print("=" * 60)

    from run_signalforge import parse_args

    # Positional argument
    args = parse_args(["some query"])
    query = args.query_flag or args.query_positional
    assert query == "some query", f"Expected 'some query', got '{query}'"

    # Named --query flag
    args = parse_args(["--query", "another query"])
    query = args.query_flag or args.query_positional
    assert query == "another query", f"Expected 'another query', got '{query}'"

    # Named -q short flag
    args = parse_args(["-q", "short flag"])
    query = args.query_flag or args.query_positional
    assert query == "short flag", f"Expected 'short flag', got '{query}'"

    # --query takes priority over positional
    args = parse_args(["positional", "--query", "flagged"])
    query = args.query_flag or args.query_positional
    assert query == "flagged", f"--query flag should take priority, got '{query}'"

    print("  [OK] Positional argument parsed correctly")
    print("  [OK] --query flag parsed correctly")
    print("  [OK] -q short flag parsed correctly")
    print("  [OK] --query takes priority over positional")
    print("  -- TEST 6 PASSED --")


# ==================================================================
# Runner
# ==================================================================

if __name__ == "__main__":
    print("\n+" + "=" * 58 + "+")
    print("|   SignalForge -- Phase 10 Full Pipeline Tests             |")
    print("+" + "=" * 58 + "+")

    _backup_existing()

    try:
        # Test 6 first -- it's fast and doesn't need the pipeline
        test_cli_argument_parsing()

        # Test 1 -- run the pipeline (generates output for subsequent tests)
        result = test_full_pipeline_execution()

        # Test 2 -- verify output file
        test_output_file_creation()

        # Test 3 -- validate summary shape and counts
        test_summary_validation(result)

        # Test 4 -- review queue
        test_review_queue_populated(result)

        # Test 5 -- approved item structure
        test_approved_items_structure(result)

        print("\n" + "=" * 60)
        print("  ALL PHASE 10 TESTS PASSED  [OK]")
        print("=" * 60 + "\n")

    except AssertionError as exc:
        print(f"\n  TEST FAILED: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  UNEXPECTED ERROR: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        _restore_existing()
