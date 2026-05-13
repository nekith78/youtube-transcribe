"""Regression tests for Task 13: _run_batch_pipeline extraction from batch_cmd.

These tests pin down the new module-level function signature so that v0.7
features (research, subscribes) can drive the core pipeline without going
through Click parsing.
"""
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

from skills.youtube_transcribe.utils.resolver import ResolvedTarget


def test_run_batch_pipeline_importable():
    """Function must exist at the documented module path."""
    from skills.youtube_transcribe.transcribe import _run_batch_pipeline  # noqa: F401
    assert callable(_run_batch_pipeline)


def test_run_batch_pipeline_empty_targets_returns_none(tmp_path):
    """No work to do → no batch folder, returns None."""
    from skills.youtube_transcribe.transcribe import _run_batch_pipeline

    cfg = MagicMock(
        default_backend="subtitles", language="auto",
        output_dir=str(tmp_path), keep_audio=False,
        timestamps=True, srt=True, fast_path_enabled=True,
        cookies_file=None,
    )
    out = _run_batch_pipeline(targets=[], cfg=cfg, opts={})
    assert out is None


def test_run_batch_pipeline_returns_batch_dir(tmp_path):
    """With a fake target + mocked run_pipeline, returns Path to batch dir
    and writes manifest.json there."""
    from skills.youtube_transcribe.transcribe import _run_batch_pipeline

    target = ResolvedTarget(
        url="https://youtu.be/aaa0", title="Video 0",
        upload_date=date(2026, 4, 20), duration_sec=60,
        channel="@anth", source="channel", video_id="aaa0",
    )
    cfg = MagicMock(
        default_backend="subtitles", language="auto",
        output_dir=str(tmp_path), keep_audio=False,
        timestamps=True, srt=True, fast_path_enabled=True,
        cookies_file=None,
    )
    fake_result = MagicMock(
        text="hello", segments=[], language_detected="en",
        backend_name="subtitles", duration_seconds=10.0,
        visual_segments=[], quality=None,
    )

    with patch(
        "skills.youtube_transcribe.transcribe.run_pipeline",
        return_value=fake_result,
    ), patch(
        "skills.youtube_transcribe.transcribe.write_txt_with_timestamps"
    ), patch(
        "skills.youtube_transcribe.transcribe.write_srt"
    ), patch(
        "skills.youtube_transcribe.transcribe.write_combined_md"
    ), patch(
        "skills.youtube_transcribe.transcribe.write_manifest_json"
    ) as wmj, patch(
        "skills.youtube_transcribe.transcribe.write_errors_log"
    ):
        out = _run_batch_pipeline(
            targets=[target],
            cfg=cfg,
            opts={"output_dir": str(tmp_path)},
        )

    assert out is not None
    assert isinstance(out, Path)
    assert out.parent == tmp_path
    assert (out / "videos").exists()
    wmj.assert_called_once()
