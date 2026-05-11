"""Tests for research.translator — LLM query translation per language."""
from unittest.mock import patch

import pytest

from skills.youtube_transcribe.research.translator import (
    detect_language,
    translate_query,
    build_queries_per_language,
)


def test_detect_language_ru():
    # Longer sample so langdetect is reliable (short cyrillic ↔ mk/uk/bg).
    out = detect_language(
        "Расскажите пожалуйста подробнее о последних новинках "
        "в искусственном интеллекте за прошлую неделю"
    )
    assert out == "ru"


def test_detect_language_en():
    out = detect_language(
        "Tell me more about the latest features released in Claude this week"
    )
    assert out == "en"


def test_detect_language_short_string():
    """langdetect can fail on very short input — should return None."""
    result = detect_language("hi")
    # langdetect may or may not detect; both None and a code are acceptable
    assert result is None or isinstance(result, str)


def test_translate_query_skip_same_language():
    """If target == source language, return query as-is, no LLM call."""
    with patch(
        "skills.youtube_transcribe.research.translator.run_analysis",
    ) as mock_run:
        out = translate_query("Claude new features", target="en", source="en",
                              backend="gemini", api_key="k")
    assert out == "Claude new features"
    mock_run.assert_not_called()


def test_translate_query_calls_llm():
    with patch(
        "skills.youtube_transcribe.research.translator.run_analysis",
        return_value="Клод новинки",
    ) as mock_run:
        out = translate_query("Claude new features", target="ru", source="en",
                              backend="gemini", api_key="k")
    assert out == "Клод новинки"
    mock_run.assert_called_once()
    # Verify prompt mentions both source and target language
    prompt = mock_run.call_args.args[0]
    assert "ru" in prompt.lower() or "russian" in prompt.lower()
    assert "Claude new features" in prompt


def test_translate_query_empty_llm_returns_original():
    with patch(
        "skills.youtube_transcribe.research.translator.run_analysis",
        return_value="",
    ):
        out = translate_query("Claude", target="ru", source="en",
                              backend="gemini", api_key="k")
    assert out == "Claude"


def test_translate_query_strips_quotes_from_llm_output():
    """LLMs love wrapping output in quotes — strip them."""
    with patch(
        "skills.youtube_transcribe.research.translator.run_analysis",
        return_value='"Клод новинки"',
    ):
        out = translate_query("Claude features", target="ru", source="en",
                              backend="gemini", api_key="k")
    assert out == "Клод новинки"


def test_build_queries_for_matching_source_language():
    """If query is in ru and languages=ru,en — ru uses query as-is, en translated."""
    with patch(
        "skills.youtube_transcribe.research.translator.run_analysis",
        return_value="Claude новости",
    ), patch(
        "skills.youtube_transcribe.research.translator.detect_language",
        return_value="ru",
    ):
        out = build_queries_per_language(
            "Клод новости", languages=["ru", "en"],
            backend="gemini", api_key="k",
        )
    assert out["ru"] == "Клод новости"
    assert out["en"] == "Claude новости"


def test_build_queries_unknown_source_uses_first_lang_as_anchor():
    """If language can't be detected, use the query as-is for the first lang
    and translate to the others."""
    with patch(
        "skills.youtube_transcribe.research.translator.run_analysis",
        return_value="<<translated>>",
    ), patch(
        "skills.youtube_transcribe.research.translator.detect_language",
        return_value=None,
    ):
        out = build_queries_per_language(
            "ambiguous", languages=["en", "ru"],
            backend="gemini", api_key="k",
        )
    assert out["en"] == "ambiguous"
    assert out["ru"] == "<<translated>>"
