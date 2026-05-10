"""Tests for auto-translate via LLM."""
import json
from unittest.mock import patch, MagicMock

from skills.youtube_transcribe.quality.translator import (
    _build_input_json,
    _parse_translated,
    translate_transcript,
)
from skills.youtube_transcribe.utils.output_writer import Segment


def _s(start, end, text):
    return Segment(start=start, end=end, text=text)


def test_skip_when_same_language():
    """source == target → no LLM call, return originals."""
    orig = [_s(0, 5, "hello")]
    with patch("google.genai.Client") as mock_client:
        out = translate_transcript(
            orig, "en", "en", api_key="k", backend="gemini",
        )
    assert out == orig
    mock_client.assert_not_called()


def test_skip_when_empty():
    out = translate_transcript([], "en", "ru", api_key="k", backend="gemini")
    assert out == []


def test_translate_preserves_timestamps():
    orig = [_s(1.5, 7.2, "hello world")]
    fake_resp = MagicMock()
    fake_resp.text = json.dumps([
        {"start": 99.9, "end": 199.9, "text": "привет мир"},
    ])
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_resp

    with patch("google.genai.Client", return_value=fake_client):
        out = translate_transcript(
            orig, "en", "ru", api_key="k", backend="gemini",
        )
    # Timestamps preserved from original (LLM tried to change them, we ignored)
    assert out[0].start == 1.5
    assert out[0].end == 7.2
    assert out[0].text == "привет мир"


def test_translate_via_each_backend():
    orig = [_s(0, 5, "hello")]
    # Gemini
    g_resp = MagicMock()
    g_resp.text = json.dumps([{"start": 0, "end": 5, "text": "привет"}])
    g_client = MagicMock()
    g_client.models.generate_content.return_value = g_resp
    with patch("google.genai.Client", return_value=g_client):
        out = translate_transcript(orig, "en", "ru", api_key="k", backend="gemini")
    assert out[0].text == "привет"

    # Claude
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = json.dumps([{"start": 0, "end": 5, "text": "привет"}])
    c_resp = MagicMock()
    c_resp.content = [text_block]
    c_client = MagicMock()
    c_client.messages.create.return_value = c_resp
    with patch("anthropic.Anthropic", return_value=c_client):
        out = translate_transcript(orig, "en", "ru", api_key="k", backend="claude")
    assert out[0].text == "привет"

    # OpenAI
    choice = MagicMock()
    choice.message.content = json.dumps([{"start": 0, "end": 5, "text": "привет"}])
    o_resp = MagicMock()
    o_resp.choices = [choice]
    o_client = MagicMock()
    o_client.chat.completions.create.return_value = o_resp
    with patch("openai.OpenAI", return_value=o_client):
        out = translate_transcript(orig, "en", "ru", api_key="k", backend="openai")
    assert out[0].text == "привет"


def test_translate_via_ollama():
    orig = [_s(0, 5, "hello")]
    body = json.dumps({
        "response": json.dumps([{"start": 0, "end": 5, "text": "привет"}]),
    }).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read = MagicMock(return_value=body)
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=None)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = translate_transcript(
            orig, "en", "ru", api_key=None, backend="ollama",
        )
    assert out[0].text == "привет"


def test_translate_llm_failure_returns_original():
    orig = [_s(0, 5, "hello")]
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = RuntimeError("rate limit")

    with patch("google.genai.Client", return_value=fake_client):
        out = translate_transcript(orig, "en", "ru", api_key="k", backend="gemini")
    assert out == orig


def test_translate_wrong_length_returns_original():
    orig = [_s(0, 5, "a"), _s(5, 10, "b")]
    fake_resp = MagicMock()
    fake_resp.text = json.dumps([{"start": 0, "end": 5, "text": "x"}])  # only 1
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_resp

    with patch("google.genai.Client", return_value=fake_client):
        out = translate_transcript(orig, "en", "ru", api_key="k", backend="gemini")
    assert out == orig


def test_parse_strips_code_fences():
    orig = [_s(0, 5, "x")]
    raw = '```json\n[{"start":0,"end":5,"text":"привет"}]\n```'
    out = _parse_translated(raw, orig)
    assert out[0].text == "привет"
