"""Multi-language YouTube search via yt-dlp + YouTube's built-in `sp` filter.

When the caller passes a `days` hint, the search URL is built with YouTube's
`sp=...` query parameter — these are YouTube's own "uploaded within last
hour/day/week/month/year" filters. The server does the date filtering, so
results are pre-screened without us paying the full-extract cost.

Two modes:
  • exact preset match (days ∈ {1, 7, 30, 365}) → SP URL + flat extract.
    YouTube guarantees the window, dates aren't needed downstream.
  • non-exact (e.g. days=14, 90) → SP URL with the NEAREST preset UP
    + full extract so `upload_date` is populated → pipeline refines
    to the precise window client-side.

No `days` → plain `ytsearchN:` shortcut, flat extract (fast, no date info).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from urllib.parse import quote_plus

from skills.neurolearn.utils.downloader import (
    parse_yt_date,
    _yt_url_from_id,
)


@dataclass
class SearchCandidate:
    """One video from YouTube search results."""
    video_id: str
    url: str
    title: str | None
    channel: str | None
    duration_sec: int | None
    upload_date: date | None
    source_language: str  # which language produced this result


# Reverse-engineered from YouTube's search UI. Each entry: (days, sp_code).
# Ordered ascending — `_pick_sp_preset` picks the first one that fits.
# The `%3D%3D` is URL-encoded `==`; YouTube accepts both, we keep encoded
# form so the URL can be passed straight to yt-dlp without re-quoting.
_SP_PRESETS: list[tuple[int, str]] = [
    (1,   "EgIIAg%3D%3D"),  # last day
    (7,   "EgIIAw%3D%3D"),  # last week
    (30,  "EgIIBA%3D%3D"),  # last month
    (365, "EgIIBQ%3D%3D"),  # last year
]


def _pick_sp_preset(days: int) -> tuple[str, int] | None:
    """Pick the smallest SP preset ≥ days (round UP). None if days > 1y or ≤ 0."""
    if days <= 0:
        return None
    for preset_days, sp_code in _SP_PRESETS:
        if days <= preset_days:
            return sp_code, preset_days
    return None


def _build_search_url(query: str, sp_code: str | None) -> str:
    """Build YouTube results URL, optionally with the SP date filter."""
    q = quote_plus(query)
    if sp_code:
        return f"https://www.youtube.com/results?search_query={q}&sp={sp_code}"
    return f"https://www.youtube.com/results?search_query={q}"


def search_multi_language(
    queries: dict[str, str],
    *,
    limit: int,
    days: int | None = None,
) -> list[SearchCandidate]:
    """Issue one yt-dlp search per (lang, query) pair, dedup by video_id.

    `days` enables YouTube's built-in date filter (SP). When it matches an
    exact preset (1/7/30/365), flat extract is used — fast, no dates needed
    because YouTube guarantees the window. Otherwise we round UP to the
    nearest preset and pay for full extract so `upload_date` is populated
    for the caller to refine the window.

    Returns candidates in first-occurrence order. Limit applies per language
    (so up to `limit * len(queries)` videos before dedup).
    """
    sp_info: tuple[str, int] | None = None
    if days is not None and days > 0:
        sp_info = _pick_sp_preset(days)

    # Full extract only when we need precise upload_date for refinement —
    # i.e. the user's window is tighter than the SP preset granularity.
    need_full_extract = sp_info is not None and sp_info[1] != days

    seen: set[str] = set()
    out: list[SearchCandidate] = []
    for lang, query in queries.items():
        if not query or not query.strip():
            continue
        q = query.strip()
        if sp_info is not None:
            url = _build_search_url(q, sp_info[0])
        else:
            url = f"ytsearch{limit}:{q}"

        info = _extract(url, full=need_full_extract, limit=limit)
        entries = (info or {}).get("entries") or []
        for e in entries[:limit]:
            if not e:
                continue
            vid = e.get("id")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            out.append(SearchCandidate(
                video_id=vid,
                url=e.get("url") or _yt_url_from_id(vid),
                title=e.get("title"),
                channel=e.get("channel") or e.get("uploader"),
                duration_sec=int(e["duration"]) if e.get("duration") else None,
                upload_date=parse_yt_date(e.get("upload_date")),
                source_language=lang,
            ))
    return out


def _extract(url: str, *, full: bool = False, limit: int = 20) -> dict:
    """Thin yt-dlp wrapper — isolated so tests can mock it.

    `full=False` → `extract_flat=True` (fast, no upload_date).
    `full=True`  → `extract_flat=False` (slower; needed for date refinement).
    """
    from yt_dlp import YoutubeDL
    opts = {
        "quiet": True, "no_warnings": True,
        "extract_flat": not full,
        "skip_download": True,
        "geo_bypass": True,
        "playlistend": limit,
    }
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)
