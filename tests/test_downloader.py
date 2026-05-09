from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from skills.youtube_transcribe.utils.downloader import (
    is_url,
    is_youtube_url,
    extract_youtube_video_id,
    build_ytdlp_command,
    ChannelEntry,
    DownloadError,
    expand_channel_or_playlist,
    probe_input,
)


def test_is_url_true_for_http():
    assert is_url("https://youtu.be/dQw4w9WgXcQ")


def test_is_url_false_for_path():
    assert not is_url("C:/videos/file.mp4")
    assert not is_url("/home/user/file.mp3")


def test_is_youtube_url_short():
    assert is_youtube_url("https://youtu.be/abc123")


def test_is_youtube_url_long():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc123")


def test_is_youtube_url_false_for_vimeo():
    assert not is_youtube_url("https://vimeo.com/12345")


def test_extract_video_id_short():
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_long():
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s") == "dQw4w9WgXcQ"


def test_build_ytdlp_command_basic(tmp_path: Path):
    cmd = build_ytdlp_command(
        url="https://youtu.be/abc",
        output_template=str(tmp_path / "audio.%(ext)s"),
        cookies_browser="",
    )
    assert "yt-dlp" in cmd[0]
    assert "-x" in cmd
    assert "--audio-format" in cmd
    assert "mp3" in cmd
    assert "https://youtu.be/abc" in cmd
    assert "--cookies-from-browser" not in cmd  # only added when set


def test_build_ytdlp_command_with_cookies(tmp_path: Path):
    cmd = build_ytdlp_command(
        url="https://youtu.be/abc",
        output_template=str(tmp_path / "audio.%(ext)s"),
        cookies_browser="chrome",
    )
    assert "--cookies-from-browser" in cmd
    assert "chrome" in cmd


# ---------------------------------------------------------------------------
# Task 7B: probe_input + expand_channel_or_playlist
# ---------------------------------------------------------------------------


def test_probe_input_video(tmp_path):
    fake_info = {"_type": "video", "id": "abc123", "title": "Hello",
                 "duration": 134, "upload_date": "20260420", "channel": "@anth"}
    with patch("skills.youtube_transcribe.utils.downloader._extract_flat",
               return_value=fake_info):
        kind, payload = probe_input("https://youtu.be/abc123")
    assert kind == "video"
    assert payload["id"] == "abc123"


def test_probe_input_playlist():
    fake_info = {
        "_type": "playlist", "id": "PL1", "title": "@channel",
        "entries": [
            {"id": "v1", "title": "First", "duration": 60, "upload_date": "20260101"},
            {"id": "v2", "title": "Second", "duration": 120, "upload_date": "20260201"},
        ],
    }
    with patch("skills.youtube_transcribe.utils.downloader._extract_flat",
               return_value=fake_info):
        kind, payload = probe_input("https://youtube.com/@channel")
    assert kind == "playlist"
    assert len(payload["entries"]) == 2


def test_probe_input_local_file(tmp_path):
    f = tmp_path / "audio.mp3"
    f.write_bytes(b"x")
    kind, payload = probe_input(str(f))
    assert kind == "local"
    assert payload["path"] == str(f)


def test_expand_channel_or_playlist_applies_limit():
    fake_info = {
        "_type": "playlist", "id": "PL1", "title": "@channel",
        "entries": [
            {"id": f"v{i}", "title": f"Video {i}", "duration": 60,
             "upload_date": "20260101"} for i in range(50)
        ],
    }
    with patch("skills.youtube_transcribe.utils.downloader._extract_flat",
               return_value=fake_info):
        entries = expand_channel_or_playlist("https://youtube.com/@channel", limit=10)
    assert len(entries) == 10
    assert all(isinstance(e, ChannelEntry) for e in entries)
    assert entries[0].video_id == "v0"
    assert entries[9].video_id == "v9"


def test_expand_channel_or_playlist_handles_missing_metadata():
    fake_info = {
        "_type": "playlist", "id": "PL1", "title": "@channel",
        "entries": [
            {"id": "v1", "title": "Live stream"},  # no duration, no upload_date
        ],
    }
    with patch("skills.youtube_transcribe.utils.downloader._extract_flat",
               return_value=fake_info):
        entries = expand_channel_or_playlist("https://youtube.com/@channel", limit=10)
    assert len(entries) == 1
    assert entries[0].video_id == "v1"
    assert entries[0].duration_sec is None
    assert entries[0].upload_date is None


def test_download_audio_raises_when_yt_dlp_not_in_path(tmp_path: Path):
    """yt-dlp missing → DownloadError + no output dir created."""
    target_dir = tmp_path / "out"  # does NOT exist
    with patch("shutil.which", return_value=None):
        with pytest.raises(DownloadError, match="не найден"):
            from skills.youtube_transcribe.utils.downloader import download_audio
            download_audio("https://youtu.be/abc", target_dir)
    assert not target_dir.exists()  # debris check


def test_extract_flat_wraps_yt_dlp_download_error():
    """yt-dlp's own DownloadError must be re-raised as our DownloadError."""
    from yt_dlp.utils import DownloadError as YtDlpDownloadError
    import yt_dlp
    fake_ydl_class = MagicMock()
    fake_ctx = MagicMock()
    fake_ctx.extract_info.side_effect = YtDlpDownloadError("HTTP 403")
    fake_ydl_class.return_value.__enter__.return_value = fake_ctx
    with patch.object(yt_dlp, "YoutubeDL", fake_ydl_class):
        from skills.youtube_transcribe.utils.downloader import _extract_flat
        with pytest.raises(DownloadError):
            _extract_flat("https://youtu.be/blocked")
