"""Tests for OpenAIBackend — Task 14.

All tests mock the openai SDK; no real API calls are made.
"""
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from skills.youtube_transcribe.backends.openai_api import OpenAIBackend
from skills.youtube_transcribe.backends.base import BackendError, BackendNotConfigured


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------

def test_is_configured_without_key():
    with patch("skills.youtube_transcribe.backends.openai_api.get_api_key", return_value=None):
        ok, reason = OpenAIBackend().is_configured()
        assert ok is False
        assert "OPENAI_API_KEY" in reason


def test_is_configured_with_key():
    with patch("skills.youtube_transcribe.backends.openai_api.get_api_key", return_value="sk-test"):
        ok, reason = OpenAIBackend().is_configured()
        assert ok is True
        assert reason is None


# ---------------------------------------------------------------------------
# transcribe — happy path
# ---------------------------------------------------------------------------

def test_transcribe_maps_response(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")

    fake_resp = MagicMock(
        text="Hello world.",
        language="en",
        duration=2.5,
        segments=[
            {"start": 0.0, "end": 1.0, "text": "Hello"},
            {"start": 1.0, "end": 2.5, "text": "world."},
        ],
    )
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = fake_resp

    with patch("skills.youtube_transcribe.backends.openai_api.get_api_key", return_value="sk-x"), \
         patch("skills.youtube_transcribe.backends.openai_api._build_client", return_value=fake_client):
        b = OpenAIBackend(model="whisper-1")
        result = b.transcribe(audio, language="en")

    assert result.backend_name == "openai"
    assert result.text == "Hello world."
    assert len(result.segments) == 2
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 1.0
    assert result.segments[0].text == "Hello"
    assert result.segments[1].start == 1.0
    assert result.segments[1].end == 2.5
    assert result.segments[1].text == "world."
    assert result.language_detected == "en"
    assert result.duration_seconds == 2.5


def test_transcribe_auto_language(tmp_path: Path):
    """When language='auto' the SDK call must not pass a language arg (None)."""
    audio = tmp_path / "b.mp3"
    audio.write_bytes(b"fake")

    fake_resp = MagicMock(text="Hola.", language="es", duration=1.0, segments=[])
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = fake_resp

    with patch("skills.youtube_transcribe.backends.openai_api.get_api_key", return_value="sk-x"), \
         patch("skills.youtube_transcribe.backends.openai_api._build_client", return_value=fake_client):
        b = OpenAIBackend()
        b.transcribe(audio, language="auto")

    call_kwargs = fake_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs.get("language") is None


def test_transcribe_empty_segments(tmp_path: Path):
    audio = tmp_path / "c.mp3"
    audio.write_bytes(b"fake")

    fake_resp = MagicMock(text="", language="en", duration=0.0, segments=[])
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = fake_resp

    with patch("skills.youtube_transcribe.backends.openai_api.get_api_key", return_value="sk-x"), \
         patch("skills.youtube_transcribe.backends.openai_api._build_client", return_value=fake_client):
        result = OpenAIBackend().transcribe(audio)

    assert result.segments == []
    assert result.text == ""
    assert result.duration_seconds == 0.0


def test_transcribe_segments_as_objects(tmp_path: Path):
    """Segments can also be objects (attr-access style), not just dicts."""
    audio = tmp_path / "d.mp3"
    audio.write_bytes(b"fake")

    seg = MagicMock(start=0.0, end=3.0, text="  object segment  ")
    fake_resp = MagicMock(text="object segment", language="en", duration=3.0, segments=[seg])
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = fake_resp

    with patch("skills.youtube_transcribe.backends.openai_api.get_api_key", return_value="sk-x"), \
         patch("skills.youtube_transcribe.backends.openai_api._build_client", return_value=fake_client):
        result = OpenAIBackend().transcribe(audio)

    assert result.segments[0].text == "object segment"
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 3.0


# ---------------------------------------------------------------------------
# transcribe — error paths
# ---------------------------------------------------------------------------

def test_transcribe_raises_backend_not_configured_when_key_missing(tmp_path: Path):
    audio = tmp_path / "nokey.mp3"
    audio.write_bytes(b"fake")

    with patch("skills.youtube_transcribe.backends.openai_api.get_api_key", return_value=None):
        b = OpenAIBackend()
        with pytest.raises(BackendNotConfigured):
            b.transcribe(audio)


def test_transcribe_raises_backend_error_for_missing_file():
    with patch("skills.youtube_transcribe.backends.openai_api.get_api_key", return_value="sk-x"):
        b = OpenAIBackend()
        with pytest.raises(BackendError, match="not found"):
            b.transcribe(Path("/nonexistent/path/audio.mp3"))


def test_transcribe_raises_backend_error_on_api_exception(tmp_path: Path):
    audio = tmp_path / "apierr.mp3"
    audio.write_bytes(b"fake")

    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.side_effect = RuntimeError("rate limit")

    with patch("skills.youtube_transcribe.backends.openai_api.get_api_key", return_value="sk-x"), \
         patch("skills.youtube_transcribe.backends.openai_api._build_client", return_value=fake_client):
        b = OpenAIBackend()
        with pytest.raises(BackendError, match="rate limit"):
            b.transcribe(audio)


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

def test_backend_attributes():
    b = OpenAIBackend()
    assert b.name == "openai"
    assert b.supports_url is False
    assert b.supports_local_file is True


def test_backend_default_model():
    b = OpenAIBackend()
    assert b.model == "whisper-1"


def test_backend_custom_model():
    b = OpenAIBackend(model="whisper-2")
    assert b.model == "whisper-2"
