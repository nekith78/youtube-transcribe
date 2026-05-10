"""Tests for window merging and bucket-based selection."""
from skills.youtube_transcribe.detection.base import DetectionWindow
from skills.youtube_transcribe.detection.window_merge import (
    merge_overlapping_windows,
    select_windows_by_budget,
)


def test_merge_non_overlapping_unchanged():
    ws = [
        DetectionWindow(0.0, 5.0, "raw", 1.0, 1.0, "a"),
        DetectionWindow(10.0, 15.0, "raw", 1.0, 1.0, "b"),
    ]
    out = merge_overlapping_windows(ws, max_gap=1.0)
    assert len(out) == 2


def test_merge_overlapping_combines():
    ws = [
        DetectionWindow(0.0, 5.0, "raw", 1.0, 1.0, "a"),
        DetectionWindow(4.0, 10.0, "raw", 0.8, 1.0, "b"),
    ]
    out = merge_overlapping_windows(ws, max_gap=0.5)
    assert len(out) == 1
    assert out[0].start == 0.0
    assert out[0].end == 10.0


def test_merge_close_gap_combines():
    ws = [
        DetectionWindow(0.0, 5.0, "raw", 1.0, 1.0, "a"),
        DetectionWindow(5.5, 10.0, "raw", 1.0, 1.0, "b"),
    ]
    out = merge_overlapping_windows(ws, max_gap=1.0)
    assert len(out) == 1


def test_budget_within_returns_all():
    ws = [
        DetectionWindow(0.0, 5.0, "raw", 1.0, 1.0, "a"),
        DetectionWindow(20.0, 25.0, "raw", 1.0, 1.0, "b"),
    ]
    out = select_windows_by_budget(ws, max_windows=10, video_duration=60.0)
    assert len(out) == 2


def test_budget_exceed_picks_best_per_bucket():
    """Видео 60s, бюджет 3 → корзины [0-20, 20-40, 40-60]. В каждой берём best."""
    ws = [
        DetectionWindow(2.0, 4.0, "u", 0.5, 1.0, "low"),
        DetectionWindow(5.0, 7.0, "u", 0.9, 2.0, "high"),  # bucket 0, score*w = 1.8
        DetectionWindow(25.0, 27.0, "u", 0.8, 1.0, "ok"),  # bucket 1
        DetectionWindow(30.0, 32.0, "u", 0.6, 1.0, "less"),
        DetectionWindow(50.0, 52.0, "u", 0.7, 1.0, "fine"),  # bucket 2
    ]
    out = select_windows_by_budget(ws, max_windows=3, video_duration=60.0)
    assert len(out) == 3
    phrases = sorted(w.phrase for w in out)
    assert phrases == ["fine", "high", "ok"]


def test_budget_zero_or_no_video_returns_empty():
    ws = [DetectionWindow(0.0, 5.0, "raw", 1.0, 1.0, "a")]
    assert select_windows_by_budget(ws, max_windows=0, video_duration=60.0) == []
    assert select_windows_by_budget(ws, max_windows=5, video_duration=0.0) == []
