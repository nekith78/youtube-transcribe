"""Tests for DetectionWindow dataclass and Detector Protocol."""
from skills.youtube_transcribe.detection.base import DetectionWindow


def test_window_creation():
    w = DetectionWindow(start=10.0, end=15.0, reason="raw", score=1.0, weight=2.0, phrase="TODO")
    assert w.start == 10.0
    assert w.end == 15.0
    assert w.reason == "raw"


def test_window_priority_score():
    w = DetectionWindow(start=0.0, end=5.0, reason="universal", score=0.7, weight=1.5, phrase="x")
    assert abs(w.priority_score - 1.05) < 1e-6  # 0.7 * 1.5
