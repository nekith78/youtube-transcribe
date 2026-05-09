from unittest.mock import patch, MagicMock
from skills.youtube_transcribe.backends.subtitles import SubtitlesBackend
from skills.youtube_transcribe.backends.base import BackendError


def test_supports_url_true():
    assert SubtitlesBackend().supports_url is True


def test_only_youtube_urls_supported():
    b = SubtitlesBackend()
    import pytest
    with pytest.raises(BackendError, match="YouTube"):
        b.transcribe("https://vimeo.com/123", language="en")


def test_transcribe_returns_result():
    fake_segments = [
        {"start": 0.0, "duration": 2.5, "text": "Hello"},
        {"start": 2.5, "duration": 2.5, "text": "World"},
    ]
    fake_api = MagicMock()
    fake_api.get_transcript.return_value = fake_segments

    with patch(
        "skills.youtube_transcribe.backends.subtitles._get_transcript_api",
        return_value=fake_api,
    ):
        b = SubtitlesBackend()
        result = b.transcribe("https://youtu.be/dQw4w9WgXcQ", language="en")

    assert result.backend_name == "subtitles"
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hello"
    assert result.segments[0].end == 2.5
