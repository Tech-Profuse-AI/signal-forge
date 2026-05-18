"""Production URL normalization and validation for SignalForge.

The scanner layer sees URLs from RSS feeds, search results, redirect wrappers,
API clients, mock fixtures, and persisted review queue records.  This module is
the single authority for turning those inputs into frontend-safe opportunity
links.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Tuple
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

logger = logging.getLogger("signalforge.url_validator")

UrlResult = Tuple[str, bool]

_REDDIT_ENTITY_PREFIX_RE = re.compile(r"^t[12345]_", re.IGNORECASE)
_REDDIT_POST_PREFIX_RE = re.compile(r"^t3_", re.IGNORECASE)
_REDDIT_ENTITY_PATH_RE = re.compile(r"^/t[12345]_[a-z0-9]+/?$", re.IGNORECASE)
_REDDIT_COMMENT_ID_RE = re.compile(r"^[a-z0-9]+$", re.IGNORECASE)

_COMMON_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_name",
    "fbclid",
    "gclid",
    "msclkid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "ref_source",
    "referrer",
    "source",
    "share",
    "share_id",
    "tracking",
    "trk",
    "sk",
}

_REDDIT_TRACKING_PARAMS = _COMMON_TRACKING_PARAMS | {
    "context",
    "rdt",
    "$deep_link",
    "correlation_id",
    "ref_campaign",
}

_QUORA_TRACKING_PARAMS = _COMMON_TRACKING_PARAMS | {
    "ch",
    "oid",
    "srid",
    "st",
}

_MEDIUM_TRACKING_PARAMS = _COMMON_TRACKING_PARAMS | {
    "gi",
    "postpublishedtype",
    "readingcollectionid",
    "responsesopen",
}

_REDIRECT_PARAM_NAMES = (
    "url",
    "u",
    "q",
    "target",
    "to",
    "link",
    "redirect",
    "redirect_url",
    "destination",
    "continue",
    "uddg",
)

_REDIRECT_HOST_HINTS = (
    "duckduckgo.",
    "google.",
    "bing.",
    "out.reddit.com",
    "l.facebook.com",
    "t.co",
    "lnkd.in",
)

_QUORA_REJECT_PREFIXES = (
    "/about",
    "/answer",
    "/contact",
    "/digest",
    "/following",
    "/notifications",
    "/profile/",
    "/q/",
    "/search",
    "/sitemap",
    "/spaces",
    "/topic/",
)

_MEDIUM_REJECT_PREFIXES = (
    "/about",
    "/archive",
    "/feed",
    "/followers",
    "/following",
    "/jobs",
    "/latest",
    "/m/signin",
    "/membership",
    "/me/",
    "/policy",
    "/search",
    "/tag/",
    "/topic/",
)

_MEDIUM_NON_ARTICLE_SEGMENTS = {
    "about",
    "archive",
    "feed",
    "followers",
    "following",
    "jobs",
    "latest",
    "lists",
    "m",
    "me",
    "membership",
    "policy",
    "search",
    "tag",
    "topic",
}


def _clean_raw_url(value: object) -> str:
    if value is None or not isinstance(value, str):
        return ""
    url = html.unescape(value).strip().strip("\"'")
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    return url


def _safe_parse(url: str):
    try:
        return urlparse(url)
    except Exception:
        return None


def _is_http_url(url: str) -> bool:
    parsed = _safe_parse(url)
    return bool(parsed and parsed.scheme in {"http", "https"} and parsed.netloc)


def _unwrap_redirect(raw_url: str, *, max_depth: int = 4) -> str:
    """Extract the destination from common redirect/search wrapper URLs."""
    url = _clean_raw_url(raw_url)
    seen = set()

    for _ in range(max_depth):
        if not url or url in seen:
            return url
        seen.add(url)

        parsed = _safe_parse(url)
        if not parsed or not parsed.query:
            return url

        host = parsed.netloc.lower()
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        should_probe = any(hint in host for hint in _REDIRECT_HOST_HINTS)
        should_probe = should_probe or any(name in params for name in _REDIRECT_PARAM_NAMES)
        if not should_probe:
            return url

        next_url = ""
        for name in _REDIRECT_PARAM_NAMES:
            candidate = params.get(name, "")
            candidate = unquote(candidate).strip()
            if _is_http_url(candidate):
                next_url = candidate
                break

        if not next_url:
            return url
        url = next_url

    return url


def _canonical_netloc(netloc: str) -> str:
    return netloc.lower().split("@")[-1].split(":")[0].strip()


def _clean_path(path: str) -> str:
    path = unquote(path or "")
    path = re.sub(r"/{2,}", "/", path)
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def _encode_path(path: str) -> str:
    return quote(path, safe="/:@~!$&'()*+,;=-._")


def _strip_trailing_slash(url: str) -> str:
    if url == "https://www.reddit.com/":
        return url
    return url.rstrip("/")


def _query_without_tracking(query: str, blocked_params: set[str]) -> str:
    if not query:
        return ""
    kept = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key.lower() in blocked_params or key.lower().startswith("utm_"):
            continue
        kept.append((key, value))
    return urlencode(kept, doseq=True)


def normalize_reddit_url(url: object) -> UrlResult:
    raw = _unwrap_redirect(_clean_raw_url(url))
    if not raw:
        return "", False

    parsed = _safe_parse(re.sub(r"^http://", "https://", raw, flags=re.IGNORECASE))
    if not parsed or parsed.scheme not in {"http", "https"}:
        return raw, False

    netloc = _canonical_netloc(parsed.netloc)
    path = _clean_path(parsed.path).replace("/amp/", "/")

    if netloc == "redd.it":
        post_id = path.strip("/").split("/", 1)[0]
        if not _REDDIT_COMMENT_ID_RE.fullmatch(post_id or ""):
            return raw, False
        return f"https://www.reddit.com/comments/{post_id.lower()}", True

    if netloc in {"reddit.com", "old.reddit.com", "np.reddit.com", "new.reddit.com", "m.reddit.com"}:
        netloc = "www.reddit.com"

    if netloc != "www.reddit.com":
        return raw, False

    lowered_path = path.lower()
    if _REDDIT_ENTITY_PATH_RE.match(path):
        logger.info("REJECTED Reddit entity URL: %s", raw)
        return _strip_trailing_slash(urlunparse(("https", netloc, path, "", "", ""))), False

    if lowered_path.startswith(("/user/", "/u/")):
        return _strip_trailing_slash(urlunparse(("https", netloc, path, "", "", ""))), False

    if re.fullmatch(r"/r/[^/]+/?", path, re.IGNORECASE):
        return _strip_trailing_slash(urlunparse(("https", netloc, path, "", "", ""))), False

    parts = [part for part in path.split("/") if part]
    canonical_path = ""
    if len(parts) >= 2 and parts[0].lower() == "comments":
        post_id = parts[1]
        if not _REDDIT_COMMENT_ID_RE.fullmatch(post_id):
            return raw, False
        canonical_path = f"/comments/{post_id.lower()}"
    elif len(parts) >= 4 and parts[0].lower() == "r" and parts[2].lower() == "comments":
        subreddit = parts[1]
        post_id = parts[3]
        if not subreddit or not _REDDIT_COMMENT_ID_RE.fullmatch(post_id):
            return raw, False
        slug = parts[4] if len(parts) >= 5 else ""
        canonical_path = f"/r/{subreddit}/comments/{post_id.lower()}"
        if slug:
            canonical_path = f"{canonical_path}/{slug}"
    else:
        return _strip_trailing_slash(urlunparse(("https", netloc, path, "", "", ""))), False

    normalised = urlunparse(("https", netloc, _encode_path(canonical_path), "", "", ""))
    return _strip_trailing_slash(normalised), True


def _is_quora_question_slug(slug: str) -> bool:
    if not slug or len(slug) < 5:
        return False
    if slug.lower().startswith("deleted-question"):
        return False
    if "/" in slug or "." in slug:
        return False
    return "-" in slug


def normalize_quora_url(url: object) -> UrlResult:
    raw = _unwrap_redirect(_clean_raw_url(url))
    if not raw:
        return "", False

    parsed = _safe_parse(re.sub(r"^http://", "https://", raw, flags=re.IGNORECASE))
    if not parsed or parsed.scheme not in {"http", "https"}:
        return raw, False

    netloc = _canonical_netloc(parsed.netloc)
    if netloc == "quora.com":
        netloc = "www.quora.com"
    if netloc != "www.quora.com":
        return raw, False

    path = _clean_path(parsed.path)
    lowered_path = path.lower()
    if any(lowered_path == prefix.rstrip("/") or lowered_path.startswith(prefix) for prefix in _QUORA_REJECT_PREFIXES):
        return _strip_trailing_slash(urlunparse(("https", netloc, path, "", "", ""))), False

    parts = [part for part in path.split("/") if part]
    if not parts:
        return f"https://{netloc}", False

    question_slug = parts[0]
    if not _is_quora_question_slug(question_slug):
        return _strip_trailing_slash(urlunparse(("https", netloc, path, "", "", ""))), False

    # Quora answer URLs are usable, but the opportunity source should open the
    # stable question page.  The answer body is still captured separately.
    canonical_path = f"/{question_slug}"
    normalised = urlunparse(("https", netloc, _encode_path(canonical_path), "", "", ""))
    return _strip_trailing_slash(normalised), True


def _medium_custom_domain_candidate(netloc: str, path: str) -> bool:
    if netloc.endswith("medium.com"):
        return False
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0].startswith("@"):
        return _is_medium_article_slug(parts[1])
    if len(parts) >= 2 and parts[0].lower() == "p":
        return bool(parts[1])
    return bool(parts and _is_medium_article_slug(parts[-1]))


def _is_medium_article_slug(slug: str) -> bool:
    candidate = (slug or "").strip("/")
    if not candidate:
        return False
    lowered = candidate.lower()
    if lowered in _MEDIUM_NON_ARTICLE_SEGMENTS:
        return False
    if "." in candidate:
        return False
    if "-" in candidate and len(candidate) >= 8:
        return True
    return bool(re.search(r"[a-z0-9]{6,}$", candidate, re.IGNORECASE))


def normalize_medium_url(url: object) -> UrlResult:
    raw = _unwrap_redirect(_clean_raw_url(url))
    if not raw:
        return "", False

    parsed = _safe_parse(re.sub(r"^http://", "https://", raw, flags=re.IGNORECASE))
    if not parsed or parsed.scheme not in {"http", "https"}:
        return raw, False

    netloc = _canonical_netloc(parsed.netloc)
    if netloc == "www.medium.com":
        netloc = "medium.com"

    path = _clean_path(parsed.path)
    lowered_path = path.lower()
    if any(lowered_path == prefix.rstrip("/") or lowered_path.startswith(prefix) for prefix in _MEDIUM_REJECT_PREFIXES):
        return _strip_trailing_slash(urlunparse(("https", netloc, path, "", "", ""))), False

    parts = [part for part in path.split("/") if part]
    if not parts:
        return f"https://{netloc}", False

    valid = False
    if netloc == "medium.com" or netloc.endswith(".medium.com"):
        if parts[0].startswith("@"):
            valid = len(parts) >= 2 and _is_medium_article_slug(parts[1])
        elif parts[0].lower() == "p":
            valid = len(parts) >= 2 and bool(parts[1])
        elif netloc == "medium.com":
            valid = len(parts) >= 2 and _is_medium_article_slug(parts[-1])
        else:
            valid = _is_medium_article_slug(parts[-1])
    else:
        valid = _medium_custom_domain_candidate(netloc, path)

    normalised = urlunparse(("https", netloc, _encode_path(path), "", "", ""))
    return _strip_trailing_slash(normalised), valid


def normalize_url(url: object, platform: str) -> UrlResult:
    """Normalize and validate a platform URL.

    Returns:
        A tuple of ``(normalized_url, is_valid)``.  Invalid URLs may return a
        cleaned display value for logging, but callers must respect
        ``is_valid=False`` and keep the URL out of public opportunity payloads.
    """
    platform_key = str(platform or "").strip().lower()
    if platform_key == "reddit":
        return normalize_reddit_url(url)
    if platform_key == "quora":
        return normalize_quora_url(url)
    if platform_key == "medium":
        return normalize_medium_url(url)

    raw = _unwrap_redirect(_clean_raw_url(url))
    if not raw:
        return "", False
    parsed = _safe_parse(re.sub(r"^http://", "https://", raw, flags=re.IGNORECASE))
    if not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw, False
    query = _query_without_tracking(parsed.query, _COMMON_TRACKING_PARAMS)
    normalised = urlunparse(("https", _canonical_netloc(parsed.netloc), _encode_path(_clean_path(parsed.path)), "", query, ""))
    return _strip_trailing_slash(normalised), True


def clean_url(url: object, platform: str) -> str:
    """Backward-compatible cleaner returning only the normalized URL string."""
    cleaned, _valid = normalize_url(url, platform)
    return cleaned


def is_valid_post_url(url: object, platform: str) -> bool:
    """Return True only when ``url`` is a usable post/article URL."""
    _cleaned, valid = normalize_url(url, platform)
    return valid


def reconstruct_reddit_url(entry_id: object) -> str:
    """Build a canonical Reddit post URL from a ``t3_`` or bare post ID."""
    if not entry_id or not isinstance(entry_id, str):
        return ""

    entry_id = entry_id.strip()
    if _REDDIT_ENTITY_PREFIX_RE.match(entry_id):
        if not _REDDIT_POST_PREFIX_RE.match(entry_id):
            logger.info(
                "REJECTED non-post Reddit entity ID: %s (only t3_ post IDs accepted)",
                entry_id,
            )
            return ""
        post_id = entry_id[3:]
    elif "_" in entry_id:
        logger.debug("REJECTED unknown entity ID format: %s", entry_id)
        return ""
    else:
        post_id = entry_id

    if not post_id or not _REDDIT_COMMENT_ID_RE.fullmatch(post_id):
        return ""

    return f"https://www.reddit.com/comments/{post_id.lower()}"


def validate_and_clean(url: object, platform: str) -> UrlResult:
    """Backward-compatible alias for the centralized normalizer."""
    return normalize_url(url, platform)


def is_valid_reddit_entry_id(entry_id: object) -> bool:
    """Return True if an RSS entry id can represent a Reddit post."""
    if not entry_id or not isinstance(entry_id, str):
        return False
    entry_id = entry_id.strip()
    if _REDDIT_ENTITY_PREFIX_RE.match(entry_id):
        return bool(_REDDIT_POST_PREFIX_RE.match(entry_id))
    return True


__all__ = [
    "clean_url",
    "is_valid_post_url",
    "is_valid_reddit_entry_id",
    "normalize_medium_url",
    "normalize_quora_url",
    "normalize_reddit_url",
    "normalize_url",
    "reconstruct_reddit_url",
    "validate_and_clean",
]
