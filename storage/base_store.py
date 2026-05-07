"""
Phase 25 — Storage abstraction layer.

Defines a minimal CRUD surface that can be backed by local JSON files or
remote stores (e.g. Supabase/PostgREST) without coupling business logic
to persistence details.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


class BaseStore(Protocol):
    def save(self, data: Any) -> Any: ...

    def load(self) -> Any: ...

    def update(self, *args: Any, **kwargs: Any) -> Any: ...

    def delete(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class JsonFileStore:
    """
    Simple JSON store wrapper used for backward-compatible fallback.

    The on-disk JSON shape is whatever the caller passes (dict/list/etc).
    """

    path: Path
    default: Any

    def save(self, data: Any) -> Any:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return data

    def load(self) -> Any:
        if not self.path.exists():
            return self._clone_default()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return self._clone_default()
        return raw

    def update(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("JsonFileStore.update is not implemented")

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("JsonFileStore.delete is not implemented")

    def _clone_default(self) -> Any:
        # Default is typically a dict/list; avoid sharing references.
        if isinstance(self.default, dict):
            return dict(self.default)
        if isinstance(self.default, list):
            return list(self.default)
        return self.default


def is_supabase_configured(url: str, key: str) -> bool:
    return bool(str(url or "").strip() and str(key or "").strip())


__all__ = ["BaseStore", "JsonFileStore", "is_supabase_configured"]

