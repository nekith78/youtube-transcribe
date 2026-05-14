"""Case-insensitive substring filter on a `title` attribute.

Used by --match flag in research and subscribes. Offline, no LLM call.
Whitespace inside the match pattern is preserved (literal match).
"""
from __future__ import annotations

from typing import Iterable, TypeVar

T = TypeVar("T")


def match_titles(candidates: Iterable[T], pattern: str | None) -> list[T]:
    """Return candidates whose `.title` contains `pattern` (case-insensitive).

    Empty/None pattern → return all candidates unchanged (no-op filter).
    """
    if not pattern:
        return list(candidates)
    needle = pattern.lower()
    return [c for c in candidates if needle in (c.title or "").lower()]
