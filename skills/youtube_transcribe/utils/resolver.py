"""Convert any user input (URL / channel / playlist / file / local path)
into a flat list of ResolvedTarget. Does NOT download media."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from skills.youtube_transcribe.utils.downloader import (
    ChannelEntry,
    expand_channel_or_playlist,
    extract_youtube_video_id,
    is_url,
    is_youtube_url,
    probe_input,
)


Source = Literal["inline", "file", "channel", "playlist", "single"]


@dataclass
class ResolvedTarget:
    url: str
    title: str | None
    upload_date: date | None
    duration_sec: int | None
    channel: str | None
    source: Source
    video_id: str | None       # для дедупликации; None для не-YouTube источников


@dataclass
class ResolverFilters:
    limit: int = 10
    # задел под v0.3 (поля присутствуют, в v0.1 не используются):
    since: date | None = None
    until: date | None = None
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None
    include_shorts: bool = True


class CLIInputError(Exception):
    """Hard input error: empty input, missing --from-file, etc. → CLI exit 2."""


class UnresolvableInput(Exception):
    """yt-dlp couldn't resolve one of the inline URLs (private/removed/blocked).
    Caller decides whether to abort or collect into errors.log."""


def parse_from_file(path: Path) -> list[str]:
    """Parse `--from-file` urls.txt: 1 URL per line, # = comment, blanks ignored.
    Trailing inline comments after URL also stripped."""
    if not path.exists():
        raise CLIInputError(f"File not found: {path}")
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # strip trailing inline comments: split on " #"
        if " #" in line:
            line = line.split(" #", 1)[0].rstrip()
        if line:
            urls.append(line)
    return urls


def _channel_entry_to_target(e: ChannelEntry, source: Source) -> ResolvedTarget:
    return ResolvedTarget(
        url=e.url,
        title=e.title,
        upload_date=e.upload_date,
        duration_sec=e.duration_sec,
        channel=e.channel,
        source=source,
        video_id=e.video_id,
    )


def _video_info_to_target(info: dict, url: str, source: Source) -> ResolvedTarget:
    from skills.youtube_transcribe.utils.downloader import _parse_yt_date
    return ResolvedTarget(
        url=url,
        title=info.get("title"),
        upload_date=_parse_yt_date(info.get("upload_date")),
        duration_sec=int(info["duration"]) if info.get("duration") else None,
        channel=info.get("channel") or info.get("uploader"),
        source=source,
        video_id=info.get("id") or (extract_youtube_video_id(url) if is_youtube_url(url) else None),
    )


def _local_to_target(path_str: str) -> ResolvedTarget:
    return ResolvedTarget(
        url=path_str, title=None, upload_date=None, duration_sec=None,
        channel=None, source="single", video_id=None,
    )


def resolve(
    inputs: list[str],
    from_file: Path | None,
    filters: ResolverFilters,
) -> list[ResolvedTarget]:
    """Expand inputs into a flat list of ResolvedTarget. No media download."""
    raw: list[tuple[str, Source]] = []
    for u in inputs:
        raw.append((u, "inline"))
    if from_file is not None:
        for u in parse_from_file(from_file):
            raw.append((u, "file"))
    if not raw:
        raise CLIInputError("No inputs given. Pass URL(s) or --from-file PATH.")

    targets: list[ResolvedTarget] = []
    seen_video_ids: set[str] = set()

    for url, src in raw:
        try:
            kind, info = probe_input(url)
        except Exception as e:
            raise UnresolvableInput(f"{url}: {e}") from e

        if kind == "local":
            t = _local_to_target(info["path"])
            targets.append(t)
            continue

        if kind == "video":
            t = _video_info_to_target(info, url, source=src)
            if t.video_id and t.video_id in seen_video_ids:
                continue   # dedup: keep first occurrence
            if t.video_id:
                seen_video_ids.add(t.video_id)
            targets.append(t)
            continue

        # kind == "playlist" → expand and apply limit per source
        entries = expand_channel_or_playlist(url, limit=filters.limit)
        playlist_source: Source = "channel"  # we don't strictly distinguish
        for e in entries:
            t = _channel_entry_to_target(e, source=playlist_source)
            if t.video_id and t.video_id in seen_video_ids:
                continue
            if t.video_id:
                seen_video_ids.add(t.video_id)
            targets.append(t)

    # In v0.1 the only filter applied is `limit` (handled per-source in expand_*).
    # Reserved fields `since/until/min_duration/max_duration/include_shorts`
    # are placeholders for v0.3 — see spec extension §5 / §9.

    return targets
