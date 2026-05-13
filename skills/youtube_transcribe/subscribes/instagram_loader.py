"""Instagram fallback fetcher via instaloader.

Used by `subscribes update` when yt-dlp's `[instagram:user]` extractor is
broken upstream (which it periodically is — Instagram changes their web
API faster than yt-dlp patches catch up).

Architecture:
  • yt-dlp stays primary. We only call this module when yt-dlp returns a
    broken-extractor signature.
  • This module reads ONLY the Netscape cookies.txt file the user
    registered via `subscribes cookies set instagram <path>`. No
    cookies-from-browser, no ambient grants. See project memory:
    feedback_cookies_strict_file_only.md.
  • instaloader is an optional dep (`pip install youtube-transcribe[instagram]`).
    Missing → raise InstaloaderUnavailable with install instructions.

Returns `_ChannelVideo` records compatible with the existing pipeline so
the downstream batch / transcription code doesn't need to know which
fetcher produced them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from skills.youtube_transcribe.subscribes.pipeline import _ChannelVideo


_console = Console()
_warning_shown_in_session = False


class InstaloaderUnavailable(Exception):
    """Raised when instaloader is not installed."""


def _ensure_warning_shown_once() -> None:
    """Print the 'fallback in use' warning once per process.

    Repeated calls become no-ops so a multi-channel update doesn't spam
    the user with the same notice.
    """
    global _warning_shown_in_session
    if _warning_shown_in_session:
        return
    _warning_shown_in_session = True
    _console.print(
        "[yellow]⚠ Instagram fallback: yt-dlp upstream cannot parse IG "
        "profiles right now,[/yellow]\n"
        "[yellow]  using instaloader.[/yellow]\n"
        "[dim]  This tool is for occasional fetches (a few channels, "
        "infrequent updates).[/dim]\n"
        "[dim]  NOT for bulk scraping (thousands of posts per hour) — "
        "Instagram will[/dim]\n"
        "[dim]  flag the account. Best practices:[/dim]\n"
        "[dim]    • Use a dedicated 'tech' IG account, not your personal "
        "one.[/dim]\n"
        "[dim]    • Don't run subscribes update more than once per "
        "hour.[/dim]\n"
        "[dim]    • On 'security warning' in IG — pause for a day.[/dim]"
    )


def _lazy_import_instaloader():
    """Import instaloader on demand. Raise InstaloaderUnavailable with
    a clear install hint if it's not installed."""
    try:
        import instaloader  # type: ignore
    except ImportError as e:
        raise InstaloaderUnavailable(
            "instaloader is not installed. Install with:\n"
            "  uv pip install 'instaloader>=4.13'\n"
            "  # or for project-wide setup:\n"
            "  uv sync --extra instagram"
        ) from e
    return instaloader


def _load_cookies_into_session(loader, cookies_file: str) -> None:
    """Load Netscape cookies.txt into instaloader's requests session.

    instaloader's own session format is a pickled dict; we work with
    Netscape directly via stdlib MozillaCookieJar so the user keeps a
    single cookies file across yt-dlp and instaloader.
    """
    jar = MozillaCookieJar(cookies_file)
    # Netscape files exported by browser extensions sometimes have
    # `# HttpOnly_` lines; MozillaCookieJar accepts them with ignore_discard.
    jar.load(ignore_discard=True, ignore_expires=True)
    # instaloader.context._session is a requests.Session; its `.cookies`
    # is a RequestsCookieJar which accepts cookies from any CookieJar via
    # `.update()`.
    loader.context._session.cookies.update(jar)


def _post_to_channel_video(post, channel_url: str):
    """Map an instaloader.Post to the pipeline's _ChannelVideo dataclass.

    Only video posts are returned; image-only posts are skipped by the
    caller's filter.
    """
    # Local import — avoid circular: pipeline imports this module.
    from skills.youtube_transcribe.subscribes.pipeline import _ChannelVideo

    # post.date_utc is a naive UTC datetime in instaloader.
    published = post.date_utc.replace(tzinfo=timezone.utc)
    return _ChannelVideo(
        video_id=post.shortcode,
        url=f"https://www.instagram.com/reel/{post.shortcode}/",
        title=(post.caption or "")[:200] if post.caption else "",
        duration_sec=int(post.video_duration) if post.video_duration else None,
        published=published,
    )


def fetch_profile_videos(
    username: str,
    *,
    cookies_file: str | None = None,
    limit: int = 30,
) -> list[_ChannelVideo]:
    """Fetch the latest `limit` video posts from an Instagram profile.

    Returns video posts only — image-only posts are filtered out. Order
    is newest-first as instaloader emits them. The caller handles
    deduplication against `last_seen_video_id` via the existing pipeline
    logic.

    Prints a one-time per-session warning that this is the fallback path
    and the user should not run high-volume scraping.

    Raises:
        InstaloaderUnavailable: instaloader is not installed.
        Other instaloader exceptions: propagate to caller, which decides
            whether to treat as channel-not-found, transient error, etc.
    """
    _ensure_warning_shown_once()
    instaloader = _lazy_import_instaloader()

    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,    # we don't download here; pipeline does
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
        # Polite rate-limit cadence between requests — sleep_pattern is
        # not a documented public API across all instaloader versions,
        # so we rely on the default polite delays here.
        request_timeout=30,
    )

    if cookies_file:
        _load_cookies_into_session(L, cookies_file)

    profile = instaloader.Profile.from_username(L.context, username)
    out: list[_ChannelVideo] = []
    for i, post in enumerate(profile.get_posts()):
        if i >= limit:
            break
        if not post.is_video:
            continue
        out.append(_post_to_channel_video(post, channel_url=profile.profile_url))
    return out
