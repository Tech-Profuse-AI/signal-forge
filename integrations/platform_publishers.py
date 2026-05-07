"""
SignalForge Phase 17 - Platform Publishers.

Concrete publisher implementations for Reddit, Quora, and Medium.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from config.settings import Settings

logger = logging.getLogger("signalforge.platform_publishers")

MOCK_MODE = os.environ.get("SIGNALFORGE_PUBLISH_MODE", "mock").lower() == "mock"


class BasePublisher:
    """Abstract base publisher. Subclasses implement _publish_live."""

    platform: str = "base"

    def publish(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Publish item to platform.

        Args:
            item: dict with keys: opportunity, draft, platform

        Returns:
            dict with: success, platform, published_url, status
        """
        platform = str(item.get("platform", self.platform)).lower()
        draft = item.get("draft", {})
        opportunity = item.get("opportunity", {})

        logger.info(
            "Publishing to %s - mock=%s opportunity_id=%s",
            platform,
            MOCK_MODE,
            opportunity.get("id", "unknown"),
        )

        try:
            if MOCK_MODE:
                return self._publish_mock(item)
            return self._publish_live(item)
        except Exception as exc:  # noqa: BLE001
            logger.error("Publish failed on %s: %s", self.platform, exc)
            return {
                "success": False,
                "platform": self.platform,
                "published_url": None,
                "status": f"error: {exc}",
            }

    def _publish_mock(self, item: Dict[str, Any]) -> Dict[str, Any]:
        mock_id = uuid.uuid4().hex[:10]
        url = f"https://mock.{self.platform}.com/posts/{mock_id}"
        logger.info("Mock publish on %s - url=%s", self.platform, url)
        return {
            "success": True,
            "platform": self.platform,
            "published_url": url,
            "status": "mock_published",
        }

    def _publish_live(self, item: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement live publishing."
        )


