"""
SignalForge Reddit Provider.

Uses PRAW (Python Reddit API Wrapper) to fetch posts from Reddit,
normalise them into a consistent schema, and return them for
downstream processing by the opportunity-scanning pipeline.

Features:
  - Environment-driven authentication
  - Keyword-based post search
  - Normalised output schema
  - Logging, exception handling, and retry support (via tenacity)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger("signalforge.reddit")


class RedditProvider:
    """
    Connects to Reddit via PRAW and fetches posts by keyword.

    All returned posts follow the normalised schema::

        {
            "platform": "reddit",
            "title":     str,
            "body":      str,
            "url":       str,
            "score":     int,
            "author":    str,
            "subreddit": str,
        }
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str = "SignalForge/1.0",
    ) -> None:
        """
        Initialise the Reddit provider.

        Args:
            client_id:     Reddit application client ID.
            client_secret: Reddit application client secret.
            user_agent:    User-agent string for the PRAW client.

        Raises:
            ImportError: If praw is not installed.
            ValueError:  If required credentials are empty.
        """
        try:
            import praw  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "praw is required for RedditProvider. "
                "Install it with: pip install praw"
            ) from exc

        if not client_id or not client_secret:
            raise ValueError(
                "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are required. "
                "Check your .env file."
            )

        self._reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        logger.info(
            "RedditProvider initialised — user_agent: %s", user_agent
        )

    # ── Public API ────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def fetch_posts(
        self,
        keyword: str,
        limit: int = 25,
        sort: str = "relevance",
        time_filter: str = "week",
        subreddit: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search Reddit for posts matching a keyword.

        Args:
            keyword:     Search query string.
            limit:       Maximum number of posts to return.
            sort:        Sort order — 'relevance', 'hot', 'top', 'new'.
            time_filter: Time window — 'hour', 'day', 'week', 'month', 'year', 'all'.
            subreddit:   Optional subreddit name to restrict the search.

        Returns:
            A list of normalised post dictionaries.
        """
        logger.info(
            "Fetching posts — keyword='%s', limit=%d, sort='%s', "
            "time_filter='%s', subreddit=%s",
            keyword,
            limit,
            sort,
            time_filter,
            subreddit or "all",
        )

        try:
            if subreddit:
                search_target = self._reddit.subreddit(subreddit)
            else:
                search_target = self._reddit.subreddit("all")

            submissions = search_target.search(
                keyword,
                sort=sort,
                time_filter=time_filter,
                limit=limit,
            )

            posts: List[Dict[str, Any]] = []
            for submission in submissions:
                posts.append(self._normalise_post(submission))

            logger.info(
                "Fetched %d posts for keyword '%s'", len(posts), keyword
            )
            return posts

        except Exception as exc:
            logger.error(
                "Error fetching posts for keyword '%s': %s", keyword, exc
            )
            raise

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_post(submission) -> Dict[str, Any]:
        """
        Convert a PRAW Submission into the SignalForge normalised schema.
        """
        return {
            "platform": "reddit",
            "title": submission.title,
            "body": submission.selftext or "",
            "url": f"https://www.reddit.com{submission.permalink}",
            "score": submission.score,
            "author": str(submission.author) if submission.author else "[deleted]",
            "subreddit": str(submission.subreddit),
            "created_utc": submission.created_utc,
            "num_comments": submission.num_comments,
            "id": submission.id,
        }

    def __repr__(self) -> str:
        return "<RedditProvider>"
