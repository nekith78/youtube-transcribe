"""Per-channel last-seen tracking for stateful incremental subscribes update.

State is stored in subscribes.toml itself (fields `last_seen_video_id`
and `last_seen_published` per channel). Update happens only after a
successful default-mode run; user-supplied --days/--since overrides
must NOT call this (override = ad-hoc, doesn't disturb incremental).
"""
from __future__ import annotations

from pathlib import Path

from skills.neurolearn.subscribes.store import (
    Channel, load_subscribes, save_subscribes,
)


def needs_initial_run(channel: Channel) -> bool:
    """True if channel has no recorded state — first run needs explicit window."""
    return channel.last_seen_video_id is None


def channels_without_state(channels: list[Channel]) -> list[Channel]:
    """Subset of channels that have never been processed."""
    return [c for c in channels if needs_initial_run(c)]


def update_last_seen(
    path: Path, channel_id: str, video_id: str, published: str,
) -> None:
    """Write `last_seen_*` fields for a channel. No-op if channel missing."""
    channels = load_subscribes(path)
    for c in channels:
        if c.channel_id == channel_id:
            c.last_seen_video_id = video_id
            c.last_seen_published = published
            save_subscribes(path, channels)
            return
    # Silent no-op on unknown channel (defensive)
