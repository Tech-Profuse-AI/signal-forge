"""
SignalForge Phase 17 - Publisher tests.

Tests:
  - Single publish routing to each platform
  - Batch publish with mixed results
  - Platform routing / detection
  - Failure simulation (unknown platform, missing fields, publisher exception)

All publishers are mocked; no real API calls are made.
"""

from __future__ import annotations

import sys
import os
import types
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(
    platform: str,
    opportunity_id: str = "opp-001",
    draft_text: str = "Test draft body.",
) -> Dict[str, Any]:
    return {
        "platform": platform,
        "opportunity": {
            "id": opportunity_id,
            "platform": platform,
            "title": f"Test opportunity on {platform}",
        },
        "draft": {
            "title": f"Test title for {platform}",
            "draft": draft_text,
            "cta": "Learn more.",
        },
    }


def _mock_publish_success(platform: str):
    """Return a mock publish() callable that always succeeds."""
    def _publish(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "platform": platform,
            "published_url": f"https://mock.{platform}.com/posts/abc123",
            "status": "mock_published",
        }
    return _publish


def _mock_publish_failure(platform: str, reason: str = "simulated failure"):
    """Return a mock publish() callable that always fails."""
    def _publish(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": False,
            "platform": platform,
            "published_url": None,
            "status": f"error: {reason}",
        }
    return _publish


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSinglePublish(unittest.TestCase):
    """Test PublisherRouter.publish() for each supported platform."""

    def _make_router_with_mocks(self, overrides: Dict[str, bool]):
        """
        Build a PublisherRouter whose internal publishers are replaced with
        mocks. overrides maps platform -> success (True/False).
        """
        from integrations.publisher import PublisherRouter
        from integrations.platform_publishers import (
            RedditPublisher,
            QuoraPublisher,
            MediumPublisher,
        )

        router = PublisherRouter()
        for platform, success in overrides.items():
            mock_pub = MagicMock()
            mock_pub.publish.side_effect = (
                _mock_publish_success(platform)
                if success
                else _mock_publish_failure(platform)
            )
            router._publishers[platform] = mock_pub
        return router

    def test_publish_reddit_success(self):
        router = self._make_router_with_mocks({"reddit": True})
        item = _make_item("reddit")
        result = router.publish(item)

        self.assertTrue(result["success"])
        self.assertEqual(result["platform"], "reddit")
        self.assertIsNotNone(result["published_url"])
        self.assertEqual(result["status"], "mock_published")
        self.assertEqual(router.success_count, 1)
        self.assertEqual(router.failure_count, 0)

    def test_publish_quora_success(self):
        router = self._make_router_with_mocks({"quora": True})
        item = _make_item("quora")
        result = router.publish(item)

        self.assertTrue(result["success"])
        self.assertEqual(result["platform"], "quora")
        self.assertEqual(router.success_count, 1)

    def test_publish_medium_success(self):
        router = self._make_router_with_mocks({"medium": True})
        item = _make_item("medium")
        result = router.publish(item)

        self.assertTrue(result["success"])
        self.assertEqual(result["platform"], "medium")
        self.assertEqual(router.success_count, 1)

    def test_publish_unknown_platform(self):
        router = self._make_router_with_mocks({})
        item = _make_item("twitter")
        result = router.publish(item)

        self.assertFalse(result["success"])
        self.assertIn("twitter", result["platform"])
        self.assertIsNone(result["published_url"])
        self.assertEqual(router.failure_count, 1)
        self.assertEqual(router.success_count, 0)

    def test_publish_missing_platform_key(self):
        router = self._make_router_with_mocks({})
        item = {"opportunity": {"id": "opp-x"}, "draft": {"draft": "body"}}
        result = router.publish(item)

        self.assertFalse(result["success"])
        self.assertEqual(router.failure_count, 1)

    def test_platform_detected_from_opportunity(self):
        """Platform missing from top level but present in opportunity."""
        from integrations.publisher import PublisherRouter
        router = PublisherRouter()
        mock_pub = MagicMock()
        mock_pub.publish.side_effect = _mock_publish_success("reddit")
        router._publishers["reddit"] = mock_pub

        item = {
            "opportunity": {"id": "opp-y", "platform": "reddit"},
            "draft": {"draft": "body text"},
        }
        result = router.publish(item)
        self.assertTrue(result["success"])
        self.assertEqual(result["platform"], "reddit")