class RedditPublisher(BasePublisher):
    """Publisher for Reddit."""

    platform: str = "reddit"

    def _publish_live(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare real Reddit submission via PRAW or Reddit API.
        Requires env vars: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
        REDDIT_USERNAME, REDDIT_PASSWORD, REDDIT_SUBREDDIT.
        """
        client_id = os.environ.get("REDDIT_CLIENT_ID", "")
        client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
        username = os.environ.get("REDDIT_USERNAME", "")
        password = os.environ.get("REDDIT_PASSWORD", "")
        subreddit = os.environ.get("REDDIT_SUBREDDIT", "")

        if not all([client_id, client_secret, username, password, subreddit]):
            return {
                "success": False,
                "platform": self.platform,
                "published_url": None,
                "status": "error: missing Reddit credentials in environment",
            }

        draft = item.get("draft", {})
        title = str(draft.get("title", draft.get("subject", "SignalForge Post")))
        body = str(draft.get("draft", draft.get("body", "")))

        # Live implementation placeholder:
        # import praw
        # reddit = praw.Reddit(client_id=client_id, client_secret=client_secret,
        #                      username=username, password=password,
        #                      user_agent="SignalForge/1.0")
        # submission = reddit.subreddit(subreddit).submit(title=title, selftext=body)
        # post_url = submission.url

        return {
            "success": False,
            "platform": self.platform,
            "published_url": None,
            "status": "live_not_implemented: install praw and complete integration",
        }


class QuoraPublisher(BasePublisher):
    """Publisher for Quora."""

    platform: str = "quora"

    def _publish_live(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare real Quora answer submission.
        Requires env vars: QUORA_API_KEY, QUORA_QUESTION_URL.
        Quora does not offer a public API; Selenium/browser automation required.
        """
        api_key = os.environ.get("QUORA_API_KEY", "")
        question_url = os.environ.get("QUORA_QUESTION_URL", "")

        if not question_url:
            opportunity = item.get("opportunity", {})
            question_url = str(opportunity.get("url", ""))

        if not question_url:
            return {
                "success": False,
                "platform": self.platform,
                "published_url": None,
                "status": "error: QUORA_QUESTION_URL not set and no opportunity url",
            }

        draft = item.get("draft", {})
        body = str(draft.get("draft", draft.get("body", "")))

        # Live implementation placeholder (requires browser automation):
        # from quora_automation import QuoraClient
        # client = QuoraClient(api_key=api_key)
        # result = client.post_answer(question_url=question_url, answer=body)
        # answer_url = result["url"]

        return {
            "success": False,
            "platform": self.platform,
            "published_url": None,
            "status": "live_not_implemented: Quora requires browser automation",
        }


_VALID_MEDIUM_PUBLISH_STATUS = frozenset({"draft", "public", "unlisted"})
_VALID_MEDIUM_CONTENT_FORMAT = frozenset({"markdown", "html"})
_MEDIUM_ME_URL = "https://api.medium.com/v1/me"
_MEDIUM_POSTS_PATH = "https://api.medium.com/v1/users/{author_id}/posts"


def _medium_failure(
    status: str,
    *,
    url: Optional[str] = None,
    post_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "success": False,
        "platform": "medium",
        "published_url": url,
        "status": status,
        "medium_post_id": post_id,
    }


def _medium_success(
    status: str,
    published_url: str,
    post_id: str,
) -> Dict[str, Any]:
    return {
        "success": True,
        "platform": "medium",
        "published_url": published_url,
        "status": status,
        "medium_post_id": post_id,
    }


def _medium_compliance_gate(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a failure dict if publishing must not proceed."""
    compliance = item.get("compliance")
    if not isinstance(compliance, dict):
        return _medium_failure(
            "error: compliance missing or invalid — publishing blocked",
        )
    if compliance.get("approved") is not True:
        return _medium_failure(
            "error: compliance not approved — publishing blocked",
        )
    return None


def _medium_extract_title_and_content(draft: Any) -> Tuple[str, str]:
    if not isinstance(draft, dict):
        return "SignalForge Article", ""
    title = str(
        draft.get("title")
        or draft.get("subject")
        or "SignalForge Article"
    ).strip()
    body = draft.get("content")
    if body is None:
        body = draft.get("draft") or draft.get("body") or ""
    return title, str(body)


def _medium_normalise_tags(draft: Dict[str, Any]) -> List[str]:
    tags = draft.get("tags", [])
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    return []


def _medium_http_json(
    url: str,
    *,
    method: str,
    token: str,
    body: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
) -> Tuple[int, Any]:
    """
    Perform a Medium API request and return (http_code, parsed_json_or_text).

    On network failure, raises urllib.error.URLError.
    """
    data_bytes: Optional[bytes] = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if body is not None:
        data_bytes = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            code = getattr(resp, "status", 200) or 200
    except urllib.error.HTTPError as exc:
        code = exc.code
        raw = exc.read().decode("utf-8", errors="replace")

    try:
        parsed: Any = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        parsed = raw
    return code, parsed


def _medium_resolve_author_id(token: str, configured_user_id: str) -> Tuple[Optional[str], str]:
    uid = (configured_user_id or "").strip()
    if uid:
        return uid, ""
    try:
        code, parsed = _medium_http_json(
            _MEDIUM_ME_URL,
            method="GET",
            token=token,
            body=None,
            timeout=30,
        )
    except urllib.error.URLError as exc:
        return None, f"error: network failure resolving Medium user id — {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"error: unexpected failure resolving Medium user id — {exc}"

    if code != 200 or not isinstance(parsed, dict):
        return None, f"error: Medium /me returned HTTP {code}"

    author = parsed.get("data", {})
    author_id = author.get("id") if isinstance(author, dict) else None
    if not author_id:
        return None, "error: Medium /me response missing user id"
    return str(author_id), ""


class MediumPublisher(BasePublisher):
    """Publisher for Medium (mock or Integration Token live API)."""

    platform: str = "medium"

    def _publish_mock(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Preserve mock URLs and add Medium-specific identifiers."""
        out = super()._publish_mock(item)
        post_id: Optional[str] = None
        pub_url = out.get("published_url")
        if isinstance(pub_url, str) and pub_url:
            post_id = pub_url.rstrip("/").split("/")[-1] or None
        out["medium_post_id"] = post_id
        return out

    def _publish_live(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Publish to Medium via Integration Token API.

        Requires ``MEDIUM_INTEGRATION_TOKEN``. ``MEDIUM_USER_ID`` is optional
        if the token can resolve the author via ``GET /v1/me``.

        Configure ``MEDIUM_PUBLISH_STATUS`` (draft | public | unlisted) and
        ``MEDIUM_CONTENT_FORMAT`` (markdown | html) via environment / .env
        (loaded through :class:`config.settings.Settings`).
        """
        gate = _medium_compliance_gate(item)
        if gate is not None:
            return gate

        try:
            settings = Settings()
        except Exception as exc:  # noqa: BLE001
            return _medium_failure(f"error: could not load settings — {exc}")

        token = (settings.medium_integration_token or "").strip()
        if not token:
            return _medium_failure("error: MEDIUM_INTEGRATION_TOKEN not set")

        author_id, err = _medium_resolve_author_id(token, settings.medium_user_id)
        if not author_id:
            return _medium_failure(err or "error: MEDIUM_USER_ID not set and /me lookup failed")

        draft = item.get("draft", {})
        if not isinstance(draft, dict):
            draft = {}

        title, content = _medium_extract_title_and_content(draft)
        if not content.strip():
            return _medium_failure("error: draft content is empty — nothing to publish")

        publish_status = (settings.medium_publish_status or "draft").lower()
        if publish_status not in _VALID_MEDIUM_PUBLISH_STATUS:
            publish_status = "draft"

        content_format = (settings.medium_content_format or "markdown").lower()
        if content_format not in _VALID_MEDIUM_CONTENT_FORMAT:
            content_format = "markdown"

        payload: Dict[str, Any] = {
            "title": title,
            "contentFormat": content_format,
            "content": content,
            "publishStatus": publish_status,
        }
        tags = _medium_normalise_tags(draft)
        if tags:
            payload["tags"] = tags[:5]

        post_url = _MEDIUM_POSTS_PATH.format(author_id=author_id)

        try:
            code, parsed = _medium_http_json(
                post_url,
                method="POST",
                token=token,
                body=payload,
                timeout=60,
            )
        except urllib.error.URLError as exc:
            return _medium_failure(f"error: network failure calling Medium API — {exc}")
        except Exception as exc:  # noqa: BLE001
            return _medium_failure(f"error: unexpected network error — {exc}")

        if code not in (200, 201) or not isinstance(parsed, dict):
            msg = f"error: Medium API HTTP {code}"
            if isinstance(parsed, dict) and parsed.get("errors"):
                msg = f"{msg} — {parsed.get('errors')}"
            elif isinstance(parsed, str) and parsed:
                msg = f"{msg} — {parsed[:500]}"
            return _medium_failure(msg)

        data = parsed.get("data", {})
        if not isinstance(data, dict):
            return _medium_failure("error: invalid Medium API response — missing data")

        medium_post_id = data.get("id")
        published_url = data.get("url") or data.get("canonicalUrl")
        if not medium_post_id:
            return _medium_failure(
                "error: invalid Medium API response — missing post id",
            )

        url_str = str(published_url) if published_url else ""
        if not url_str:
            url_str = f"https://medium.com/p/{medium_post_id}"

        status_label = f"published:{publish_status}"
        return _medium_success(status_label, url_str, str(medium_post_id))