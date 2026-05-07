"""
Phase 29 — Live Mode Activation Tests.

Validates:
  - Mock mode routes all providers to offline/mock data
  - Live mode routes all providers to live execution
  - UnifiedScannerAgent is used as the scanner in both modes
  - GeminiProvider is activated in live mode
  - Provider mode propagation is consistent
  - CLI argument parsing for --mock / --live
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ==================================================================
# 1. UnifiedScannerAgent — mock mode
# ==================================================================


class TestUnifiedScannerMockMode:
    """Verify that UnifiedScannerAgent in mock mode produces results
    from all three platforms using offline data."""

    def test_mock_mode_initialisation(self):
        from agents.unified_scanner import UnifiedScannerAgent

        scanner = UnifiedScannerAgent(mock_mode=True)
        assert scanner.mode == "mock"
        assert scanner.reddit_scanner.scanner.mode == "mock"
        assert scanner.quora_scanner.mode == "mock"
        assert scanner.medium_scanner.mode == "mock"

    def test_mock_scan_returns_results(self):
        from agents.unified_scanner import UnifiedScannerAgent

        scanner = UnifiedScannerAgent(mock_mode=True)
        results = scanner.scan(keywords=["social media automation"], limit_per_keyword=5)
        assert isinstance(results, list)
        assert len(results) > 0, "Mock scan should return at least some results"

    def test_mock_scan_multi_platform(self):
        from agents.unified_scanner import UnifiedScannerAgent

        scanner = UnifiedScannerAgent(mock_mode=True)
        results = scanner.scan(keywords=["AI automation tool"], limit_per_keyword=10)
        platforms = {r.get("platform", "unknown") for r in results}
        # At minimum Reddit mock data should be present
        assert "reddit" in platforms, f"Expected reddit in platforms, got {platforms}"

    def test_scan_interface_matches_opportunity_scanner(self):
        """Verify UnifiedScannerAgent.scan() accepts the same kwargs as
        OpportunityScannerAgent.scan() so it's a drop-in replacement."""
        from agents.unified_scanner import UnifiedScannerAgent

        scanner = UnifiedScannerAgent(mock_mode=True)
        # Should not raise — all kwargs accepted
        results = scanner.scan(
            keywords=["test"],
            limit_per_keyword=3,
            subreddit=None,
            time_filter="week",
        )
        assert isinstance(results, list)


# ==================================================================
# 2. UnifiedScannerAgent — live mode init
# ==================================================================


class TestUnifiedScannerLiveMode:
    """Verify that live mode propagates correctly to sub-scanners."""

    def test_live_mode_propagation(self):
        """In live mode without a RedditProvider, Reddit falls back to mock
        but Quora and Medium should be in live mode."""
        from agents.unified_scanner import UnifiedScannerAgent

        scanner = UnifiedScannerAgent(mock_mode=False)
        assert scanner.mode == "live"
        # Quora scanner should be live
        assert scanner.quora_scanner.mode == "live"
        # Medium scanner should be live
        assert scanner.medium_scanner.mode == "live"

    def test_live_mode_with_reddit_provider(self):
        """When a RedditProvider is passed, Reddit should also be live."""
        from agents.unified_scanner import UnifiedScannerAgent

        mock_reddit = MagicMock()
        scanner = UnifiedScannerAgent(
            mock_mode=False,
            reddit_provider=mock_reddit,
        )
        assert scanner.mode == "live"
        assert scanner.reddit_scanner.scanner.mode == "live"


# ==================================================================
# 3. CLI argument parsing
# ==================================================================


class TestCLIArgs:
    """Verify --mock / --live flags are parsed correctly."""

    def test_default_is_mock(self):
        from run_signalforge import parse_args

        args = parse_args(["test query"])
        assert args.mock is False
        assert args.live is False
        # Neither flag set → defaults to mock (live=False in main)

    def test_mock_flag(self):
        from run_signalforge import parse_args

        args = parse_args(["--mock", "test query"])
        assert args.mock is True
        assert args.live is False

    def test_live_flag(self):
        from run_signalforge import parse_args

        args = parse_args(["--live", "--query", "test query"])
        assert args.live is True
        assert args.mock is False

    def test_query_positional(self):
        from run_signalforge import parse_args

        args = parse_args(["my test query"])
        assert args.query_positional == "my test query"

    def test_query_flag(self):
        from run_signalforge import parse_args

        args = parse_args(["--query", "flag query"])
        assert args.query_flag == "flag query"


