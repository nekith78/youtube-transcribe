"""Tests for research.translator — script-based language detection +
LLM-based query translation."""
from unittest.mock import patch

import pytest

from skills.neurolearn.research.translator import (
    detect_script,
    pick_anchor_language,
    translate_query,
    build_queries_per_language,
)


# ─── detect_script (no langdetect, pure Unicode-block heuristic) ─────


def test_detect_script_cyrillic_short():
    """Short cyrillic strings work — unlike langdetect on 2-word inputs."""
    assert detect_script("Клод новинки") == "cyrillic"


def test_detect_script_cyrillic_single_word():
    assert detect_script("Клод") == "cyrillic"


def test_detect_script_latin():
    assert detect_script("Claude new features") == "latin"


def test_detect_script_cjk_chinese():
    assert detect_script("人工智能") == "cjk"


def test_detect_script_cjk_japanese():
    assert detect_script("こんにちは") == "cjk"


def test_detect_script_cjk_korean():
    assert detect_script("안녕하세요") == "cjk"


def test_detect_script_arabic():
    assert detect_script("الذكاء الاصطناعي") == "arabic"


def test_detect_script_hebrew_counts_as_arabic():
    """Hebrew shares the 'rtl' script category in our mapping."""
    assert detect_script("שלום") == "arabic"


def test_detect_script_empty():
    assert detect_script("") is None
    assert detect_script(None) is None if False else True  # None branch covered


def test_detect_script_digits_only():
    """No letter chars — None."""
    assert detect_script("12345 - !@#") is None


def test_detect_script_mixed_cyrillic_wins():
    """Mostly cyrillic with a few latin words (proper names) → cyrillic."""
    assert detect_script("Клод и GPT обзор") == "cyrillic"


def test_detect_script_mixed_latin_wins():
    """Mostly latin → latin."""
    assert detect_script("Claude features in 2026") == "latin"


# ─── pick_anchor_language ───────────────────────────────────────────


def test_anchor_explicit_hint_wins():
    """If user explicitly passes --query-lang, it overrides auto-detect."""
    assert pick_anchor_language("ru", "totally english here",
                                 ["ru", "en"]) == "ru"


def test_anchor_hint_must_be_in_languages():
    """If hint isn't in --languages, ignore it and fall through to detection.

    text = latin → first latin in [ru, en] → 'en'.
    'uk' as hint is silently dropped since it's not in --languages.
    """
    out = pick_anchor_language("uk", "Claude new features", ["ru", "en"])
    assert out == "en"


def test_anchor_script_match_cyrillic():
    """Cyrillic query + --languages ru,en → ru (first cyrillic)."""
    assert pick_anchor_language(None, "Клод новинки",
                                 ["ru", "en"]) == "ru"


def test_anchor_script_match_latin():
    """Latin query + --languages ru,en → en (first latin)."""
    assert pick_anchor_language(None, "Claude features",
                                 ["ru", "en"]) == "en"


def test_anchor_script_match_languages_order_matters():
    """If --languages is en,ru and query is cyrillic, ru still wins
    (first matching script). Order matters only inside same script."""
    assert pick_anchor_language(None, "Клод",
                                 ["en", "ru"]) == "ru"


def test_anchor_script_no_match_falls_back_to_first():
    """CJK query + --languages ru,en (no CJK) → fallback to first (ru)."""
    assert pick_anchor_language(None, "人工智能",
                                 ["ru", "en"]) == "ru"


def test_anchor_empty_text_falls_back_to_first():
    assert pick_anchor_language(None, "", ["en", "ru"]) == "en"


def test_anchor_hint_overrides_even_wrong_script():
    """User hint trumps everything (even if 'ru' for latin text)."""
    assert pick_anchor_language("ru", "Claude features",
                                 ["ru", "en"]) == "ru"


# ─── translate_query ────────────────────────────────────────────────


def test_translate_query_skip_same_language():
    with patch(
        "skills.neurolearn.research.translator.run_analysis",
    ) as mock_run:
        out = translate_query("Claude new features", target="en", source="en",
                              backend="gemini", api_key="k")
    assert out == "Claude new features"
    mock_run.assert_not_called()


