"""Exact deduplication helpers for scanner results."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence


def _clean_key(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def cache_keys_for_post(post: Dict[str, Any]) -> List[str]:
    """Return cache keys for exact post identity: ID and URL only."""
    keys: List[str] = []
    post_id = _clean_key(post.get("id"))
    url = _clean_key(post.get("url"))
    if post_id:
        keys.append(post_id)
    if url and url not in keys:
        keys.append(url)
    return keys


def cache_keys_for_posts(posts: Iterable[Dict[str, Any]]) -> List[str]:
    """Flatten exact cache keys for a batch of posts."""
    keys: List[str] = []
    for post in posts:
        for key in cache_keys_for_post(post):
            if key not in keys:
                keys.append(key)
    return keys


def dedupe_exact_posts(
    posts: Sequence[Dict[str, Any]],
    *,
    cache: Optional[Any] = None,
    logger: logging.Logger,
    stage: str,
    platform: str,
) -> List[Dict[str, Any]]:
    """Remove only exact duplicate IDs, exact duplicate URLs, or cache hits."""
    unique: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    reason_counts: Dict[str, int] = {}

    def skip(post: Dict[str, Any], reason: str, cache_key: str = "") -> None:
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        logger.info(
            "DEDUP SKIP: platform=%s stage=%s id=%s url=%s reason=%s cache_key=%s",
            platform,
            stage,
            _clean_key(post.get("id")) or "-",
            _clean_key(post.get("url")) or "-",
            reason,
            cache_key or "-",
        )

    for post in posts:
        post_id = _clean_key(post.get("id"))
        url = _clean_key(post.get("url"))

        if cache is not None:
            if post_id and cache.has_seen(post_id):
                skip(post, "already_seen_cache_id", post_id)
                continue
            if url and cache.has_seen(url):
                skip(post, "already_seen_cache_url", url)
                continue

        if post_id and post_id in seen_ids:
            skip(post, "duplicate_id_in_batch")
            continue
        if url and url in seen_urls:
            skip(post, "duplicate_url_in_batch")
            continue

        if post_id:
            seen_ids.add(post_id)
        if url:
            seen_urls.add(url)
        unique.append(dict(post))

    removed = len(posts) - len(unique)
    logger.info(
        "DEDUP SUMMARY: platform=%s stage=%s fetched=%d kept=%d removed=%d reasons=%s",
        platform,
        stage,
        len(posts),
        len(unique),
        removed,
        reason_counts or {},
    )
    return unique


def dedupe_unified_exact(
    posts: Sequence[Dict[str, Any]],
    *,
    logger: logging.Logger,
) -> List[Dict[str, Any]]:
    """Exact post-merge dedup across platforms by platform ID and URL."""
    unique: List[Dict[str, Any]] = []
    seen_platform_ids: set[str] = set()
    seen_urls: set[str] = set()
    reason_counts: Dict[str, int] = {}

    def skip(post: Dict[str, Any], reason: str) -> None:
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        logger.info(
            "DEDUP SKIP: platform=%s stage=unified id=%s url=%s reason=%s",
            _clean_key(post.get("platform")) or "-",
            _clean_key(post.get("id")) or "-",
            _clean_key(post.get("url")) or "-",
            reason,
        )

    for post in posts:
        platform = _clean_key(post.get("platform")).lower() or "unknown"
        post_id = _clean_key(post.get("id"))
        url = _clean_key(post.get("url"))
        platform_id = f"{platform}:{post_id}" if post_id else ""

        if platform_id and platform_id in seen_platform_ids:
            skip(post, "duplicate_platform_id_in_batch")
            continue
        if url and url in seen_urls:
            skip(post, "duplicate_url_in_batch")
            continue

        if platform_id:
            seen_platform_ids.add(platform_id)
        if url:
            seen_urls.add(url)
        unique.append(dict(post))

    removed = len(posts) - len(unique)
    logger.info(
        "DEDUP SUMMARY: platform=all stage=unified fetched=%d kept=%d removed=%d reasons=%s",
        len(posts),
        len(unique),
        removed,
        reason_counts or {},
    )
    return unique

