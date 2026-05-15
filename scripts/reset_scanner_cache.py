#!/usr/bin/env python3
"""Reset SignalForge scanner cache files."""

from __future__ import annotations

import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = PROJECT_ROOT / "outputs" / ".scanner_cache"
DEFAULT_FILES = (
    "seen_posts.json",
    "seen_quora_posts.json",
    "seen_medium_posts.json",
)


def reset_cache(cache_dir: Path, filenames: tuple[str, ...]) -> int:
    removed = 0
    cache_dir.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        path = cache_dir / filename
        if path.exists():
            path.unlink()
            removed += 1
            print(f"removed {path}")
        else:
            print(f"missing  {path}")
    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset SignalForge scanner caches.")
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help="Scanner cache directory. Defaults to outputs/.scanner_cache.",
    )
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        default=None,
        help="Specific cache filename to remove. Can be repeated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    filenames = tuple(args.files) if args.files else DEFAULT_FILES
    removed = reset_cache(Path(args.cache_dir), filenames)
    print(f"scanner cache reset complete: removed={removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

