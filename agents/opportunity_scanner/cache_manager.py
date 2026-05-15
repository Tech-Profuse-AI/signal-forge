"""JSON-backed exact-deduplication cache for scanner posts."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("signalforge.cache")

_DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(names: tuple[str, ...], default: int) -> int:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or raw.strip() == "":
            continue
        try:
            return int(raw)
        except ValueError:
            logger.warning("Invalid integer for %s=%r; using %d", name, raw, default)
            return default
    return default


class CacheManager:
    """Small JSON cache for exact post IDs and exact cleaned URLs."""

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        cache_filename: str = "seen_posts.json",
        ephemeral: bool = False,
        max_age_days: Optional[int] = None,
    ) -> None:
        env_ephemeral = _env_flag("TEST_MODE") or _env_flag("EPHEMERAL_SCAN_MODE")
        self._ephemeral = ephemeral or env_ephemeral
        self._max_age_days = (
            max_age_days
            if max_age_days is not None
            else _env_int(("CACHE_MAX_AGE_DAYS", "SCANNER_CACHE_MAX_AGE_DAYS"), 7)
        )
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._cache_file = self._cache_dir / cache_filename
        self._cache: Dict[str, str] = {}

        if not self._ephemeral:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            if _env_flag("CLEAR_CACHE_ON_BOOT"):
                self.clear(remove_file=True)
                logger.warning("CLEAR_CACHE_ON_BOOT=true; cleared %s", self._cache_file)
            self._cache = self._load()

        logger.info(
            "CacheManager ready - %d seen keys, file=%s, ephemeral=%s, max_age_days=%d",
            len(self._cache),
            self._cache_file,
            self._ephemeral,
            self._max_age_days,
        )

    def has_seen(self, post_id: str) -> bool:
        """Return True if this exact ID or URL has been marked as seen."""
        if not post_id:
            return False

        seen_at = self._cache.get(post_id)
        if not seen_at:
            return False

        if self._is_expired(seen_at):
            del self._cache[post_id]
            self._save()
            logger.info(
                "CACHE MISS: key=%s reason=expired_cache_entry seen_at=%s",
                post_id,
                seen_at,
            )
            return False

        logger.info(
            "CACHE HIT: key=%s reason=already_seen_cache seen_at=%s",
            post_id,
            seen_at,
        )
        return True

    def mark_seen(self, post_id: str) -> None:
        """Record an exact ID or URL as seen and persist to disk."""
        if post_id and not self.has_seen(post_id):
            self._cache[post_id] = datetime.now(timezone.utc).isoformat()
            self._save()
            logger.debug("Marked as seen: %s", post_id)

    def mark_seen_batch(self, post_ids: list[str]) -> int:
        """Mark multiple exact IDs/URLs. Returns count of newly marked keys."""
        now = datetime.now(timezone.utc).isoformat()
        new_count = 0
        for pid in post_ids:
            if pid and not self.has_seen(pid):
                self._cache[pid] = now
                new_count += 1
        if new_count:
            self._save()
            logger.info("Batch-marked %d new cache keys as seen", new_count)
        return new_count

    def clear(self, *, remove_file: bool = False) -> None:
        """Wipe the cache, optionally deleting the backing file."""
        self._cache.clear()
        if remove_file and not self._ephemeral:
            try:
                self._cache_file.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to remove cache file %s: %s", self._cache_file, exc)
        else:
            self._save()
        logger.info("Cache cleared")

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def max_age_days(self) -> int:
        return self._max_age_days

    @property
    def cache_file(self) -> Path:
        return self._cache_file

    def _load(self) -> Dict[str, str]:
        if not self._cache_file.exists():
            return {}
        try:
            with open(self._cache_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                logger.warning("Cache file %s is not a JSON object; ignoring", self._cache_file)
                return {}

            fresh_entries: Dict[str, str] = {}
            expired_count = 0
            for post_id, seen_at in data.items():
                if isinstance(post_id, str) and isinstance(seen_at, str) and not self._is_expired(seen_at):
                    fresh_entries[post_id] = seen_at
                else:
                    expired_count += 1

            if expired_count:
                logger.info(
                    "Cache startup cleanup pruned %d stale/invalid entries from %s",
                    expired_count,
                    self._cache_file,
                )
                self._cache = fresh_entries
                self._save()
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
            return
        tmp_path = self._cache_file.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, indent=2)
            tmp_path.replace(self._cache_file)
        except OSError as exc:
            logger.error("Failed to save cache: %s", exc)

    def __repr__(self) -> str:
        return f"<CacheManager size={self.size} file='{self._cache_file.name}'>"

