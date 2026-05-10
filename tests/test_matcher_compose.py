"""Tests for top-level match_segment composition."""
import numpy as np
import pytest

from skills.youtube_transcribe.detection.triggers import LanguageTriggers, TriggerConfig
from skills.youtube_transcribe.detection import matcher
from skills.youtube_transcribe.detection.matcher import match_segment, TriggerMatch


class FakeEncoder:
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


def test_raw_wins_over_universal():
    cfg = TriggerConfig()
    cfg.raw = {"TODO": 2.0}
    cfg.universal = {"work": 1.0}
    cfg.universal_match_threshold = -1.0  # everything matches universal otherwise

    m = match_segment("we have a TODO in this code", cfg)
    assert m is not None
    assert m.reason == "raw"
    assert m.phrase == "todo"
    assert m.weight == 2.0


def test_strict_wins_over_soft():
    cfg = TriggerConfig()
    cfg.languages["ru"] = LanguageTriggers(
        strict={"баг": 1.0},
        soft={"посмотри сюда": 1.0},
    )

    m = match_segment("вот этот баг здесь", cfg)
    assert m is not None
    assert m.reason.startswith("strict:")


def test_no_match_returns_none():
    cfg = TriggerConfig()
    cfg.universal_match_threshold = 2.0
    m = match_segment("completely unrelated text", cfg)
    assert m is None


def test_universal_fallback():
    cfg = TriggerConfig()
    cfg.universal = {"hello": 1.5}
    cfg.universal_match_threshold = -1.0
    m = match_segment("hi there friend", cfg)
    assert m is not None
    assert m.reason == "universal"
    assert m.weight == 1.5
