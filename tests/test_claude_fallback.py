"""Tests for the Claude-fallback refinement step in pipeline_v02.

When Gemini returns visual segments with confidence < 0.7 or
needs_refinement=True, the orchestrator re-processes those (and only
those) windows through Claude.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

from skills.neurolearn.backends.vision_base import VisualSegment
from skills.neurolearn.detection.base import DetectionWindow
from skills.neurolearn.pipeline_v02 import _refine_low_confidence_with_claude


def _seg(*, start, end, desc, conf=1.0, needs=False, kf=("frames/x.jpg",)):
    return VisualSegment(
        start=start, end=end, description=desc,
        keyframes=list(kf), detected_objects=[],
        trigger_reason="raw", importance="medium",
        confidence=conf, needs_refinement=needs,
    )


def _win(start, end):
    return DetectionWindow(
        start=start, end=end, reason="raw",
        score=0.8, weight=1.0, phrase="x",
    )


def test_no_low_confidence_returns_visuals_unchanged(tmp_path):
    """All segments confident → Claude is never invoked."""
    visuals = [
        _seg(start=10, end=15, desc="A", conf=0.9),
        _seg(start=20, end=25, desc="B", conf=0.85),
    ]
    windows = [_win(10, 15), _win(20, 25)]
    with patch(
        "skills.neurolearn.vision.claude_vision.ClaudeVisionBackend"
    ) as MockCls:
        out = _refine_low_confidence_with_claude(
            visuals=visuals, windows=windows, video_path=Path("v.mp4"),
            api_key="x", prompt_template="t", language="en",
            video_id="v", out_dir=tmp_path, frames_per_window=3,
        )
    MockCls.assert_not_called()
    assert out == visuals


def test_low_confidence_segment_refined(tmp_path):
    """Segment with confidence=0.5 → Claude is invoked, result replaces it."""
    visuals = [
        _seg(start=10, end=15, desc="A", conf=0.9),
        _seg(start=20, end=25, desc="B-uncertain", conf=0.5),
        _seg(start=30, end=35, desc="C", conf=0.95),
    ]
    windows = [_win(10, 15), _win(20, 25), _win(30, 35)]

    refined_seg = _seg(start=20, end=25, desc="B-refined-by-claude", conf=0.98)
    fake_backend = MagicMock()
    fake_backend.annotate_segments.return_value = [refined_seg]

    with patch(
        "skills.neurolearn.vision.claude_vision.ClaudeVisionBackend",
        return_value=fake_backend,
    ):
        out = _refine_low_confidence_with_claude(
            visuals=visuals, windows=windows, video_path=Path("v.mp4"),
            api_key="x", prompt_template="t", language="en",
            video_id="v", out_dir=tmp_path, frames_per_window=3,
        )

    fake_backend.annotate_segments.assert_called_once()
    # Only the uncertain window was sent for refinement.
    sent_windows = fake_backend.annotate_segments.call_args.kwargs["windows"]
    assert len(sent_windows) == 1
    assert sent_windows[0].start == 20

    # Original segments at confident slots untouched; uncertain slot replaced.
    assert out[0].description == "A"
    assert out[1].description == "B-refined-by-claude"
    assert out[2].description == "C"


def test_needs_refinement_flag_triggers_claude(tmp_path):
    """needs_refinement=True triggers Claude even when confidence is high."""
    visuals = [
        _seg(start=10, end=15, desc="A-small-text", conf=0.92, needs=True),
    ]
    windows = [_win(10, 15)]
    refined = _seg(start=10, end=15, desc="A-claude-read-the-text", conf=1.0)
    fake_backend = MagicMock()
    fake_backend.annotate_segments.return_value = [refined]

    with patch(
        "skills.neurolearn.vision.claude_vision.ClaudeVisionBackend",
        return_value=fake_backend,
    ):
        out = _refine_low_confidence_with_claude(
            visuals=visuals, windows=windows, video_path=Path("v.mp4"),
            api_key="x", prompt_template="t", language="en",
            video_id="v", out_dir=tmp_path, frames_per_window=3,
        )
    assert out[0].description == "A-claude-read-the-text"


def test_claude_error_keeps_original_visuals(tmp_path):
    """If ClaudeVisionBackend throws, original Gemini segments survive."""
    visuals = [_seg(start=10, end=15, desc="A-original", conf=0.3)]
    windows = [_win(10, 15)]
    fake_backend = MagicMock()
    fake_backend.annotate_segments.side_effect = RuntimeError("anthropic API down")

    with patch(
        "skills.neurolearn.vision.claude_vision.ClaudeVisionBackend",
        return_value=fake_backend,
    ):
        out = _refine_low_confidence_with_claude(
            visuals=visuals, windows=windows, video_path=Path("v.mp4"),
            api_key="x", prompt_template="t", language="en",
            video_id="v", out_dir=tmp_path, frames_per_window=3,
        )
    assert out == visuals
    assert out[0].description == "A-original"


def test_empty_visuals_short_circuits(tmp_path):
    """No visuals to process → no Claude call, returns the empty list."""
    with patch(
        "skills.neurolearn.vision.claude_vision.ClaudeVisionBackend"
    ) as MockCls:
        out = _refine_low_confidence_with_claude(
            visuals=[], windows=[], video_path=Path("v.mp4"),
            api_key="x", prompt_template="t", language="en",
            video_id="v", out_dir=tmp_path, frames_per_window=3,
        )
    MockCls.assert_not_called()
    assert out == []