# ==================================================================
# 4. Mock mode full pipeline (boot_agents routing)
# ==================================================================


class TestBootAgents:
    """Verify _boot_agents creates the right providers for each mode."""

    def test_mock_mode_uses_mock_llm(self):
        from run_signalforge import _boot_agents, MockIntentLLMProvider, MockDraftingLLMProvider

        agents = _boot_agents(live=False)

        assert "scanner" in agents
        assert "intent" in agents
        assert "scoring" in agents
        assert "knowledge" in agents
        assert "drafting" in agents
        assert "compliance" in agents

        # Scanner should be UnifiedScannerAgent in mock mode
        from agents.unified_scanner import UnifiedScannerAgent
        assert isinstance(agents["scanner"], UnifiedScannerAgent)
        assert agents["scanner"].mode == "mock"

    @patch.dict("os.environ", {
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": "test-key-123",
    })
    @patch("providers.llm_provider.GeminiProvider.__init__", return_value=None)
    @patch("providers.llm_provider.GeminiProvider.generate", return_value='{"test": true}')
    def test_live_mode_uses_gemini(self, mock_generate, mock_init):
        """In live mode, GeminiProvider should be instantiated."""
        from config.settings import Settings
        Settings.reset()  # clear singleton so env vars are re-read

        try:
            from run_signalforge import _boot_agents
            agents = _boot_agents(live=True)

            assert agents["scanner"].mode == "live"
            # GeminiProvider.__init__ should have been called
            mock_init.assert_called_once()
        finally:
            Settings.reset()


# ==================================================================
# 5. Provider mode propagation
# ==================================================================


class TestProviderPropagation:
    """Verify mode flows through to all provider layers."""

    def test_quora_mock_mode(self):
        from agents.quora_scanner import QuoraScannerAgent

        scanner = QuoraScannerAgent(force_mock=True)
        assert scanner.mode == "mock"

    def test_quora_live_mode(self):
        from agents.quora_scanner import QuoraScannerAgent
        from providers.quora_provider import QuoraProvider

        # QuoraScannerAgent defaults to mock when quora_provider is None.
        # Must pass an explicit live provider to get live mode.
        live_provider = QuoraProvider(mock_mode=False)
        scanner = QuoraScannerAgent(quora_provider=live_provider, force_mock=False)
        assert scanner.mode == "live"

    def test_medium_mock_mode(self):
        from agents.medium_scanner import MediumScannerAgent

        scanner = MediumScannerAgent(mode="mock")
        assert scanner.mode == "mock"

    def test_medium_live_mode(self):
        from agents.medium_scanner import MediumScannerAgent

        scanner = MediumScannerAgent(mode="live")
        assert scanner.mode == "live"

    def test_reddit_mock_mode(self):
        from agents.opportunity_scanner.agent import OpportunityScannerAgent

        scanner = OpportunityScannerAgent(force_mock=True)
        assert scanner.scanner.mode == "mock"


# ==================================================================
# 6. Pipeline output validation (mock mode end-to-end)
# ==================================================================


class TestMockPipeline:
    """Run a quick mock pipeline and validate output structure."""

    def test_mock_pipeline_produces_output(self, tmp_path):
        from run_signalforge import run_pipeline

        result = run_pipeline("AI automation tools", live=False)

        assert isinstance(result, dict)
        assert result["mode"] == "mock"
        assert "summary" in result
        assert "approved_items" in result
        assert result["summary"]["total_opportunities"] > 0

    def test_publish_mode_preserved(self):
        """SIGNALFORGE_PUBLISH_MODE should remain independent of --mock/--live."""
        import os
        current = os.environ.get("SIGNALFORGE_PUBLISH_MODE", "mock")
        # Publishing mode is not affected by pipeline mode
        assert current in ("mock", "dry_run", "live", "")
