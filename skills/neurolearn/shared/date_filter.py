"""Parse --days / --since / --until into a date window, and test membership.

Used by research and subscribes commands. Returns None when caller
provided no filter (caller handles default, e.g. stateful subscribes).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class DateWindow:
    """Inclusive date window [start, end]."""
    start: date
    end: date


def parse_window(
    *,
    days: int | None,
    since: date | None,
    until: date | None,
    now: date,
) -> DateWindow | None:
    """Return a DateWindow or None if no filter given.

    Raises ValueError on mutex violations and invalid inputs.
    """
    if days is not None and (since is not None or until is not None):
        raise ValueError("--days and --since/--until are mutually exclusive")

    if days is not None:
        if days <= 0:
            raise ValueError("days must be positive")
        return DateWindow(start=now - timedelta(days=days), end=now)

    if since is None and until is None:
        return None

    if since is None and until is not None:
        raise ValueError("--until requires --since")

    end = until if until is not None else now
    if since > end:
        raise ValueError("--since must be before --until")
    return DateWindow(start=since, end=end)


def in_window(value: date | datetime, window: DateWindow) -> bool:
    """Inclusive membership test. Accepts date or datetime."""
    d = value.date() if isinstance(value, datetime) else value
    return window.start <= d <= window.end
