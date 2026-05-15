"""SignalForge opportunity filters."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("signalforge.filters")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class FilterConfig:
    """Tunable thresholds for the opportunity filter."""

    minimum_score: int = 1
    minimum_body_length: int = 25

    blacklisted_subreddits: List[str] = field(default_factory=lambda: [
        "memes",
        "dankmemes",
        "funny",
        "shitposting",
        "FreeKarma4U",
        "FreeKarma4You",
        "KarmaFarming4Pros",
        "test",
        "circlejerk",
    ])

    bot_author_patterns: List[str] = field(default_factory=lambda: [
        r"b[o0]t",
        r"auto[-_]?mod",
        r"spam",
        r"^RemindMeBot$",
        r"^AutoModerator$",
    ])

    help_keywords: List[str] = field(default_factory=lambda: [
        "help",
        "how do i",
        "how to",
        "need advice",
        "stuck on",
        "can someone explain",
        "struggling with",
        "issue with",
        "problem with",
        "question about",
        "confused about",
        "how can i",
    ])

    recommendation_keywords: List[str] = field(default_factory=lambda: [
        "recommend",
        "suggestion",
        "best tool",
        "looking for",
        "any good",
        "what do you use",
        "alternative to",
        "which one",
        "comparison",
        "vs",
        "tool for",
    ])

    pain_point_keywords: List[str] = field(default_factory=lambda: [
        "pain point",
        "frustrat",
        "annoying",
        "broken",
        "doesn't work",
        "hate that",
        "wish there was",
        "rant",
        "vent",
        "unsustainable",
        "killing my",
        "not working",
    ])

    bottleneck_keywords: List[str] = field(default_factory=lambda: [
        "bottleneck",
        "workflow",
        "automat",
        "manual process",
        "takes too long",
        "time consuming",
        "at scale",
        "can't keep up",
        "doesn't scale",
        "inefficient",
        "save time",
        "too much time",
        "repetitive",
    ])

    meme_patterns: List[str] = field(default_factory=lambda: [
        r"^\.+$",
        r"^ok$",
        r"^lmao",
        r"^lol",
        r"free (followers|karma)",
        r"upvote.*(4|for).*upvote",
    ])


class OpportunityFilter:
    """Classify scanner posts as keep or reject with reason logging."""

    def __init__(self, config: Optional[FilterConfig] = None) -> None:
        self.config = config or FilterConfig()
        if config is None and _env_flag("TEST_MODE"):
            self.config.minimum_score = 0
            self.config.minimum_body_length = 10
        logger.info(
            "OpportunityFilter initialised - min_score=%d, min_body=%d",
            self.config.minimum_score,
            self.config.minimum_body_length,
        )

    def filter_opportunities(
        self, posts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Return posts that pass hard rejects and contain a signal."""
        kept: List[Dict[str, Any]] = []

        for post in posts:
            reject_reason = self._check_rejection(post)
            if reject_reason:
                logger.info(
                    "FILTER REJECT: id=%s platform=%s reason=%s title=%s body_len=%d score=%d",
                    post.get("id", "?"),
                    post.get("platform", "?"),
                    reject_reason,
                    post.get("title", "")[:50],
                    len(post.get("body", "")),
                    post.get("score", 0),
                )
                continue

            signals = self._detect_signals(post)
            if not signals:
                logger.info(
                    "FILTER REJECT: id=%s platform=%s reason=low_relevance title=%s body_len=%d score=%d",
                    post.get("id", "?"),
                    post.get("platform", "?"),
                    post.get("title", "")[:50],
                    len(post.get("body", "")),
                    post.get("score", 0),
                )
                continue

            enriched = {**post, "opportunity_signals": signals}
            kept.append(enriched)
            logger.info(
                "FILTER KEEP: id=%s platform=%s signals=%s title=%s",
                post.get("id", "?"),
                post.get("platform", "?"),
                signals,
                post.get("title", "")[:60],
            )

        logger.info(
            "FILTER SUMMARY: input=%d kept=%d rejected=%d",
            len(posts),
            len(kept),
            len(posts) - len(kept),
        )
        return kept

    def _check_rejection(self, post: Dict[str, Any]) -> Optional[str]:
        """Return a rejection reason string, or None if the post passes."""
        if self._is_deleted(post):
            return "deleted"
        if self._is_low_effort(post):
            return "body_too_short"
        if self._is_meme(post):
            return "meme"
        if self._is_bot(post):
            return "bot_spam"
        if not self._passes_score_threshold(post):
            return f"score_below_{self.config.minimum_score}"
        if self._is_blacklisted_subreddit(post):
            return "blacklisted_subreddit"
        return None

    def _is_deleted(self, post: Dict[str, Any]) -> bool:
        title = post.get("title", "").strip().lower()
        body = post.get("body", "").strip().lower()
        author = post.get("author", "").strip().lower()
        return (
            title in ("[deleted]", "[removed]")
            or body in ("[deleted]", "[removed]")
            or author in ("[deleted]", "[removed]")
        )

    def _is_low_effort(self, post: Dict[str, Any]) -> bool:
        body = post.get("body", "")
        if len(body.strip()) >= self.config.minimum_body_length:
            return False

        title = post.get("title", "")
        text = f"{title} {body}".lower()
        signal_keywords = (
            self.config.help_keywords
            + self.config.recommendation_keywords
            + self.config.pain_point_keywords
            + self.config.bottleneck_keywords
        )
        title_is_useful = len(title.strip()) >= 35
        has_signal = any(keyword in text for keyword in signal_keywords)
        return not (title_is_useful and has_signal)

    def _is_meme(self, post: Dict[str, Any]) -> bool:
        text = f"{post.get('title', '')} {post.get('body', '')}".lower()
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in self.config.meme_patterns)

    def _is_bot(self, post: Dict[str, Any]) -> bool:
        author = post.get("author", "").lower()
        return any(
            re.search(pattern, author, re.IGNORECASE)
            for pattern in self.config.bot_author_patterns
        )

    def _is_blacklisted_subreddit(self, post: Dict[str, Any]) -> bool:
        sub = post.get("subreddit", "").lower()
        return sub in [s.lower() for s in self.config.blacklisted_subreddits]

    def _passes_score_threshold(self, post: Dict[str, Any]) -> bool:
        score = post.get("score", 0)
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = 0

        if score >= self.config.minimum_score:
            return True

        body = (post.get("body", "") or "").strip()
        if (
            post.get("platform", "").lower() == "quora"
            and score == 0
            and len(body) > 200
        ):
            logger.info(
                "Applying Quora zero-score fallback [%s] %s - body_len=%d",
                post.get("id", "?"),
                post.get("title", "")[:50],
                len(body),
            )
            return True

        if score == 0 and post.get("platform", "").lower() != "quora" and self._detect_signals(post):
            logger.info(
                "Applying zero-score signal fallback [%s] %s",
                post.get("id", "?"),
                post.get("title", "")[:50],
            )
            return True

        return False

    def _detect_signals(self, post: Dict[str, Any]) -> List[str]:
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

    def __repr__(self) -> str:
        return (
            f"<OpportunityFilter min_score={self.config.minimum_score} "
            f"min_body={self.config.minimum_body_length}>"
        )