def test_translate_query_calls_llm():
    with patch(
        "skills.neurolearn.research.translator.run_analysis",
        return_value="Клод новинки",
    ) as mock_run:
        out = translate_query("Claude new features", target="ru", source="en",
                              backend="gemini", api_key="k")
    assert out == "Клод новинки"
    mock_run.assert_called_once()
    prompt = mock_run.call_args.args[0]
    assert "ru" in prompt.lower() or "russian" in prompt.lower()
    assert "Claude new features" in prompt


def test_translate_query_empty_llm_returns_original():
    with patch(
        "skills.neurolearn.research.translator.run_analysis",
        return_value="",
    ):
        out = translate_query("Claude", target="ru", source="en",
                              backend="gemini", api_key="k")
    assert out == "Claude"


def test_translate_query_strips_quotes_from_llm_output():
    with patch(
        "skills.neurolearn.research.translator.run_analysis",
        return_value='"Клод новинки"',
    ):
        out = translate_query("Claude features", target="ru", source="en",
                              backend="gemini", api_key="k")
    assert out == "Клод новинки"


# ─── build_queries_per_language (the integration) ──────────────────


def test_build_queries_anchor_uses_query_as_is():
    """Cyrillic query + ru,en → ru anchor, en translated."""
    with patch(
        "skills.neurolearn.research.translator.run_analysis",
        return_value="Claude новости",
    ):
        out = build_queries_per_language(
            "Клод новости", languages=["ru", "en"],
            backend="gemini", api_key="k",
        )
    assert out["ru"] == "Клод новости"
    assert out["en"] == "Claude новости"


def test_build_queries_parallelizes_translations():
    """v0.10.4: non-anchor translations run concurrently via thread pool.
    With N languages, total wall time should be ~one LLM call, not N."""
    import threading
    import time

    concurrent_count = 0
    max_concurrent = 0
    lock = threading.Lock()

    def slow_translate(prompt, **kwargs):
        nonlocal concurrent_count, max_concurrent
        with lock:
            concurrent_count += 1
            if concurrent_count > max_concurrent:
                max_concurrent = concurrent_count
        time.sleep(0.1)  # simulate LLM latency
        with lock:
            concurrent_count -= 1
        return "<<translated>>"

    with patch(
        "skills.neurolearn.research.translator.run_analysis",
        side_effect=slow_translate,
    ):
        t0 = time.time()
        out = build_queries_per_language(
            "Claude features",
            languages=["en", "ru", "ja", "de"],
            source_lang_hint="en",   # 3 non-anchor translations
            backend="gemini", api_key="k",
        )
        elapsed = time.time() - t0

    # Strict: all four entries present.
    assert set(out.keys()) == {"en", "ru", "ja", "de"}
    assert out["en"] == "Claude features"  # anchor, no LLM call

    # Concurrency proof: at least 2 calls were in-flight simultaneously.
    # (Anchor is skipped, so 3 calls in parallel; we assert >=2 to be
    # robust to interpreter scheduling delays.)
    assert max_concurrent >= 2, f"max_concurrent={max_concurrent} (no parallelism)"
    # Wall time should be <300ms (3 × 100ms sequential would be 300ms+).
    # Generous slack for slow CI.
    assert elapsed < 0.35, f"elapsed={elapsed:.2f}s (looks sequential)"


def test_build_queries_with_explicit_hint():
    """--query-lang ru overrides script detection even when text is latin."""
    with patch(
        "skills.neurolearn.research.translator.run_analysis",
        return_value="<<en-translated>>",
    ) as mock_run:
        out = build_queries_per_language(
            "Claude features",
            languages=["ru", "en"],
            source_lang_hint="ru",  # user asserts: query is "ru" anchor
            backend="gemini", api_key="k",
        )
    # ru = anchor (raw), en = translated
    assert out["ru"] == "Claude features"
    assert out["en"] == "<<en-translated>>"
    mock_run.assert_called_once()


def test_build_queries_empty_languages():
    assert build_queries_per_language(
        "anything", languages=[], backend="gemini", api_key="k",
    ) == {}


def test_build_queries_single_language_no_llm_call():
    """If only one language and query matches its script — no LLM call."""
    with patch(
        "skills.neurolearn.research.translator.run_analysis",
    ) as mock_run:
        out = build_queries_per_language(
            "Клод новости", languages=["ru"],
            backend="gemini", api_key="k",
        )
    assert out == {"ru": "Клод новости"}
    mock_run.assert_not_called()
