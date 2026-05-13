"""Tests for Instagram URL detection + error diagnostics."""
import pytest

from skills.youtube_transcribe.utils.downloader import (
    extract_instagram_shortcode,
    is_instagram_url,
    is_url,
    is_youtube_url,
    _diagnose_ytdlp_error,
)


@pytest.mark.parametrize("url, expected", [
    # Standard post
    ("https://www.instagram.com/p/ABC123xyz/", True),
    # Reel
    ("https://www.instagram.com/reel/DEF456abc/", True),
    # IGTV
    ("https://www.instagram.com/tv/GHI789jkl/", True),
    # Reels (alt path)
    ("https://www.instagram.com/reels/MNO000xyz/", True),
    # No www
    ("https://instagram.com/p/AAA/", True),
    # http not https
    ("http://www.instagram.com/p/BBB/", True),
    # Profile URL (not a post) — should NOT match
    ("https://www.instagram.com/anthropic/", False),
    # YouTube URL
    ("https://youtu.be/jNQXAC9IVRw", False),
    # Random URL
    ("https://example.com/foo", False),
    ("not a url", False),
])
def test_is_instagram_url(url, expected):
    assert is_instagram_url(url) is expected


def test_extract_instagram_shortcode():
    assert extract_instagram_shortcode(
        "https://www.instagram.com/p/ABC123xyz/"
    ) == "ABC123xyz"
    assert extract_instagram_shortcode(
        "https://www.instagram.com/reel/DEF456/"
    ) == "DEF456"
    assert extract_instagram_shortcode("https://example.com") is None


def test_instagram_url_passes_is_url():
    """Instagram URLs should be recognized as URLs by the generic check."""
    assert is_url("https://www.instagram.com/p/ABC/") is True


def test_youtube_and_instagram_dont_overlap():
    """A URL can be one or the other but not both."""
    yt = "https://youtu.be/abc"
    ig = "https://www.instagram.com/p/abc/"
    assert is_youtube_url(yt) and not is_instagram_url(yt)
    assert is_instagram_url(ig) and not is_youtube_url(ig)


def test_diagnose_instagram_login_error():
    """Instagram-specific errors get a tailored hint pointing at the
    cookies-file workflow (we don't recommend --cookies-from-browser)."""
    msg = _diagnose_ytdlp_error(
        "ERROR: [Instagram] Login required to access this content. "
        "Use --cookies."
    )
    assert "Instagram" in msg
    assert "cookies" in msg.lower()
    assert "subscribes cookies set" in msg
    # Hint must NOT push the user toward --cookies-from-browser.
    assert "cookies-from-browser" not in msg


def test_diagnose_instagram_rate_limit():
    msg = _diagnose_ytdlp_error(
        "ERROR: [Instagram] Rate-limit reached. Please try again later."
    )
    assert "Instagram" in msg
    assert "cookies" in msg.lower()


def test_diagnose_youtube_403_unchanged():
    """YouTube-style errors still get the YouTube hint, not the Instagram one."""
    msg = _diagnose_ytdlp_error("ERROR: HTTP Error 403: Forbidden. Sign in to confirm")
    assert "YouTube" in msg
    assert "Instagram" not in msg
