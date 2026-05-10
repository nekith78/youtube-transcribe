"""Tests for v0.2 pipeline wrapper that adds quality + vision stages."""
from pathlib import Path
from unittest.mock import patch, MagicMock

from skills.youtube_transcribe.pipeline_v02 import apply_v02_stages
from skills.youtube_transcribe.backends.base import TranscriptionResult
from skills.youtube_transcribe.utils.output_writer import Segment


def _result(text="hello world"):
    return TranscriptionResult(
        text=text,
        segments=[Segment(start=0.0, end=5.0, text=text)],
        language_detected="en",
        backend_name="subtitles",
        duration_seconds=5.0,
    )


def test_quality_check_runs_when_enabled():
    cfg = {"quality_check": True, "vision_backend": "off"}
    result = _result()
    with patch(
        "skills.youtube_transcribe.pipeline_v02.HeuristicChecker"
    ) as mock_checker:
        instance = MagicMock()
        instance.check.return_value = MagicMock(
            score=0.85, recommendation="use_as_is", flags=[], breakdown={},
        )
        mock_checker.return_value = instance

        out = apply_v02_stages(
            result=result, cfg=cfg, video_path=None,
            video_id="x", out_dir=Path("/tmp"), source="youtube_auto",
        )
    assert out.quality is not None
    assert out.quality.score == 0.85


def test_quality_check_skipped_when_disabled():
    cfg = {"quality_check": False, "vision_backend": "off"}
    result = _result()
    out = apply_v02_stages(
        result=result, cfg=cfg, video_path=None,
        video_id="x", out_dir=Path("/tmp"), source="youtube_auto",
    )
    assert out.quality is None


def test_vision_skipped_when_off():
    cfg = {"quality_check": False, "vision_backend": "off"}
    result = _result()
    out = apply_v02_stages(
        result=result, cfg=cfg, video_path=Path("/tmp/v.mp4"),
        video_id="x", out_dir=Path("/tmp"), source="whisper",
    )
    assert out.visual_segments == []


def test_vision_runs_when_gemini_and_video_path(tmp_path):
    cfg = {
        "quality_check": False,
        "vision_backend": "gemini",
        "detect_method": "keywords_only",
        "frames_per_window": 1,
        "max_windows_per_video": 5,
    }
    result = _result(text="look here")
    fake_visual = MagicMock()
    fake_visual.start = 0.0
    fake_visual.end = 5.0

    with patch(
        "skills.youtube_transcribe.pipeline_v02.find_detection_windows",
        return_value=[MagicMock(start=0.0, end=5.0, reason="universal", score=0.7,
                                weight=1.0, phrase="look here", priority_score=0.7)],
    ), patch(
        "skills.youtube_transcribe.pipeline_v02.GeminiVisionBackend"
    ) as mock_vis, patch(
        "skills.youtube_transcribe.config.get_api_key",
        return_value="fake_key",
    ):
        mock_vis.return_value.annotate_segments.return_value = [fake_visual]
        out = apply_v02_stages(
            result=result, cfg=cfg, video_path=tmp_path / "v.mp4",
            video_id="x", out_dir=tmp_path, source="whisper",
        )
    assert len(out.visual_segments) == 1
