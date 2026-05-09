"""Tests for the `batch` sub-command (Task 20B).

All external I/O is mocked:
- `resolve` – returns pre-built ResolvedTarget lists
- `run_pipeline` – returns a mock TranscriptionResult or raises
- Writer functions – patched to avoid real file I/O
"""
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from skills.youtube_transcribe.transcribe import cli
from skills.youtube_transcribe.utils.resolver import ResolvedTarget


def _target(idx: int) -> ResolvedTarget:
    return ResolvedTarget(
        url=f"https://youtu.be/aaa{idx}", title=f"Video {idx}",
        upload_date=date(2026, 4, 20), duration_sec=60,
        channel="@anth", source="channel", video_id=f"aaa{idx}",
    )


def _ok_result(idx: int):
    return MagicMock(text=f"text {idx}", segments=[],
                     language_detected="en", backend_name="subtitles",
                     duration_seconds=10.0)


def _patch_writers():
    return [
        patch("skills.youtube_transcribe.transcribe.write_txt_with_timestamps"),
        patch("skills.youtube_transcribe.transcribe.write_srt"),
        patch("skills.youtube_transcribe.transcribe.write_combined_md"),
        patch("skills.youtube_transcribe.transcribe.write_manifest_json"),
        patch("skills.youtube_transcribe.transcribe.write_errors_log"),
    ]


def test_batch_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["batch", "--help"])
    assert result.exit_code == 0
    assert "--limit" in result.output
    assert "--from-file" in result.output
    assert "--fail-fast" in result.output


def test_batch_continue_on_error_collects_failures(tmp_path):
    targets = [_target(0), _target(1), _target(2)]
    cfg = MagicMock(default_backend="subtitles", language="auto",
                    output_dir=str(tmp_path), keep_audio=False,
                    timestamps=True, srt=True)
    runner = CliRunner()
    patches = _patch_writers()

    def pipeline_side_effect(target, *_a, **_k):
        if target.video_id == "aaa1":
            from skills.youtube_transcribe.backends.base import BackendError
            raise BackendError("HTTP 403")
        return _ok_result(int(target.video_id[-1]))

    with patch("skills.youtube_transcribe.transcribe.run_wizard"), \
         patch("skills.youtube_transcribe.transcribe.CONFIG_PATH") as cp, \
         patch("skills.youtube_transcribe.transcribe.load_config", return_value=cfg), \
         patch("skills.youtube_transcribe.transcribe.resolve", return_value=targets), \
         patch("skills.youtube_transcribe.transcribe.run_pipeline",
               side_effect=pipeline_side_effect) as rp, \
         patches[0], patches[1], \
         patches[2] as wcm, patches[3] as wmj, patches[4] as wel:
        cp.exists.return_value = True
        wcm.return_value = tmp_path / "combined.md"
        wmj.return_value = tmp_path / "manifest.json"
        wel.return_value = tmp_path / "errors.log"
        result = runner.invoke(cli, [
            "batch",
            "https://youtu.be/aaa0", "https://youtu.be/aaa1", "https://youtu.be/aaa2",
            "--backend", "subtitles",
            "--output-dir", str(tmp_path),
        ])

    assert result.exit_code == 0, result.output
    assert rp.call_count == 3                  # все 3 пробовали
    wcm.assert_called_once()
    wmj.assert_called_once()
    wel.assert_called_once()                   # был 1 fail → errors.log создан


def test_batch_fail_fast_aborts_on_first_error(tmp_path):
    targets = [_target(0), _target(1), _target(2)]
    cfg = MagicMock(default_backend="subtitles", language="auto",
                    output_dir=str(tmp_path), keep_audio=False,
                    timestamps=True, srt=True)
    runner = CliRunner()
    patches = _patch_writers()

    def pipeline_side_effect(target, *_a, **_k):
        if target.video_id == "aaa0":
            from skills.youtube_transcribe.backends.base import BackendError
            raise BackendError("nope")
        return _ok_result(0)

    with patch("skills.youtube_transcribe.transcribe.run_wizard"), \
         patch("skills.youtube_transcribe.transcribe.CONFIG_PATH") as cp, \
         patch("skills.youtube_transcribe.transcribe.load_config", return_value=cfg), \
         patch("skills.youtube_transcribe.transcribe.resolve", return_value=targets), \
         patch("skills.youtube_transcribe.transcribe.run_pipeline",
               side_effect=pipeline_side_effect) as rp, \
         patches[0], patches[1], patches[2], patches[3], patches[4]:
        cp.exists.return_value = True
        result = runner.invoke(cli, [
            "batch", "https://youtu.be/aaa0", "https://youtu.be/aaa1",
            "--fail-fast",
            "--output-dir", str(tmp_path),
        ])

    assert result.exit_code == 4
    assert rp.call_count == 1                  # на первой ошибке остановились


def test_batch_from_file_only(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("https://youtu.be/aaa0\n", encoding="utf-8")
    cfg = MagicMock(default_backend="subtitles", language="auto",
                    output_dir=str(tmp_path), keep_audio=False,
                    timestamps=True, srt=True)
    runner = CliRunner()
    patches = _patch_writers()

    with patch("skills.youtube_transcribe.transcribe.run_wizard"), \
         patch("skills.youtube_transcribe.transcribe.CONFIG_PATH") as cp, \
         patch("skills.youtube_transcribe.transcribe.load_config", return_value=cfg), \
         patch("skills.youtube_transcribe.transcribe.resolve",
               return_value=[_target(0)]) as r, \
         patch("skills.youtube_transcribe.transcribe.run_pipeline",
               return_value=_ok_result(0)), \
         patches[0], patches[1], patches[2], patches[3], patches[4]:
        cp.exists.return_value = True
        result = runner.invoke(cli, [
            "batch", "--from-file", str(f),
            "--output-dir", str(tmp_path),
        ])

    assert result.exit_code == 0, result.output
    # Resolver вызван с inputs=[] и from_file=Path(f)
    args, kwargs = r.call_args
    assert args[0] == [] or kwargs.get("inputs") == []
