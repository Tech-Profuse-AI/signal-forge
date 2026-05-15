"""
SignalForge Quora Post Provider.

Quora has no public posting API, so this provider implements a
manual-assist workflow: approved answers are formatted, validated,
and saved to outputs/pending_posts/ for the operator to copy-paste
into the Quora web UI.

When FIRECRAWL_API_KEY is set the provider will first validate that
the target question URL still exists before saving the draft.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logger = logging.getLogger("signalforge.quora_post")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PENDING_POSTS_DIR = _PROJECT_ROOT / "outputs" / "pending_posts"
_USER_AGENT = (
    "Mozilla/5.0 (compatible; SignalForge/1.0; +https://signalforge.io)"
)

# ── Reading-speed constant used for estimated read time ──────────────
_WORDS_PER_MINUTE = 238  # average adult reading speed


class QuoraPostProvider:
    """
    Format and save Quora answer drafts for manual posting.

    Args:
        pending_posts_dir: Directory where draft artefacts are written.
                           Defaults to ``outputs/pending_posts/``.
    """

    def __init__(
        self,
        *,
        pending_posts_dir: Optional[str] = None,
    ) -> None:
        self._pending_posts_dir = (
            Path(pending_posts_dir) if pending_posts_dir else _DEFAULT_PENDING_POSTS_DIR
        )
        self._pending_posts_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "QuoraPostProvider initialised — pending_posts_dir=%s",
            self._pending_posts_dir,
        )

    # ── Public API ────────────────────────────────────────────────────

    def prepare_answer(
        self,
        question_url: str,
        draft_text: str,
    ) -> Dict[str, Any]:
        """
        Format a draft answer and save it for manual posting on Quora.

        Steps:
            1. Validate inputs.
            2. If ``FIRECRAWL_API_KEY`` is set, verify the question URL
               still resolves (Firecrawl scrape).
            3. Build a structured payload with the formatted draft,
               character count, estimated read time, and timestamp.
            4. Write the payload to ``outputs/pending_posts/quora_{ts}.json``.
            5. Log a confirmation message.

        Args:
            question_url: Full Quora question URL.
            draft_text:   Plain-text or markdown draft answer.

        Returns:
            The saved payload dict.

        Raises:
            ValueError: If inputs are empty or the question URL is
                        unreachable (when validation is enabled).
        """
        clean_url = str(question_url).strip()
        clean_draft = str(draft_text).strip()

        if not clean_url:
            raise ValueError("question_url is required.")
        if not clean_draft:
            raise ValueError("draft_text is required.")

        # ── Optional Firecrawl validation ─────────────────────────────
        firecrawl_key = str(os.environ.get("FIRECRAWL_API_KEY", "") or "").strip()
        if firecrawl_key:
            self._validate_question_url(clean_url, firecrawl_key)

        # ── Build payload ─────────────────────────────────────────────
        timestamp = datetime.now(timezone.utc)
        char_count = len(clean_draft)
        word_count = len(clean_draft.split())
        estimated_read_time_min = max(1, math.ceil(word_count / _WORDS_PER_MINUTE))

        payload: Dict[str, Any] = {
            "platform": "quora",
            "status": "pending_manual_post",
            "question_url": clean_url,
            "draft_text": clean_draft,
            "character_count": char_count,
            "estimated_read_time": f"{estimated_read_time_min} min read",
            "created_at": timestamp.isoformat(),
        }

        # ── Persist to disk ───────────────────────────────────────────
        file_timestamp = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
        out_path = self._pending_posts_dir / f"quora_{file_timestamp}.json"
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

        logger.info(
            "Quora answer prepared for manual posting \u2014 saved to outputs/pending_posts/"
        )

        return payload

    # ── Firecrawl URL validation ──────────────────────────────────────

    def _validate_question_url(self, url: str, api_key: str) -> None:
        """
        Use Firecrawl to verify the Quora question page still exists.

        Raises ``ValueError`` if the page cannot be reached or Firecrawl
        reports an unsuccessful scrape.
        """
        endpoint = "https://api.firecrawl.dev/v1/scrape"
        body = json.dumps({
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
        }).encode("utf-8")

        req = Request(
            endpoint,
            method="POST",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            if not data.get("success"):
                raise ValueError(
                    f"Quora question URL validation failed — page may no longer exist: {url}"
                )
            logger.info("Quora question URL validated via Firecrawl: %s", url)
        except HTTPError as exc:
            raise ValueError(
                f"Quora question URL unreachable (HTTP {exc.code}): {url}"
            ) from exc
        except URLError as exc:
            raise ValueError(
                f"Quora question URL unreachable (network error): {url}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Firecrawl returned non-JSON response for: {url}"
            ) from exc

    # ── Helpers ───────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return "<QuoraPostProvider mode='manual_assist'>"
