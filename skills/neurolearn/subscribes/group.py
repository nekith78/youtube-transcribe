"""Channel grouping helpers — filter and listing for subscribes.

Groups are user-defined string tags on Channel.group. Special keyword
"ungrouped" selects channels with group=None. None as filter input
returns the full list (no-op).
"""
from __future__ import annotations

from skills.neurolearn.subscribes.store import Channel


def filter_by_group(channels: list[Channel], group: str | None) -> list[Channel]:
    """Return channels matching the given group.

    - None → all channels (no filter)
    - "ungrouped" → channels with group=None
    - other → channels whose group equals the input
    """
    if group is None:
        return list(channels)
    if group == "ungrouped":
        return [c for c in channels if c.group is None]
    return [c for c in channels if c.group == group]


def list_groups(channels: list[Channel]) -> list[str]:
    """Return sorted unique non-None group names."""
    return sorted({c.group for c in channels if c.group is not None})
