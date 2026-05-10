"""Verify Aho-Corasick automaton caching: same phrase set → same automaton."""
from skills.youtube_transcribe.detection import matcher
from skills.youtube_transcribe.detection.matcher import (
    _build_automaton_cached,
    _build_raw_automaton,
    _build_strict_automaton,
)
from skills.youtube_transcribe.detection.triggers import LanguageTriggers, TriggerConfig


def setup_function(_func):
    """Clear cache before each test for clean state."""
    _build_automaton_cached.cache_clear()


def test_cache_hits_on_repeat_calls():
    """Calling _build_automaton_cached with same items → cache hit, no rebuild."""
    items = (("TODO", 2.0), ("FIXME", 1.0))
    a1 = _build_automaton_cached(items)
    a2 = _build_automaton_cached(items)
    assert a1 is a2  # same object — cached


def test_cache_miss_on_different_items():
    """Different phrase sets → different automatons."""
    a1 = _build_automaton_cached((("TODO", 2.0),))
    a2 = _build_automaton_cached((("FIXME", 1.0),))
    assert a1 is not a2


def test_raw_automaton_cached_across_cfgs():
    """Two cfgs with identical raw triggers share the same automaton."""
    cfg1 = TriggerConfig()
    cfg1.raw = {"TODO": 2.0, "FIXME": 1.0}
    cfg2 = TriggerConfig()
    cfg2.raw = {"FIXME": 1.0, "TODO": 2.0}  # same items, different insertion order

    a1 = _build_raw_automaton(cfg1)
    a2 = _build_raw_automaton(cfg2)
    assert a1 is a2  # both should hit cache (sorted items make order irrelevant)


def test_strict_automaton_cached_per_language():
    """Same language strict triggers cached; different langs get different automatons."""
    cfg = TriggerConfig()
    cfg.languages["ru"] = LanguageTriggers(strict={"баг": 1.0})
    cfg.languages["en"] = LanguageTriggers(strict={"bug": 1.0})

    a_ru = _build_strict_automaton(cfg, "ru")
    a_en = _build_strict_automaton(cfg, "en")
    assert a_ru is not None
    assert a_en is not None
    assert a_ru is not a_en  # different phrase sets per language

    # Re-call returns same instance
    a_ru2 = _build_strict_automaton(cfg, "ru")
    assert a_ru is a_ru2


def test_cache_info_tracks_hits():
    """Verify lru_cache actually counts hits (sanity)."""
    _build_automaton_cached.cache_clear()
    items = (("foo", 1.0),)
    _build_automaton_cached(items)
    _build_automaton_cached(items)
    _build_automaton_cached(items)
    info = _build_automaton_cached.cache_info()
    assert info.misses == 1
    assert info.hits == 2


def test_empty_items_returns_none_cached():
    """Empty tuple → None, also cached."""
    a1 = _build_automaton_cached(())
    a2 = _build_automaton_cached(())
    assert a1 is None
    assert a2 is None


def test_no_strict_for_lang_returns_none():
    cfg = TriggerConfig()
    cfg.languages["ru"] = LanguageTriggers(strict={})  # empty
    assert _build_strict_automaton(cfg, "ru") is None
    assert _build_strict_automaton(cfg, "es") is None  # no entry at all
