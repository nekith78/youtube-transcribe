"""Convert any user input (URL / channel / playlist / file / local path)
into a flat list of ResolvedTarget. Does NOT download media."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal


# Probe yt-dlp metadata in parallel for batched URLs. yt-dlp init is
# ~1-2s per process; on `batch --from-file urls.txt` with 10 URLs that
# can save 10-20s of sequential probe overhead. Cap conservatively to
# avoid hitting per-IP rate limits or saturating the network.
_MAX_PROBE_WORKERS = 4

from skills.neurolearn.utils.downloader import (
    ChannelEntry,
    expand_channel_or_playlist,
    extract_youtube_video_id,
    is_url,
    is_youtube_url,
    probe_input,
)


Source = Literal["inline", "file", "channel", "playlist", "single", "search"]


@dataclass
class ResolvedTarget:
    url: str
    title: str | None
    upload_date: date | None
    duration_sec: int | None
    channel: str | None
    source: Source
    video_id: str | None       # for dedup; None for non-YouTube sources
    # Optional: which language search produced this target (multi-lang research).
    # Set by research.pipeline when converting SearchCandidate → ResolvedTarget;
    # None for everything else. Lands in manifest.json for downstream filtering.
    source_language: str | None = None


@dataclass
class ResolverFilters:
    limit: int = 10
    since: date | None = None
    until: date | None = None
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None
    include_shorts: bool = True
    # v0.3 #4: search-by-tags. When set, resolve() runs a YouTube search
    # via yt-dlp `ytsearchN:query` instead of (or in addition to) `inputs`.
    search_query: str | None = None


class CLIInputError(Exception):
    """Hard input error: empty input, missing --from-file, etc. → CLI exit 2."""


class UnresolvableInput(Exception):
    """yt-dlp couldn't resolve one of the inline URLs (private/removed/blocked).
    Kept for backward-compat reference; no longer raised by resolve()."""


@dataclass
class ResolveFailure:
    """A per-URL probe failure — spec extension §5 collect-and-continue."""
    url: str
    error: str      # str(exception) or human description
    source: Source  # "inline" or "file"


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
    from skills.neurolearn.utils.downloader import parse_yt_date
    return ResolvedTarget(
        url=url,
        title=info.get("title"),
        upload_date=parse_yt_date(info.get("upload_date")),
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
) -> tuple[list[ResolvedTarget], list[ResolveFailure]]:
    """Expand user input into a flat list of ResolvedTarget. No media download.

    Returns: (targets, failures).
    - `targets`: successfully resolved videos (after dedup + per-source limit).
    - `failures`: probe failures per spec extension §5 — caller handles them
      (single-mode aborts; batch-mode logs them as BatchFailure(stage="resolve")
      and continues with successful targets).
    """
    raw: list[tuple[str, Source]] = []
    for u in inputs:
        raw.append((u, "inline"))
    if from_file is not None:
        for u in parse_from_file(from_file):
            raw.append((u, "file"))
    if not raw and not filters.search_query:
        raise CLIInputError(
            "No inputs given. Pass URL(s), --from-file PATH, or --search QUERY."
        )

    targets: list[ResolvedTarget] = []
    failures: list[ResolveFailure] = []
    seen_video_ids: set[str] = set()

    # Parallelize the network probes for `raw` URLs. We only parallelize
    # the I/O-bound metadata fetch; downstream processing (kind dispatch,
    # dedup, playlist expansion) stays single-threaded so the seen_video_ids
    # set needs no lock and result ordering is identical to the serial version.
    def _safe_probe(item: tuple[str, Source]) -> tuple[str, Source, tuple | Exception]:
        url, src = item
        try:
            return url, src, probe_input(url)
        except Exception as e:    # noqa: BLE001 — re-raised below per-url
            return url, src, e

    if raw:
        workers = min(_MAX_PROBE_WORKERS, len(raw))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            probed = list(ex.map(_safe_probe, raw))
    else:
        probed = []

    for url, src, result in probed:
        if isinstance(result, Exception):
            failures.append(ResolveFailure(url=url, error=str(result), source=src))
            continue
        kind, info = result

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

    # v0.3 #4: search-by-tags via yt-dlp ytsearchN:query
    if filters.search_query:
        from skills.neurolearn.utils.downloader import search_videos
        try:
            entries = search_videos(filters.search_query, limit=filters.limit)
            for e in entries:
                t = _channel_entry_to_target(e, source="search")
                if t.video_id and t.video_id in seen_video_ids:
                    continue
                if t.video_id:
                    seen_video_ids.add(t.video_id)
                targets.append(t)
        except Exception as e:
            failures.append(ResolveFailure(
                url=f"ytsearch:{filters.search_query}",
                error=str(e),
                source="search",
            ))

    # v0.3: apply post-resolution filters (since/until/duration/shorts).
    # `limit` is handled per-source in expand_* (yt-dlp playlistend); the
    # filters below run on already-probed metadata and are best-effort:
    # if a target has no upload_date / duration_sec, those filters skip it.
    targets = _apply_filters(targets, filters)

    return targets, failures


def _apply_filters(
    targets: list[ResolvedTarget],
    filters: ResolverFilters,
) -> list[ResolvedTarget]:
    """Drop targets that fail since/until/duration/shorts filters.

    Targets with missing metadata (e.g. local files have no upload_date)
    pass all date/duration checks — the filters only exclude when we
    have positive evidence of mismatch.
    """
    out: list[ResolvedTarget] = []
    for t in targets:
        if filters.since is not None and t.upload_date is not None:
            if t.upload_date < filters.since:
                continue
        if filters.until is not None and t.upload_date is not None:
            if t.upload_date > filters.until:
                continue
        if filters.min_duration_sec is not None and t.duration_sec is not None:
            if t.duration_sec < filters.min_duration_sec:
                continue
        if filters.max_duration_sec is not None and t.duration_sec is not None:
            if t.duration_sec > filters.max_duration_sec:
                continue
        # YouTube Shorts: vertical short-form videos, typically <= 60s.
        # We use a duration heuristic — yt-dlp doesn't expose a "is_short" flag.
        if not filters.include_shorts and t.duration_sec is not None:
            if t.duration_sec <= 60:
                continue
        out.append(t)
    return out
