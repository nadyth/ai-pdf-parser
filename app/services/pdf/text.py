"""Text sanitisation helpers.

Postgres TEXT and JSONB columns reject the NUL byte (`\\x00`). pdfplumber
sometimes emits NULs for unmapped glyphs in non-Latin scripts (Hindi, Tamil,
CJK, etc.); LLMs can occasionally echo them back. We strip them everywhere
before persisting.
"""

from __future__ import annotations

from typing import Any


def clean_text(s: str | None) -> str | None:
    if s is None:
        return None
    if "\x00" not in s:
        return s
    return s.replace("\x00", "")


def clean_jsonable(value: Any) -> Any:
    """Recursively strip NULs from any strings inside a JSON-ish structure."""
    if value is None:
        return None
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return [clean_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {clean_text(k) if isinstance(k, str) else k: clean_jsonable(v) for k, v in value.items()}
    return value