class TestBatchPublish(unittest.TestCase):
    """Test PublisherRouter.publish_batch() behaviour."""

    def _make_router_with_mixed_mocks(self):
        from integrations.publisher import PublisherRouter
        router = PublisherRouter()

        reddit_mock = MagicMock()
        reddit_mock.publish.side_effect = _mock_publish_success("reddit")

        quora_mock = MagicMock()
        quora_mock.publish.side_effect = _mock_publish_failure("quora", "API error")

        medium_mock = MagicMock()
        medium_mock.publish.side_effect = _mock_publish_success("medium")

        router._publishers["reddit"] = reddit_mock
        router._publishers["quora"] = quora_mock
        router._publishers["medium"] = medium_mock
        return router

    def test_batch_continues_on_failure(self):
        router = self._make_router_with_mixed_mocks()
        items = [
            _make_item("reddit", "opp-1"),
            _make_item("quora", "opp-2"),
            _make_item("medium", "opp-3"),
        ]
        results = router.publish_batch(items)

        self.assertEqual(len(results), 3)
        self.assertTrue(results[0]["success"])
        self.assertFalse(results[1]["success"])
        self.assertTrue(results[2]["success"])

    def test_batch_counts_tracked(self):
        router = self._make_router_with_mixed_mocks()
        items = [
            _make_item("reddit", "opp-a"),
            _make_item("quora", "opp-b"),
            _make_item("medium", "opp-c"),
            _make_item("reddit", "opp-d"),
        ]
        router.publish_batch(items)

        self.assertEqual(router.success_count, 3)
        self.assertEqual(router.failure_count, 1)

    def test_batch_empty_list(self):
        from integrations.publisher import PublisherRouter
        router = PublisherRouter()
        results = router.publish_batch([])
        self.assertEqual(results, [])
        self.assertEqual(router.success_count, 0)
        self.assertEqual(router.failure_count, 0)

    def test_batch_all_unknown_platforms(self):
        from integrations.publisher import PublisherRouter
        router = PublisherRouter()
        items = [_make_item("linkedin"), _make_item("twitter")]
        results = router.publish_batch(items)

        self.assertEqual(len(results), 2)
        for r in results:
            self.assertFalse(r["success"])
        self.assertEqual(router.failure_count, 2)
        self.assertEqual(router.success_count, 0)

    def test_batch_publisher_exception_does_not_halt(self):
        """An unhandled exception inside a publisher does not abort the batch."""
        from integrations.publisher import PublisherRouter
        router = PublisherRouter()

        exploding_mock = MagicMock()
        exploding_mock.publish.side_effect = RuntimeError("boom")
        router._publishers["reddit"] = exploding_mock

        medium_mock = MagicMock()
        medium_mock.publish.side_effect = _mock_publish_success("medium")
        router._publishers["medium"] = medium_mock

        items = [_make_item("reddit", "opp-x"), _make_item("medium", "opp-y")]
        results = router.publish_batch(items)

        self.assertEqual(len(results), 2)
        self.assertFalse(results[0]["success"])
        self.assertTrue(results[1]["success"])
        self.assertEqual(router.failure_count, 1)
        self.assertEqual(router.success_count, 1)


class TestPlatformRouting(unittest.TestCase):
    """Test _detect_platform and routing logic directly."""

    def test_detect_platform_from_item(self):
        from integrations.publisher import PublisherRouter
        item = {"platform": "Reddit", "opportunity": {}, "draft": {}}
        result = PublisherRouter._detect_platform(item)
        self.assertEqual(result, "reddit")

    def test_detect_platform_from_opportunity_platform(self):
        from integrations.publisher import PublisherRouter
        item = {"opportunity": {"platform": "Medium"}, "draft": {}}
        result = PublisherRouter._detect_platform(item)
        self.assertEqual(result, "medium")

    def test_detect_platform_from_opportunity_source(self):
        from integrations.publisher import PublisherRouter
        item = {"opportunity": {"source": "Quora"}, "draft": {}}
        result = PublisherRouter._detect_platform(item)
        self.assertEqual(result, "quora")

    def test_detect_platform_none_when_missing(self):
        from integrations.publisher import PublisherRouter
        item = {"opportunity": {}, "draft": {}}
        result = PublisherRouter._detect_platform(item)
        self.assertIsNone(result)

    def test_router_maps_all_supported_platforms(self):
        from integrations.publisher import PublisherRouter, _PLATFORM_MAP
        self.assertIn("reddit", _PLATFORM_MAP)
        self.assertIn("quora", _PLATFORM_MAP)
        self.assertIn("medium", _PLATFORM_MAP)


