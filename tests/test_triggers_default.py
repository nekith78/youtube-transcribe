"""Verify built-in triggers_default.toml has expected content."""
from skills.youtube_transcribe.detection.triggers import load_triggers


def test_builtin_has_at_least_20_universal_phrases():
    cfg = load_triggers(user_path=None)
    assert len(cfg.universal) >= 20


def test_builtin_universal_includes_key_phrases():
    cfg = load_triggers(user_path=None)
    expected = {"look here", "pay attention", "for example", "the result is"}
    assert expected.issubset(cfg.universal.keys())


def test_builtin_no_raw_or_languages():
    """Default ships only universal — raw/languages are user opt-in."""
    cfg = load_triggers(user_path=None)
    assert cfg.raw == {}
    assert cfg.languages == {}


def test_builtin_default_language_english():
    cfg = load_triggers(user_path=None)
    assert cfg.default_language == "en"
