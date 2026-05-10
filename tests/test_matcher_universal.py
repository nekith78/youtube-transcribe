"""Tests for universal matching via multilingual embeddings.

Encoder mocked via monkeypatch — real model only in e2e."""
import numpy as np
import pytest

from skills.youtube_transcribe.detection.triggers import TriggerConfig
from skills.youtube_transcribe.detection import matcher


class FakeEncoder:
    """Deterministic stub: hash(text) → seeded vector."""

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        out = []
        for t in texts:
            rng = np.random.default_rng(hash(t.lower()) % (2**32))
            v = rng.standard_normal(384).astype(np.float32)
            v /= np.linalg.norm(v) + 1e-9
            out.append(v)
        return np.array(out)


@pytest.fixture(autouse=True)
def patch_encoder(monkeypatch):
    monkeypatch.setattr(matcher, "_get_encoder", lambda: FakeEncoder())


def _make_cfg():
    cfg = TriggerConfig()
    cfg.universal = {"look here": 1.0, "function": 1.5}
    cfg.universal_match_threshold = -1.0  # always match (deterministic stub)
    return cfg


def test_universal_returns_some_match():
    cfg = _make_cfg()
    res = matcher._match_universal("hello there", cfg)
    assert res is not None
    phrase, score, weight = res
    assert phrase in cfg.universal
    assert weight == cfg.universal[phrase]


def test_universal_empty_phrases_returns_none():
    cfg = TriggerConfig()
    cfg.universal = {}
    assert matcher._match_universal("hello", cfg) is None


def test_universal_high_threshold_no_match(monkeypatch):
    cfg = _make_cfg()
    cfg.universal_match_threshold = 2.0  # impossibly high
    assert matcher._match_universal("hello there", cfg) is None