class TestMediumLivePublishing(unittest.TestCase):
    """Medium live path: compliance gate, credentials, mocked HTTP (no real posts)."""

    def tearDown(self) -> None:
        import integrations.platform_publishers as pp_module

        pp_module.MOCK_MODE = True
        try:
            from config.settings import Settings

            Settings.reset()
        except Exception:  # noqa: BLE001
            pass

    def _live_item(self, **kwargs: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "platform": "medium",
            "opportunity": {"id": "opp-medium-1", "platform": "medium"},
            "draft": {
                "title": "Article title",
                "content": "Hello **world** — markdown body.",
            },
            "compliance": {"approved": True, "risk_level": "safe"},
        }
        base.update(kwargs)
        return base

    def test_medium_live_publish_success(self):
        import integrations.platform_publishers as pp_module
        from integrations.platform_publishers import MediumPublisher

        pp_module.MOCK_MODE = False
        with patch.dict(
            os.environ,
            {
                "MEDIUM_INTEGRATION_TOKEN": "test-integration-token",
                "MEDIUM_USER_ID": "1234abcd",
                "MEDIUM_PUBLISH_STATUS": "draft",
                "MEDIUM_CONTENT_FORMAT": "markdown",
            },
            clear=False,
        ):
            with patch(
                "integrations.platform_publishers._medium_http_json",
                return_value=(
                    201,
                    {
                        "data": {
                            "id": "post-xyz",
                            "url": "https://medium.com/p/post-xyz",
                        }
                    },
                ),
            ) as mock_http:
                from config.settings import Settings

                Settings.reset()
                pub = MediumPublisher()
                result = pub.publish(self._live_item())

        self.assertTrue(result["success"])
        self.assertEqual(result["platform"], "medium")
        self.assertEqual(result["medium_post_id"], "post-xyz")
        self.assertIn("medium.com", result["published_url"] or "")
        mock_http.assert_called_once()
        kw = mock_http.call_args.kwargs
        self.assertEqual(kw.get("method"), "POST")
        posted = kw.get("body")
        self.assertIsNotNone(posted)
        self.assertEqual(posted.get("contentFormat"), "markdown")
        self.assertEqual(posted.get("publishStatus"), "draft")
        self.assertIn("content", posted)

    def test_medium_live_missing_credentials(self):
        import integrations.platform_publishers as pp_module
        from integrations.platform_publishers import MediumPublisher

        pp_module.MOCK_MODE = False
        with patch.dict(os.environ, {"MEDIUM_INTEGRATION_TOKEN": ""}, clear=False):
            from config.settings import Settings

            Settings.reset()
            pub = MediumPublisher()
            result = pub.publish(self._live_item())

        self.assertFalse(result["success"])
        self.assertIn("MEDIUM_INTEGRATION_TOKEN", result["status"])
        self.assertIsNone(result["published_url"])
        self.assertIsNone(result["medium_post_id"])

    def test_medium_live_missing_user_id_me_failure(self):
        import integrations.platform_publishers as pp_module
        from integrations.platform_publishers import MediumPublisher

        pp_module.MOCK_MODE = False
        with patch.dict(
            os.environ,
            {
                "MEDIUM_INTEGRATION_TOKEN": "tok",
                "MEDIUM_USER_ID": "",
            },
            clear=False,
        ):
            with patch(
                "integrations.platform_publishers._medium_http_json",
                return_value=(401, {"errors": [{"message": "unauthorized"}]}),
            ):
                from config.settings import Settings

                Settings.reset()
                pub = MediumPublisher()
                result = pub.publish(self._live_item())

        self.assertFalse(result["success"])
        self.assertIsNone(result["medium_post_id"])

    def test_medium_compliance_missing_blocks_live(self):
        import integrations.platform_publishers as pp_module
        from integrations.platform_publishers import MediumPublisher

        pp_module.MOCK_MODE = False
        with patch.dict(
            os.environ,
            {"MEDIUM_INTEGRATION_TOKEN": "tok", "MEDIUM_USER_ID": "u1"},
            clear=False,
        ):
            with patch(
                "integrations.platform_publishers._medium_http_json"
            ) as mock_http:
                from config.settings import Settings

                Settings.reset()
                pub = MediumPublisher()
                item = self._live_item()
                del item["compliance"]
                result = pub.publish(item)

        self.assertFalse(result["success"])
        self.assertIn("compliance", result["status"].lower())
        mock_http.assert_not_called()

    def test_medium_compliance_rejected_blocks_live(self):
        import integrations.platform_publishers as pp_module
        from integrations.platform_publishers import MediumPublisher

        pp_module.MOCK_MODE = False
        with patch.dict(
            os.environ,
            {"MEDIUM_INTEGRATION_TOKEN": "tok", "MEDIUM_USER_ID": "u1"},
            clear=False,
        ):
            with patch(
                "integrations.platform_publishers._medium_http_json"
            ) as mock_http:
                from config.settings import Settings

                Settings.reset()
                pub = MediumPublisher()
                result = pub.publish(
                    self._live_item(compliance={"approved": False, "risk_level": "reject"})
                )

        self.assertFalse(result["success"])
        self.assertIn("not approved", result["status"].lower())
        mock_http.assert_not_called()

    def test_medium_mock_mode_does_not_require_compliance_or_token(self):
        import integrations.platform_publishers as pp_module
        from integrations.platform_publishers import MediumPublisher

        pp_module.MOCK_MODE = True
        with patch.dict(os.environ, {"MEDIUM_INTEGRATION_TOKEN": ""}, clear=False):
            from config.settings import Settings

            Settings.reset()
            pub = MediumPublisher()
            result = pub.publish(
                {
                    "platform": "medium",
                    "opportunity": {"id": "o1"},
                    "draft": {"title": "T", "draft": "Body only"},
                }
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "mock_published")
        self.assertIsNotNone(result.get("medium_post_id"))


