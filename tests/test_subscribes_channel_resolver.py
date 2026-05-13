"""Tests for subscribes.channel_resolver — url → channel_id via yt-dlp."""
from unittest.mock import patch

import pytest

from skills.youtube_transcribe.subscribes.channel_resolver import (
    resolve_channel,
    ResolvedChannel,
)


def test_resolve_handle_url():
    fake = {
        "channel_id": "UC_abc123",
        "channel": "Anthropic AI",
        "uploader": "Anthropic AI",
    }
    with patch(
        "skills.youtube_transcribe.subscribes.channel_resolver._extract_flat",
        return_value=fake,
    ):
        out = resolve_channel("https://www.youtube.com/@AnthropicAI")
    assert out.channel_id == "UC_abc123"
    assert out.handle == "@AnthropicAI"
    assert out.url == "https://www.youtube.com/@AnthropicAI"


def test_resolve_canonical_url():
    fake = {
        "channel_id": "UC_xyz",
        "channel": "OpenAI",
    }
    with patch(
        "skills.youtube_transcribe.subscribes.channel_resolver._extract_flat",
        return_value=fake,
    ):
        out = resolve_channel("https://www.youtube.com/channel/UC_xyz")
    assert out.channel_id == "UC_xyz"


def test_resolve_strips_trailing_slash():
    fake = {"channel_id": "UC_a", "channel": "A"}
    with patch(
        "skills.youtube_transcribe.subscribes.channel_resolver._extract_flat",
        return_value=fake,
    ):
        out = resolve_channel("https://www.youtube.com/@A/")
    assert out.url == "https://www.youtube.com/@A"


def test_resolve_extracts_handle_from_url():
    """If yt-dlp doesn't give us a handle, parse it from the URL."""
    fake = {"channel_id": "UC_a", "channel": "TestChannel"}
    with patch(
        "skills.youtube_transcribe.subscribes.channel_resolver._extract_flat",
        return_value=fake,
    ):
        out = resolve_channel("https://www.youtube.com/@SomeHandle")
    assert out.handle == "@SomeHandle"


def test_resolve_no_channel_id_raises():
    fake = {"channel": "weird"}  # no channel_id
    with patch(
        "skills.youtube_transcribe.subscribes.channel_resolver._extract_flat",
        return_value=fake,
    ):
        with pytest.raises(ValueError, match="channel_id"):
            resolve_channel("https://www.youtube.com/@X")


# === v0.8: platform detection + IG / TikTok resolvers ===


def test_detect_platform_youtube():
    from skills.youtube_transcribe.subscribes.channel_resolver import detect_platform
    assert detect_platform("https://www.youtube.com/@anthropic-ai") == "youtube"
    assert detect_platform("https://www.youtube.com/channel/UC_abc") == "youtube"
    assert detect_platform("https://www.youtube.com/c/Anthropic") == "youtube"
    assert detect_platform("https://www.youtube.com/user/oldname") == "youtube"


def test_detect_platform_instagram():
    from skills.youtube_transcribe.subscribes.channel_resolver import detect_platform
    assert detect_platform("https://www.instagram.com/anthropic/") == "instagram"
    assert detect_platform("https://instagram.com/example") == "instagram"


def test_detect_platform_rejects_instagram_post_urls():
    """Profile detector must not match /p/, /reel/, /tv/."""
    from skills.youtube_transcribe.subscribes.channel_resolver import detect_platform
    assert detect_platform("https://www.instagram.com/p/ABC123/") is None
    assert detect_platform("https://www.instagram.com/reel/XYZ/") is None
    assert detect_platform("https://www.instagram.com/tv/abc/") is None
    assert detect_platform("https://www.instagram.com/reels/abc/") is None


def test_detect_platform_tiktok():
    from skills.youtube_transcribe.subscribes.channel_resolver import detect_platform
    assert detect_platform("https://www.tiktok.com/@duolingo") == "tiktok"
    assert detect_platform("https://www.tiktok.com/@example/") == "tiktok"


def test_detect_platform_rejects_tiktok_video_urls():
    from skills.youtube_transcribe.subscribes.channel_resolver import detect_platform
    assert (
        detect_platform("https://www.tiktok.com/@user/video/12345") is None
    )


def test_detect_platform_unknown_returns_none():
    from skills.youtube_transcribe.subscribes.channel_resolver import detect_platform
    assert detect_platform("https://vimeo.com/user12345") is None
    assert detect_platform("https://twitter.com/anthropic") is None
    assert detect_platform("not even a url") is None


def test_resolve_instagram_profile():
    """Instagram resolution must NOT hit yt-dlp — we use the username as id."""
    with patch(
        "skills.youtube_transcribe.subscribes.channel_resolver._extract_flat",
        side_effect=AssertionError("yt-dlp must not be called for IG"),
    ):
        out = resolve_channel("https://www.instagram.com/anthropic/")
    assert out.platform == "instagram"
    assert out.channel_id == "anthropic"
    assert out.handle == "@anthropic"
    assert out.url == "https://www.instagram.com/anthropic"


def test_resolve_tiktok_profile():
    with patch(
        "skills.youtube_transcribe.subscribes.channel_resolver._extract_flat",
        side_effect=AssertionError("yt-dlp must not be called for TikTok"),
    ):
        out = resolve_channel("https://www.tiktok.com/@duolingo")
    assert out.platform == "tiktok"
    assert out.channel_id == "@duolingo"
    assert out.handle == "@duolingo"
    assert out.url == "https://www.tiktok.com/@duolingo"


def test_resolve_unrecognized_url_raises():
    with pytest.raises(ValueError, match="не похож"):
        resolve_channel("https://vimeo.com/user12345")
