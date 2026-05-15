"""
SignalForge URL Validator & Cleaner.

Reusable utilities for cleaning, normalising, and validating post URLs
across all supported platforms (Reddit, Quora, Medium).
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

logger = logging.getLogger("signalforge.url_validator")

# Reddit fullname type prefixes
# t1_ = comment, t2_ = account, t3_ = post/link, t4_ = message, t5_ = subreddit
_REDDIT_ENTITY_PREFIX_RE = re.compile(r"^t[12345]_", re.IGNORECASE)
_REDDIT_POST_PREFIX_RE = re.compile(r"^t3_", re.IGNORECASE)
_REDDIT_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_source", "share_id", "context", "rdt", "$deep_link",
    "correlation_id", "ref_campaign",
}


def clean_url(url: str, platform: str) -> str:
    """Clean and normalise a URL for the given platform.

    Strips tracking parameters, forces HTTPS, and applies
    platform-specific transformations.
    """
    if not url or not isinstance(url, str):
        return ""

    url = url.strip()

    # Force HTTPS
    url = re.sub(r"^http://", "https://", url)

    # Strip fragment
    url = url.split("#")[0]

    # --- Platform-specific cleaning ---

    if platform == "reddit":
        # Strip all query params (Reddit URLs don't need them)
        url = url.split("?")[0]

        # Normalise old.reddit.com and redd.it
        url = url.replace("old.reddit.com", "www.reddit.com")
        url = url.replace("np.reddit.com", "www.reddit.com")

        # Remove /amp/ segments
        url = url.replace("/amp/", "/")
        url = re.sub(r"\?amp\b[^&]*", "", url)

        # Ensure www. prefix for consistency
        url = re.sub(r"https://reddit\.com/", "https://www.reddit.com/", url)

    elif platform == "quora":
        # Strip tracking params
        url = url.split("?")[0]

        # Force www.quora.com
        url = re.sub(
            r"https://quora\.com/",
            "https://www.quora.com/",
            url,
        )

    elif platform == "medium":
        # Strip all query params (Medium adds ?source= tracking)
        url = url.split("?")[0]

    # Strip trailing slashes
    url = url.rstrip("/")

    return url


def is_valid_post_url(url: str, platform: str) -> bool:
    """Return True only if URL points to an actual post on the platform."""
    if not url or len(url) < 20:
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if not parsed.scheme or not parsed.netloc:
        return False

    if platform == "reddit":
        # Must be a www.reddit.com post URL with /comments/
        if parsed.netloc not in ("www.reddit.com", "reddit.com"):
            return False

        path = parsed.path

        # Reject any Reddit entity URLs like /t5_XXXXX, /t3_XXXXX, /t1_XXXXX
        # These are fullname identifiers, NOT permalinks
        if re.match(r"/t[12345]_[a-z0-9]+", path, re.IGNORECASE):
            return False

        # Reject /user/ profile URLs
        if path.startswith("/user/") or path.startswith("/u/"):
            return False

        # Must contain /comments/ to be an actual post
        if "/comments/" not in path:
            return False

        # Reject bare subreddit URLs /r/name with no post ID
        if re.match(r"^/r/[^/]+/?$", path):
            return False

        return True

    if platform == "quora":
        # Must be www.quora.com, NOT a subdomain like indianpoliticsnculture.quora.com
        if parsed.netloc != "www.quora.com":
            return False

        path = parsed.path
        # Reject profile, topic, news, search, sitemap pages
        rejected_prefixes = (
            "/profile/", "/topic/", "/news/", "/search/", "/sitemap",
        )
        if any(path.startswith(p) for p in rejected_prefixes):
            return False

        # Must have a meaningful path (a question slug)
        if len(path) <= 5:
            return False

        return True

    if platform == "medium":
        # Must be medium.com or a custom domain with article indicators
        if "medium.com" in parsed.netloc:
            # Reject bare https://medium.com with no article path
            if len(parsed.path) <= 1:
                return False
            return True

        # Custom domain articles (e.g., towardsdatascience.com/@user/...)
        if "/@" in url or "/p/" in url:
            return len(url) > 25

        return False

    # Unknown platform — accept by default
    return True


def reconstruct_reddit_url(entry_id: str) -> str:
    """Build a canonical Reddit URL from a t3_POSTID entry ID.

    Only accepts ``t3_`` (post/link) identifiers.  All other Reddit
    fullname types (``t1_`` comment, ``t2_`` account, ``t4_`` message,
    ``t5_`` subreddit) are rejected because they do not represent
    individual post permalinks.

    Returns:
        A ``https://www.reddit.com/comments/{post_id}`` URL for valid
        ``t3_`` IDs, or an empty string for anything else.
    """
    if not entry_id or not isinstance(entry_id, str):
        return ""

    entry_id = entry_id.strip()

    # Reject non-post Reddit entity IDs (t1_, t2_, t4_, t5_)
    if _REDDIT_ENTITY_PREFIX_RE.match(entry_id):
        if not _REDDIT_POST_PREFIX_RE.match(entry_id):
            logger.info(
                "REJECTED non-post Reddit entity ID: %s (only t3_ post IDs accepted)",
                entry_id,
            )
            return ""
        # It's a valid t3_ post ID — extract the ID portion
        post_id = entry_id[3:]  # strip "t3_"
    elif "_" in entry_id:
        # Unknown prefix with underscore — reject for safety
        logger.debug("REJECTED unknown entity ID format: %s", entry_id)
        return ""
    else:
        # Bare ID (no prefix) — accept as-is
        post_id = entry_id

    if not post_id or not re.match(r"^[a-z0-9]+$", post_id, re.IGNORECASE):
        return ""

    return f"https://www.reddit.com/comments/{post_id}"


def normalize_reddit_url(url: str) -> Tuple[str, bool]:
    """Centralised Reddit URL normalisation and validation.

    Responsibilities:
      - Strip tracking params (utm_*, ref, share_id, etc.)
      - Normalise domain to ``www.reddit.com``
      - Remove /amp/ segments
      - Validate permalink structure (must contain ``/comments/``)
      - Reject invalid entities (t5_, user profiles, bare subreddit URLs)

    Args:
        url: Raw URL string.

    Returns:
        ``(normalised_url, is_valid)`` tuple.
    """
    if not url or not isinstance(url, str):
        return "", False

    url = url.strip()

    # Force HTTPS
    url = re.sub(r"^http://", "https://", url)

    # Parse
    try:
        parsed = urlparse(url)
    except Exception:
        return url, False

    # Must be a reddit.com domain
    netloc = parsed.netloc.lower()
    if "reddit.com" not in netloc and netloc != "redd.it":
        return url, False

    # Normalise domain
    netloc = re.sub(r"^(old|np|new|i|m|amp)\.reddit\.com$", "www.reddit.com", netloc)
    if netloc == "reddit.com":
        netloc = "www.reddit.com"

    # Clean path
    path = parsed.path
    path = path.replace("/amp/", "/")
    path = re.sub(r"//+", "/", path)  # collapse double slashes

    # Strip tracking query params
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        cleaned_params = {
            k: v for k, v in params.items()
            if k.lower() not in _REDDIT_TRACKING_PARAMS
        }
        query = urlencode(cleaned_params, doseq=True) if cleaned_params else ""
    else:
        query = ""

    # Reconstruct (drop fragment)
    normalised = urlunparse(("https", netloc, path, "", query, ""))
    normalised = normalised.rstrip("/")

    # Validate
    is_valid = is_valid_post_url(normalised, "reddit")

    if not is_valid:
        logger.info("REJECTED invalid Reddit URL: %s", url)

    return normalised, is_valid


def validate_and_clean(url: str, platform: str) -> Tuple[str, bool]:
    """Clean a URL and validate it.

    Returns:
        (cleaned_url, is_valid) tuple.
    """
    if platform == "reddit":
        return normalize_reddit_url(url)
    cleaned = clean_url(url, platform)
    valid = is_valid_post_url(cleaned, platform)
    return cleaned, valid


def is_valid_reddit_entry_id(entry_id: str) -> bool:
    """Return True if the entry_id represents a Reddit post (t3_).

    Returns False for subreddit IDs (t5_), comment IDs (t1_), etc.
    """
    if not entry_id or not isinstance(entry_id, str):
        return False
    entry_id = entry_id.strip()
    # If it has a tN_ prefix, it must be t3_
    if _REDDIT_ENTITY_PREFIX_RE.match(entry_id):
        return bool(_REDDIT_POST_PREFIX_RE.match(entry_id))
    # Bare ID or URL — accept
    return True


__all__ = [
    "clean_url",
    "is_valid_post_url",
    "is_valid_reddit_entry_id",
    "normalize_reddit_url",
    "reconstruct_reddit_url",
    "validate_and_clean",
]