class TestFailureSimulation(unittest.TestCase):
    """Test failure scenarios explicitly."""

    def test_publisher_returns_failure_result(self):
        from integrations.publisher import PublisherRouter
        router = PublisherRouter()

        fail_mock = MagicMock()
        fail_mock.publish.side_effect = _mock_publish_failure("reddit", "quota exceeded")
        router._publishers["reddit"] = fail_mock

        result = router.publish(_make_item("reddit"))
        self.assertFalse(result["success"])
        self.assertIn("quota exceeded", result["status"])
        self.assertIsNone(result["published_url"])
        self.assertEqual(router.failure_count, 1)

    def test_mock_mode_base_publisher(self):
        """BasePublisher._publish_mock returns success with a mock URL."""
        from integrations.platform_publishers import RedditPublisher
        import integrations.platform_publishers as pp_module

        original = pp_module.MOCK_MODE
        try:
            pp_module.MOCK_MODE = True
            pub = RedditPublisher()
            result = pub.publish(_make_item("reddit"))
            self.assertTrue(result["success"])
            self.assertIn("mock.reddit.com", result["published_url"])
            self.assertEqual(result["status"], "mock_published")
        finally:
            pp_module.MOCK_MODE = original

    def test_reset_counts(self):
        from integrations.publisher import PublisherRouter
        router = PublisherRouter()
        router.success_count = 5
        router.failure_count = 3
        router.reset_counts()
        self.assertEqual(router.success_count, 0)
        self.assertEqual(router.failure_count, 0)


# ---------------------------------------------------------------------------
# Runner with printed summary
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        TestSinglePublish,
        TestBatchPublish,
        TestPlatformRouting,
        TestMediumLivePublishing,
        TestFailureSimulation,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    published_count = 0
    failed_count = 0
    platform_status: Dict[str, str] = {}

    # Run a live summary using actual router with mocked publishers
    try:
        from integrations.publisher import PublisherRouter
        from integrations.platform_publishers import (
            RedditPublisher, QuoraPublisher, MediumPublisher
        )
        import integrations.platform_publishers as pp_module

        pp_module.MOCK_MODE = True
        router = PublisherRouter()

        sample_items = [
            _make_item("reddit", "summary-1"),
            _make_item("quora", "summary-2"),
            _make_item("medium", "summary-3"),
        ]
        batch_results = router.publish_batch(sample_items)

        for r in batch_results:
            plat = r["platform"]
            if r["success"]:
                published_count += 1
                platform_status[plat] = f"published -> {r['published_url']}"
            else:
                failed_count += 1
                platform_status[plat] = f"failed -> {r['status']}"

    except Exception as exc:  # noqa: BLE001
        print(f"\n[summary] Could not run live summary: {exc}")

    print("\n" + "=" * 60)
    print("PUBLISHER SUMMARY")
    print("=" * 60)
    print(f"  Published count : {published_count}")
    print(f"  Failed count    : {failed_count}")
    print("  Platform status :")
    for plat, status in platform_status.items():
        print(f"    {plat:<10} {status}")
    print("=" * 60)

    sys.exit(0 if result.wasSuccessful() else 1)