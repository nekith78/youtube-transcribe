"""Tests for soft (lemmatized) per-language matching."""
import pytest

from skills.youtube_transcribe.detection.triggers import LanguageTriggers, TriggerConfig
from skills.youtube_transcribe.detection.matcher import _match_soft


def _make_cfg_ru():
    cfg = TriggerConfig()
    cfg.languages["ru"] = LanguageTriggers(soft={"смотри сюда": 1.0, "вот этот код": 1.5})
    return cfg


def _make_cfg_en():
    cfg = TriggerConfig()
    cfg.languages["en"] = LanguageTriggers(soft={"the function call": 1.0})
    return cfg


def test_soft_ru_inflected_form_matches():
    """'посмотрите сюда' должно матчить лемму 'смотри сюда' (взаимные формы глагола)."""
    cfg = _make_cfg_ru()
    res = _match_soft("посмотрите сюда внимательно", cfg, "ru")
    assert res is not None


def test_soft_ru_exact_match():
    cfg = _make_cfg_ru()
    res = _match_soft("смотри сюда", cfg, "ru")
    assert res is not None


def test_soft_en_function_calls():
    """'function calls' должно матчить лемму 'function call'."""
    cfg = _make_cfg_en()
    res = _match_soft("see how this function calls work", cfg, "en")
    assert res is not None


def test_soft_no_lang_section_returns_none():
    cfg = _make_cfg_ru()
    assert _match_soft("look here", cfg, "es") is None


@pytest.mark.parametrize("text", ["hello world", "completely unrelated"])
def test_soft_no_match(text):
    cfg = _make_cfg_ru()
    assert _match_soft(text, cfg, "ru") is None
