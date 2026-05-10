"""Tests for Ollama local-LLM backend in ASR correction."""
import io
import json
from unittest.mock import patch, MagicMock

from skills.youtube_transcribe.quality.asr_corrector import (
    _call_ollama,
    correct_transcript_via_llm,
)
from skills.youtube_transcribe.utils.output_writer import Segment


def _s(start, end, text):
    return Segment(start=start, end=end, text=text)


def _fake_ollama_response(corrected_segments):
    """Build a fake urllib response containing Ollama's JSON output."""
    inner = json.dumps(corrected_segments)
    body = json.dumps({"response": inner}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read = MagicMock(return_value=body)
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=None)
    return mock_resp


def test_call_ollama_posts_to_local_host():
    """Verify the urllib.request goes to http://localhost:11434/api/generate."""
    captured = {}

    def fake_urlopen(req, timeout=120):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return _fake_ollama_response([{"start": 0, "end": 1, "text": "ok"}])

    with patch("urllib.request.urlopen", fake_urlopen):
        out = _call_ollama("prompt", model="llama3.2:3b")
    assert captured["url"] == "http://localhost:11434/api/generate"
    payload = json.loads(captured["data"])
    assert payload["model"] == "llama3.2:3b"
    assert payload["prompt"] == "prompt"
    assert payload["stream"] is False


def test_call_ollama_custom_host():
    captured = {}

    def fake_urlopen(req, timeout=120):
        captured["url"] = req.full_url
        return _fake_ollama_response([])

    with patch("urllib.request.urlopen", fake_urlopen):
        _call_ollama("prompt", host="http://192.168.0.10:11434")
    assert captured["url"] == "http://192.168.0.10:11434/api/generate"


def test_correct_via_ollama_returns_corrected():
    orig = [_s(0.0, 5.0, "elephats")]
    corrected = [{"start": 0.0, "end": 5.0, "text": "elephants"}]

    with patch(
        "urllib.request.urlopen",
        return_value=_fake_ollama_response(corrected),
    ):
        out = correct_transcript_via_llm(
            orig, "en", api_key=None, backend="ollama",
        )
    assert out[0].text == "elephants"
    assert out[0].start == 0.0
    assert out[0].end == 5.0


def test_correct_via_ollama_no_api_key_works():
    """Ollama doesn't need an api_key. Passing None must work."""
    orig = [_s(0.0, 5.0, "x")]
    with patch(
        "urllib.request.urlopen",
        return_value=_fake_ollama_response([{"start": 0, "end": 5, "text": "y"}]),
    ):
        out = correct_transcript_via_llm(
            orig, "en", api_key=None, backend="ollama",
        )
    assert out[0].text == "y"


def test_ollama_connection_failure_returns_original():
    """If Ollama isn't running, return original segments unchanged."""
    orig = [_s(0.0, 5.0, "hello")]
    with patch(
        "urllib.request.urlopen",
        side_effect=ConnectionRefusedError("no daemon"),
    ):
        out = correct_transcript_via_llm(
            orig, "en", api_key=None, backend="ollama",
        )
    assert out == orig


def test_ollama_model_override():
    """correct_transcript_via_llm passes ollama_model through to _call_ollama."""
    captured = {}

    def fake_urlopen(req, timeout=120):
        captured["data"] = req.data
        return _fake_ollama_response([{"start": 0, "end": 5, "text": "x"}])

    with patch("urllib.request.urlopen", fake_urlopen):
        correct_transcript_via_llm(
            [_s(0.0, 5.0, "x")], "en",
            api_key=None, backend="ollama",
            ollama_model="qwen2.5:7b",
            ollama_host="http://localhost:11434",
        )
    payload = json.loads(captured["data"])
    assert payload["model"] == "qwen2.5:7b"
