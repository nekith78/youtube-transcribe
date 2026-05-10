"""Tests for perplexity brick (opt-in). transformers / torch mocked."""
from unittest.mock import MagicMock, patch

from skills.youtube_transcribe.quality import perplexity
from skills.youtube_transcribe.quality.perplexity import (
    _LANG_MODELS,
    is_perplexity_available_for_lang,
    perplexity_anomaly_score,
)
from skills.youtube_transcribe.utils.output_writer import Segment


def _seg(text: str) -> Segment:
    return Segment(start=0.0, end=1.0, text=text)


def test_unsupported_language_returns_neg_one():
    assert perplexity_anomaly_score([_seg("hello")], "kk") == -1.0


def test_unsupported_lang_via_helper():
    assert is_perplexity_available_for_lang("kk") is False


def test_supported_lang_when_transformers_missing(monkeypatch):
    """English IS in _LANG_MODELS but transformers might not be installed."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "transformers":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    perplexity._get_lm.cache_clear()
    assert is_perplexity_available_for_lang("en") is False


def test_lm_failure_returns_neg_one(monkeypatch):
    """If _get_lm returns None (load failure), return -1.0 sentinel."""
    monkeypatch.setattr(perplexity, "_get_lm", lambda lang: None)
    perplexity._get_lm.cache_clear() if hasattr(perplexity._get_lm, "cache_clear") else None
    score = perplexity_anomaly_score([_seg("hi")], "en")
    assert score == -1.0


def test_normal_text_low_score(monkeypatch):
    """Normal English text: PPL ~50 baseline → score ~0.0 (no penalty)."""
    fake_tok = MagicMock()
    fake_model = MagicMock()
    monkeypatch.setattr(perplexity, "_get_lm", lambda lang: (fake_tok, fake_model))
    monkeypatch.setattr(
        perplexity, "_compute_perplexity",
        lambda text, tok, model: {"hello": 50.0, "world": 60.0, "today": 45.0}.get(text),
    )
    score = perplexity_anomaly_score(
        [_seg("hello"), _seg("world"), _seg("today")],
        "en",
    )
    # mean(50+60+45)/3 = 51.67; (51.67-50)/150 ≈ 0.011
    assert 0.0 <= score < 0.05


def test_medium_perplexity_partial_score(monkeypatch):
    """PPL ~125 → score around 0.5."""
    fake_tok = MagicMock()
    fake_model = MagicMock()
    monkeypatch.setattr(perplexity, "_get_lm", lambda lang: (fake_tok, fake_model))
    monkeypatch.setattr(
        perplexity, "_compute_perplexity",
        lambda text, tok, model: 125.0,
    )
    score = perplexity_anomaly_score([_seg("text")] * 3, "en")
    # (125 - 50) / 150 = 0.5
    assert abs(score - 0.5) < 0.05


def test_garbled_text_high_score(monkeypatch):
    """Garbled text: PPL >=200 → score 1.0 (saturated)."""
    fake_tok = MagicMock()
    fake_model = MagicMock()
    monkeypatch.setattr(perplexity, "_get_lm", lambda lang: (fake_tok, fake_model))
    monkeypatch.setattr(
        perplexity, "_compute_perplexity",
        lambda text, tok, model: 1000.0,
    )
    score = perplexity_anomaly_score([_seg("garbage")] * 3, "en")
    assert score == 1.0  # capped


def test_empty_segments_returns_zero_when_lm_loaded(monkeypatch):
    """Empty / whitespace segments → 0.0, no _compute_perplexity calls."""
    fake_tok = MagicMock()
    fake_model = MagicMock()
    monkeypatch.setattr(perplexity, "_get_lm", lambda lang: (fake_tok, fake_model))
    compute_calls = {"n": 0}

    def fake_compute(text, tok, model):
        compute_calls["n"] += 1
        return 50.0

    monkeypatch.setattr(perplexity, "_compute_perplexity", fake_compute)

    score = perplexity_anomaly_score([_seg("   "), _seg("\n")], "en")
    assert score == 0.0
    assert compute_calls["n"] == 0  # short-circuit on empty texts


def test_compute_returns_none_skipped(monkeypatch):
    """If _compute_perplexity returns None for a segment, that segment is skipped."""
    fake_tok = MagicMock()
    fake_model = MagicMock()
    monkeypatch.setattr(perplexity, "_get_lm", lambda lang: (fake_tok, fake_model))
    # First two return None (e.g., too short), third returns 100
    sequence = iter([None, None, 100.0])
    monkeypatch.setattr(
        perplexity, "_compute_perplexity",
        lambda text, tok, model: next(sequence),
    )

    score = perplexity_anomaly_score(
        [_seg("a"), _seg("b"), _seg("normal text here")],
        "en",
    )
    # Only third value (100) used → (100-50)/150 = 0.333
    assert abs(score - 0.333) < 0.01


def test_all_compute_failures_returns_zero(monkeypatch):
    """If every segment compute returns None, score is 0.0 (nothing to score)."""
    fake_tok = MagicMock()
    fake_model = MagicMock()
    monkeypatch.setattr(perplexity, "_get_lm", lambda lang: (fake_tok, fake_model))
    monkeypatch.setattr(perplexity, "_compute_perplexity", lambda *a: None)

    score = perplexity_anomaly_score([_seg("hi"), _seg("ho")], "en")
    assert score == 0.0


def test_lang_models_includes_english():
    """English must be supported (default model is gpt2)."""
    assert "en" in _LANG_MODELS
    assert _LANG_MODELS["en"] == "gpt2"
