from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from skills.youtube_transcribe.utils.resolver import ResolvedTarget
from skills.youtube_transcribe.pipeline import run_pipeline


def _make_target(url: str = "https://youtu.be/aaa", source: str = "inline",
                 video_id: str | None = "aaa") -> ResolvedTarget:
    return ResolvedTarget(
        url=url, title="hi", upload_date=date(2026, 4, 20),
        duration_sec=60, channel="@x", source=source, video_id=video_id,
    )


def test_run_pipeline_local_file_invokes_backend(tmp_path):
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"f")
    fake_backend = MagicMock()
    fake_backend.transcribe.return_value = MagicMock(
        text="hi", segments=[], language_detected="en",
        backend_name="whisper-local", duration_seconds=1.0,
    )
    target = _make_target(url=str(audio), source="single", video_id=None)
    cfg = MagicMock(default_backend="whisper-local", language="en",
                    yt_dlp_auto_update=False, cookies_file="",
                    fast_path_enabled=True, keep_audio=False)

    with patch("skills.youtube_transcribe.pipeline.build_backend",
               return_value=fake_backend):
        result = run_pipeline(target, cfg, backend_override=None)

    assert result.backend_name == "whisper-local"
    fake_backend.transcribe.assert_called_once()


def test_run_pipeline_url_with_subtitles_skips_download(tmp_path):
    fake_backend = MagicMock()
    fake_backend.transcribe.return_value = MagicMock(
        text="t", segments=[], language_detected="en",
        backend_name="subtitles", duration_seconds=10.0,
    )
    target = _make_target()
    cfg = MagicMock(default_backend="subtitles", language="en",
                    yt_dlp_auto_update=False, cookies_file="",
                    fast_path_enabled=True, keep_audio=False)

    with patch("skills.youtube_transcribe.pipeline.build_backend",
               return_value=fake_backend), \
         patch("skills.youtube_transcribe.pipeline.download_audio") as dl:
        result = run_pipeline(target, cfg, backend_override="subtitles")

    dl.assert_not_called()
    assert result.backend_name == "subtitles"


def test_run_pipeline_url_with_whisper_local_downloads_to_temp(tmp_path):
    fake_backend = MagicMock()
    fake_backend.transcribe.return_value = MagicMock(
        text="t", segments=[], language_detected="en",
        backend_name="whisper-local", duration_seconds=10.0,
    )
    target = _make_target()
    cfg = MagicMock(default_backend="whisper-local", language="en",
                    yt_dlp_auto_update=False, cookies_file="",
                    fast_path_enabled=True, keep_audio=False)

    fake_audio = tmp_path / "audio.mp3"
    fake_audio.write_bytes(b"x")
    with patch("skills.youtube_transcribe.pipeline.build_backend",
               return_value=fake_backend), \
         patch("skills.youtube_transcribe.pipeline.download_audio",
               return_value=fake_audio):
        result = run_pipeline(target, cfg, backend_override="whisper-local")

    assert result.backend_name == "whisper-local"
    fake_backend.transcribe.assert_called_once()


def test_run_pipeline_propagates_backend_not_configured(tmp_path):
    from skills.youtube_transcribe.backends.base import BackendNotConfigured
    fake_audio = tmp_path / "audio.mp3"
    fake_audio.write_bytes(b"x")
    target = _make_target()
    cfg = MagicMock(default_backend="gemini", language="en",
                    yt_dlp_auto_update=False, cookies_file="",
                    fast_path_enabled=True, keep_audio=False)
    with patch("skills.youtube_transcribe.pipeline.build_backend",
               side_effect=BackendNotConfigured("GEMINI_API_KEY missing")), \
         patch("skills.youtube_transcribe.pipeline.download_audio",
               return_value=fake_audio):
        with pytest.raises(BackendNotConfigured):
            run_pipeline(target, cfg, backend_override=None)
