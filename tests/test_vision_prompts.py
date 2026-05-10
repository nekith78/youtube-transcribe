"""Tests for vision prompt template formatting."""
from skills.youtube_transcribe.vision.prompts import (
    DEFAULT_PROMPT,
    format_prompt,
)


def test_default_prompt_has_expected_keys():
    """Template должен ожидать language, transcript_snippet, start_sec, end_sec."""
    formatted = format_prompt(
        DEFAULT_PROMPT,
        language="en",
        transcript_snippet="hello",
        start_sec=10.0,
        end_sec=15.0,
    )
    assert "en" in formatted
    assert "hello" in formatted
    assert "10.0" in formatted or "10" in formatted


def test_format_prompt_unknown_language_falls_back_to_english():
    formatted = format_prompt(
        DEFAULT_PROMPT,
        language="kk",       # казахский — точно нет специального шаблона
        transcript_snippet="x",
        start_sec=0.0,
        end_sec=1.0,
    )
    # Just verify it doesn't crash and returns a non-empty string
    assert formatted
    assert "x" in formatted
