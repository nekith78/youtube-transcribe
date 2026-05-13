"""Tests for subscribes.instagram_loader — fallback when yt-dlp is broken."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n"
_FAKE_COOKIE_ROW = (
    ".instagram.com\tTRUE\t/\tTRUE\t9999999999\tsessionid\tfake_token\n"
)


def _make_cookies_file(p: Path) -> Path:
    p.write_text(_NETSCAPE_HEADER + _FAKE_COOKIE_ROW, encoding="utf-8")
    return p


def _make_fake_post(*, shortcode, is_video=True, duration=10,
                   caption="caption", date=None):
    """Build a mock matching the subset of instaloader.Post we use."""
    post = MagicMock()
    post.shortcode = shortcode
    post.is_video = is_video
    post.video_duration = duration
    post.caption = caption
    post.date_utc = date or datetime(2026, 5, 13, 12, 0, 0)
    return post


def test_unavailable_when_instaloader_not_installed():
    """Missing dep should raise InstaloaderUnavailable with install hint."""
    from skills.youtube_transcribe.subscribes import instagram_loader

    with patch.object(
        instagram_loader, "_lazy_import_instaloader",
        side_effect=instagram_loader.InstaloaderUnavailable(
            "instaloader is not installed"
        ),
    ):
        with pytest.raises(
            instagram_loader.InstaloaderUnavailable, match="not installed",
        ):
            instagram_loader.fetch_profile_videos("natgeo")


def test_fetches_video_posts_only(tmp_path: Path):
    """Image-only posts should be skipped; only is_video=True returned."""
    from skills.youtube_transcribe.subscribes import instagram_loader

    posts = [
        _make_fake_post(shortcode="v1", is_video=True),
        _make_fake_post(shortcode="img1", is_video=False),
        _make_fake_post(shortcode="v2", is_video=True),
    ]
    profile = MagicMock()
    profile.get_posts.return_value = iter(posts)
    profile.profile_url = "https://www.instagram.com/natgeo/"

    fake_il = MagicMock()
    fake_il.Profile.from_username.return_value = profile
    fake_il.Instaloader.return_value = MagicMock()

    with patch.object(
        instagram_loader, "_lazy_import_instaloader", return_value=fake_il,
    ):
        out = instagram_loader.fetch_profile_videos("natgeo")
    assert [v.video_id for v in out] == ["v1", "v2"]


def test_respects_limit(tmp_path: Path):
    """Limit caps the iteration — even if the profile has more posts."""
    from skills.youtube_transcribe.subscribes import instagram_loader

    posts = [
        _make_fake_post(shortcode=f"v{i}", is_video=True) for i in range(10)
    ]
    profile = MagicMock()
    profile.get_posts.return_value = iter(posts)
    profile.profile_url = "https://www.instagram.com/x/"

    fake_il = MagicMock()
    fake_il.Profile.from_username.return_value = profile
    fake_il.Instaloader.return_value = MagicMock()

    with patch.object(
        instagram_loader, "_lazy_import_instaloader", return_value=fake_il,
    ):
        out = instagram_loader.fetch_profile_videos("x", limit=3)
    assert len(out) == 3


def test_cookies_loaded_into_session(tmp_path: Path):
    """When cookies_file is given, MozillaCookieJar.load is invoked and
    cookies end up in the loader's requests session."""
    from skills.youtube_transcribe.subscribes import instagram_loader

    cookies_path = _make_cookies_file(tmp_path / "ig.txt")

    fake_session = MagicMock()
    fake_session.cookies = MagicMock()
    fake_loader = MagicMock()
    fake_loader.context._session = fake_session

    fake_il = MagicMock()
    fake_il.Instaloader.return_value = fake_loader
    profile = MagicMock()
    profile.get_posts.return_value = iter([])
    profile.profile_url = "u"
    fake_il.Profile.from_username.return_value = profile

    with patch.object(
        instagram_loader, "_lazy_import_instaloader", return_value=fake_il,
    ):
        instagram_loader.fetch_profile_videos(
            "natgeo", cookies_file=str(cookies_path),
        )

    # cookies.update was called with a populated MozillaCookieJar.
    fake_session.cookies.update.assert_called_once()


def test_warning_shown_once_per_session():
    """First call prints the bulk-scraping warning; subsequent calls do
    not re-print."""
    from skills.youtube_transcribe.subscribes import instagram_loader

    # Reset session state.
    instagram_loader._warning_shown_in_session = False

    fake_il = MagicMock()
    profile = MagicMock()
    profile.get_posts.return_value = iter([])
    profile.profile_url = "u"
    fake_il.Profile.from_username.return_value = profile
    fake_il.Instaloader.return_value = MagicMock()

    with patch.object(
        instagram_loader, "_lazy_import_instaloader", return_value=fake_il,
    ), patch.object(instagram_loader._console, "print") as mock_print:
        instagram_loader.fetch_profile_videos("a")
        instagram_loader.fetch_profile_videos("b")

    # The fallback-warning print fires exactly once across two calls.
    warning_calls = [
        call for call in mock_print.call_args_list
        if "Instagram fallback" in str(call)
    ]
    assert len(warning_calls) == 1
