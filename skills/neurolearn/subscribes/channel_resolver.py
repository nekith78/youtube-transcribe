"""Resolve a channel URL (YouTube / Instagram / TikTok) to a stable identifier.

One-time call on `subscribes add` — result is cached in subscribes.toml so
subsequent operations (RSS / yt-dlp scrape) work directly without re-resolving.

`channel_id` semantics by platform:
  - YouTube: stable `UC...` from yt-dlp metadata (won't change on handle rename)
  - Instagram: the username (URL path segment) — there is no stable internal
    id available without an authenticated API
  - TikTok: the @handle — same constraint as Instagram
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# Profile-style URL detectors (NOT post/video URLs).
# YouTube has many channel URL shapes: /@handle, /c/Name, /channel/UC..., /user/...
_YT_CHANNEL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?youtube\.com/"
    r"(?:@[\w\-.]+|c/[\w\-.]+|channel/[\w\-]+|user/[\w\-]+)/?",
    re.IGNORECASE,
)
# Instagram profile: instagram.com/<username>/ — must NOT match /p/, /reel/, /tv/.
_IG_PROFILE_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?instagram\.com/"
    r"(?!p/|reel/|reels/|tv/|stories/|explore/)([\w\-.]+)/?",
    re.IGNORECASE,
)
# TikTok profile: tiktok.com/@<username> — must NOT match /video/.
_TT_PROFILE_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?tiktok\.com/(@[\w\-.]+)/?$",
    re.IGNORECASE,
)


@dataclass
class ResolvedChannel:
    url: str          # canonical, trailing-slash stripped
    handle: str | None  # @handle if present in URL
    channel_id: str   # UC... for YouTube; username for IG; @handle for TikTok
    title: str | None
    platform: str = "youtube"


def detect_platform(url: str) -> str | None:
    """Return 'youtube' / 'instagram' / 'tiktok' or None if URL not a known channel."""
    if _YT_CHANNEL_RE.match(url):
        return "youtube"
    if _TT_PROFILE_RE.match(url):
        return "tiktok"
    # Instagram regex is the loosest (matches any username), test last so the
    # other two get priority on ambiguous inputs.
    if _IG_PROFILE_RE.match(url):
        return "instagram"
    return None


def resolve_channel(url: str) -> ResolvedChannel:
    """Route to the platform-specific resolver. Raises ValueError if unrecognized."""
    platform = detect_platform(url)
    if platform is None:
        raise ValueError(
            f"URL doesn't look like a YouTube / Instagram / TikTok profile or channel: {url}"
        )
    if platform == "youtube":
        return _resolve_youtube(url)
    if platform == "instagram":
        return _resolve_instagram(url)
    if platform == "tiktok":
        return _resolve_tiktok(url)
    raise ValueError(f"unsupported platform: {platform}")  # unreachable


def _resolve_youtube(url: str) -> ResolvedChannel:
    canonical = url.rstrip("/")
    handle = _extract_handle(canonical)
    info = _extract_flat(canonical)
    channel_id = info.get("channel_id")
    if not channel_id:
        raise ValueError(f"could not resolve channel_id for {url}")
    return ResolvedChannel(
        url=canonical,
        handle=handle,
        channel_id=channel_id,
        title=info.get("channel") or info.get("uploader"),
        platform="youtube",
    )


def _resolve_instagram(url: str) -> ResolvedChannel:
    """Instagram has no stable internal id reachable without auth — use the
    username as the identifier. Username changes are the user's problem
    (we error out during `update` and tell them to remove + re-add).
    """
    canonical = url.rstrip("/")
    m = _IG_PROFILE_RE.match(canonical)
    if not m:
        raise ValueError(f"not an Instagram profile URL: {url}")
    username = m.group(1)
    return ResolvedChannel(
        url=canonical,
        handle=f"@{username}",
        channel_id=username,
        title=None,  # would need auth to fetch profile title
        platform="instagram",
    )


def _resolve_tiktok(url: str) -> ResolvedChannel:
    """TikTok @handle is the identifier — no separate internal id is
    reachable without scraping the profile page (which we defer to
    `subscribes update`)."""
    canonical = url.rstrip("/")
    m = _TT_PROFILE_RE.match(canonical)
    if not m:
        raise ValueError(f"not a TikTok profile URL: {url}")
    handle = m.group(1)  # includes the leading @
    return ResolvedChannel(
        url=canonical,
        handle=handle,
        channel_id=handle,
        title=None,
        platform="tiktok",
    )


def _extract_handle(url: str) -> str | None:
    """Extract @handle from a YouTube URL, if present."""
    m = re.search(r"/(@[\w\-.]+)", url)
    return m.group(1) if m else None


def _extract_flat(url: str) -> dict:
    """yt-dlp wrapper — isolated for tests to mock."""
    from yt_dlp import YoutubeDL
    opts = {
        "quiet": True, "no_warnings": True,
        "extract_flat": True, "skip_download": True,
        "playlist_items": "0",  # only metadata, don't enumerate uploads
    }
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}
