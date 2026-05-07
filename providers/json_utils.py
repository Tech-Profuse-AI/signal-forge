"""
SignalForge JSON parsing utilities for LLM output.

Handles the common failure modes when parsing JSON from Gemini / LLM responses:
  - Markdown code fences (```json ... ```)
  - Leading/trailing junk text around a JSON object
  - Truncated responses (best-effort extraction)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("signalforge.json_utils")


def extract_json(raw: str) -> Dict[str, Any]:
    """
    Extract and parse the first valid JSON object from an LLM response.

    Strategy (in order):
      1. Strip markdown code fences and try json.loads
      2. Find the first { ... } substring and try json.loads
      3. Raise ValueError if nothing works

    Args:
        raw: The raw LLM output string.

    Returns:
        Parsed dict.

    Raises:
        ValueError: If no valid JSON object can be extracted.
    """
    if not raw or not raw.strip():
        raise ValueError("Empty LLM response")

    # 1. Strip code fences and try direct parse
    cleaned = strip_code_fences(raw)
    parsed = _try_parse(cleaned)
    if parsed is not None:
        return parsed

    # 2. Extract first { ... } block (greedy from first { to last })
    extracted = _extract_json_block(cleaned)
    if extracted:
        parsed = _try_parse(extracted)
        if parsed is not None:
            return parsed

    # 3. Try the original raw text as a last resort
    extracted = _extract_json_block(raw)
    if extracted:
        parsed = _try_parse(extracted)
        if parsed is not None:
            return parsed

    raise ValueError(f"No valid JSON object found in LLM response: {raw[:200]}")


def strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers that LLMs sometimes add."""
    text = text.strip()
    # Remove opening fence (```json or ``` at start)
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    # Remove closing fence (``` at end)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _extract_json_block(text: str) -> Optional[str]:
    """Find the first balanced { ... } block in text."""
    start = text.find("{")
    if start == -1:
        return None

    # Find the last } after the first {
    end = text.rfind("}")
    if end == -1 or end <= start:
        return None

    return text[start:end + 1]


def _try_parse(text: str) -> Optional[Dict[str, Any]]:
    """Try to parse text as JSON dict. Returns None on failure."""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        return None
    except (json.JSONDecodeError, ValueError):
        return None
