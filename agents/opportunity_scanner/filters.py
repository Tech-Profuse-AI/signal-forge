"""
SignalForge Opportunity Filters.

Classifies and filters Reddit posts to separate high-value engagement
opportunities from noise (deleted posts, memes, bot spam, low-effort).

Filter categories:
  REJECT — deleted, low-effort, memes, bot / spam posts
  KEEP   — help requests, recommendation requests, pain-point posts,
            workflow bottleneck discussions

Configurable thresholds:
  - minimum_score       (default: 5)
  - minimum_body_length (default: 50 characters)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("signalforge.filters")


# ── Configurable thresholds ──────────────────────────────────────────

@dataclass
class FilterConfig:
    """Tunable thresholds for the opportunity filter."""

    minimum_score: int = 5
    minimum_body_length: int = 50

    # Subreddits that are almost never engagement-worthy
    blacklisted_subreddits: List[str] = field(default_factory=lambda: [
        "memes", "dankmemes", "funny", "shitposting",
        "FreeKarma4U", "FreeKarma4You", "KarmaFarming4Pros",
        "test", "circlejerk",
    ])

    # Author patterns that strongly indicate bots
    bot_author_patterns: List[str] = field(default_factory=lambda: [
        r"b[o0]t",
        r"auto[-_]?mod",
        r"spam",
        r"^RemindMeBot$",
        r"^AutoModerator$",
    ])

    # Title / body keyword signals for KEEPING posts
    help_keywords: List[str] = field(default_factory=lambda: [
        "help", "how do i", "how to", "need advice", "stuck on",
        "can someone explain", "struggling with", "issue with",
        "problem with", "question about", "confused about",
    ])

    recommendation_keywords: List[str] = field(default_factory=lambda: [
        "recommend", "suggestion", "best tool", "looking for",
        "any good", "what do you use", "alternative to",
        "which one", "comparison", "vs",
    ])

    pain_point_keywords: List[str] = field(default_factory=lambda: [
        "pain point", "frustrat", "annoying", "broken",
        "doesn't work", "hate that", "wish there was",
        "rant", "vent", "unsustainable", "killing my",
    ])

    bottleneck_keywords: List[str] = field(default_factory=lambda: [
        "bottleneck", "workflow", "automat", "manual process",
        "takes too long", "time consuming", "at scale",
        "can't keep up", "doesn't scale", "inefficient",
    ])

    # Meme / low-effort title patterns
    meme_patterns: List[str] = field(default_factory=lambda: [
        r"^\.+$",
        r"^ok$",
        r"^lmao",
        r"^lol",
        r"🔥{2,}",
        r"🚨.*upvote",
        r"free (followers|karma)",
        r"upvote.*(4|for).*upvote",
    ])


# ── Filter engine ────────────────────────────────────────────────────

class OpportunityFilter:
    """
    Classifies Reddit posts as either *keep* or *reject*.

    Usage::

        filt = OpportunityFilter()                       # defaults
        filt = OpportunityFilter(FilterConfig(minimum_score=10))  # custom

        kept = filt.filter_opportunities(posts)
    """

    def __init__(self, config: Optional[FilterConfig] = None) -> None:
        self.config = config or FilterConfig()
        logger.info(
            "OpportunityFilter initialised — min_score=%d, min_body=%d",
            self.config.minimum_score,
            self.config.minimum_body_length,
        )

    # ── Public API ────────────────────────────────────────────────────

    def filter_opportunities(
        self, posts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Return only the posts that pass all rejection checks and
        match at least one keep signal.

        Each kept post gets an extra ``"opportunity_signals"`` key
        listing why it was kept (e.g. ``["help_request", "bottleneck"]``).
        """
        kept: List[Dict[str, Any]] = []

        for post in posts:
            reject_reason = self._check_rejection(post)
            if reject_reason:
                logger.info(
                    "REJECTED [%s] %s — reason: %s, len: %d, score: %d",
                    post.get("id", "?"),
                    post.get("title", "")[:50],
                    reject_reason,
                    len(post.get("body", "")),
                    post.get("score", 0),
                )
                continue

            signals = self._detect_signals(post)
            if not signals:
                logger.debug(
                    "NO SIGNAL [%s] %s",
                    post.get("id", "?"),
                    post.get("title", "")[:50],
                )
                continue

            enriched = {**post, "opportunity_signals": signals}
            kept.append(enriched)
            logger.info(
                "KEPT [%s] signals=%s — %s",
                post.get("id", "?"),
                signals,
                post.get("title", "")[:60],
            )

        logger.info(
            "Filtering complete — %d/%d posts kept",
            len(kept),
            len(posts),
        )
        return kept

    # ── Rejection checks ──────────────────────────────────────────────

    def _check_rejection(self, post: Dict[str, Any]) -> Optional[str]:
        """Return a rejection reason string, or None if the post passes."""

        # 1. Deleted posts
        if self._is_deleted(post):
            return "deleted"

        # 2. Low-effort posts (body too short)
        if self._is_low_effort(post):
            return "low_effort"

        # 3. Memes
        if self._is_meme(post):
            return "meme"

        # 4. Bot / spam posts
        if self._is_bot(post):
            return "bot_spam"

        # 5. Score below threshold
        if post.get("score", 0) < self.config.minimum_score:
            return f"score_below_{self.config.minimum_score}"

        # 6. Blacklisted subreddit
        if self._is_blacklisted_subreddit(post):
            return "blacklisted_subreddit"

        return None

    def _is_deleted(self, post: Dict[str, Any]) -> bool:
        """Check if the post or its author has been deleted."""
        title = post.get("title", "").strip().lower()
        body = post.get("body", "").strip().lower()
        author = post.get("author", "").strip().lower()

        return (
            title in ("[deleted]", "[removed]")
            or body in ("[deleted]", "[removed]")
            or author in ("[deleted]", "[removed]")
        )

    def _is_low_effort(self, post: Dict[str, Any]) -> bool:
        """Reject posts with body shorter than the configured minimum."""
        body = post.get("body", "")
        return len(body.strip()) < self.config.minimum_body_length

    def _is_meme(self, post: Dict[str, Any]) -> bool:
        """Match title / body against known meme patterns."""
        text = f"{post.get('title', '')} {post.get('body', '')}".lower()
        for pattern in self.config.meme_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _is_bot(self, post: Dict[str, Any]) -> bool:
        """Detect likely bot authors."""
        author = post.get("author", "").lower()
        for pattern in self.config.bot_author_patterns:
            if re.search(pattern, author, re.IGNORECASE):
                return True
        return False

    def _is_blacklisted_subreddit(self, post: Dict[str, Any]) -> bool:
        """Check subreddit against the blacklist (case-insensitive)."""
        sub = post.get("subreddit", "").lower()
        return sub in [s.lower() for s in self.config.blacklisted_subreddits]

    # ── Keep-signal detection ─────────────────────────────────────────

    def _detect_signals(self, post: Dict[str, Any]) -> List[str]:
        """Return a list of opportunity signal labels found in the post."""
        text = f"{post.get('title', '')} {post.get('body', '')}".lower()
        signals: List[str] = []

        if any(kw in text for kw in self.config.help_keywords):
            signals.append("help_request")

        if any(kw in text for kw in self.config.recommendation_keywords):
            signals.append("recommendation_request")

        if any(kw in text for kw in self.config.pain_point_keywords):
            signals.append("pain_point")

        if any(kw in text for kw in self.config.bottleneck_keywords):
            signals.append("bottleneck")

        return signals

    # ── Convenience ───────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<OpportunityFilter min_score={self.config.minimum_score} "
            f"min_body={self.config.minimum_body_length}>"
        )
