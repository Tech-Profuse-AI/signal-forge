"""
SignalForge Cache Manager — deduplication cache for seen posts.

Stores post IDs in a JSON file so the scanner never surfaces the
same opportunity twice across runs.

Methods:
  - has_seen(post_id)  → bool
  - mark_seen(post_id) → None
  - clear()            → None
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("signalforge.cache")

_DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"


class CacheManager:
    """
    JSON-backed deduplication cache.

    Schema::

        {
            "post_id_1": "2025-04-30T12:00:00+00:00",
            "post_id_2": "2025-04-30T12:05:00+00:00"
        }
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        cache_filename: str = "seen_posts.json",
        ephemeral: bool = False,
        max_age_days: int = 7,
    ) -> None:
        # ephemeral=True: keep the cache in memory only (never read/write disk).
        # Used by mock mode so fixed mock post IDs are never persisted and
        # every pipeline run always operates against the full mock dataset.
        self._ephemeral = ephemeral
        self._max_age_days = max_age_days
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._cache_file = self._cache_dir / cache_filename
        if not ephemeral:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, str] = {} if ephemeral else self._load()
        logger.info(
            "CacheManager ready — %d seen posts, file=%s, ephemeral=%s",
            len(self._cache), self._cache_file, ephemeral,
        )

    # ── Public API ────────────────────────────────────────────────────

    def has_seen(self, post_id: str) -> bool:
        """Return True if this post ID has been marked as seen."""
        seen_at = self._cache.get(post_id)
        if not seen_at:
            return False
        if self._is_expired(seen_at):
            del self._cache[post_id]
            self._save()
            logger.debug("Expired cache entry pruned on lookup: %s", post_id)
            return False
        return True

    def mark_seen(self, post_id: str) -> None:
        """Record a post ID as seen and persist to disk."""
        if not self.has_seen(post_id):
            self._cache[post_id] = datetime.now(timezone.utc).isoformat()
            self._save()
            logger.debug("Marked as seen: %s", post_id)

    def mark_seen_batch(self, post_ids: list[str]) -> int:
        """Mark multiple post IDs. Returns count of newly marked."""
        now = datetime.now(timezone.utc).isoformat()
        new_count = 0
        for pid in post_ids:
            if not self.has_seen(pid):
                self._cache[pid] = now
                new_count += 1
        if new_count:
            self._save()
            logger.info("Batch-marked %d new posts as seen", new_count)
        return new_count

    def clear(self) -> None:
        """Wipe the cache."""
        self._cache.clear()
        self._save()
        logger.info("Cache cleared")

    @property
    def size(self) -> int:
        return len(self._cache)

    # ── Persistence ───────────────────────────────────────────────────

    def _load(self) -> Dict[str, str]:
        if not self._cache_file.exists():
            return {}
        try:
            with open(self._cache_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {}
            fresh_entries: Dict[str, str] = {}
            for post_id, seen_at in data.items():
                if isinstance(seen_at, str) and not self._is_expired(seen_at):
                    fresh_entries[post_id] = seen_at
            return fresh_entries
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load cache: %s", exc)
            return {}

    def _is_expired(self, seen_at: str) -> bool:
        if self._max_age_days < 0:
            return False
        try:
            seen_dt = datetime.fromisoformat(seen_at)
        except ValueError:
            return True
        if seen_dt.tzinfo is None:
            seen_dt = seen_dt.replace(tzinfo=timezone.utc)
        else:
            seen_dt = seen_dt.astimezone(timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._max_age_days)
        return seen_dt < cutoff

    def _save(self) -> None:
        if self._ephemeral:
            return  # never write to disk in ephemeral (mock) mode
        tmp_path = self._cache_file.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, indent=2)
            tmp_path.replace(self._cache_file)
        except OSError as exc:
            logger.error("Failed to save cache: %s", exc)

    def __repr__(self) -> str:
        return f"<CacheManager size={self.size} file='{self._cache_file.name}'>"
