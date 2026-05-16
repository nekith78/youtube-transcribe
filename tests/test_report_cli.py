"""Tests for the `neurolearn report` CLI command."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from skills.neurolearn.transcribe import cli


def _make_synthetic_batch(tmp_path: Path) -> Path:
    """Mirror the helper from test_report_orchestrator (simplified)."""
    batch_dir = tmp_path / "batch1"
    (batch_dir / "videos").mkdir(parents=True)
    (batch_dir / "frames").mkdir(parents=True)

    srt_rel = "videos/01_test.srt"
    (batch_dir / srt_rel).write_text(
        "1\n00:00:00,000 --> 00:00:05,000\nWelcome.\n\n"
        "2\n00:00:05,000 --> 00:00:10,000\nClick Save.\n",
        encoding="utf-8",
    )

    PIL = pytest.importorskip("PIL")
    from PIL import Image
    Image.new("RGB", (800, 450), color=(80, 120, 200)).save(
        batch_dir / "frames" / "v_00005.jpg", "JPEG", quality=80,
    )

    manifest = {
        "batch_name": "test-batch",
        "videos": [{
            "index": 1,
            "url": "https://example.com/v",
            "video_id": "test123",
            "title": "Test Video",
            "channel": "Ch",
            "duration_sec": 10,
            "language_detected": "en",
            "files": {"srt": srt_rel, "txt": ""},
            "status": "ok",
            "visual_segments": [],
        }],
    }
    (batch_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    return batch_dir


def _fake_llm() -> str:
    return json.dumps({
        "title": "CLI Test",
        "summary": "ok",
        "sections": [{
            "title": "Step 1",
            "summary": "do it",
            "key_points": ["a"],
            "image_refs": [],
            "timestamps": ["00:00:00"],
        }],
    })


def test_report_help_lists_in_top_level():
    """`neurolearn --help` mentions the report subcommand."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "report" in result.output.lower()


def test_report_explicit_batch_dir_renders_pdf(tmp_path, monkeypatch):
    pytest.importorskip("weasyprint")
    pytest.importorskip("jinja2")

    batch_dir = _make_synthetic_batch(tmp_path)

    # CLI tries to load a real API key — mock get_api_key directly.
    monkeypatch.setattr(
        "skills.neurolearn.transcribe.get_api_key",
        lambda *a, **kw: "fake-key",
    )

    runner = CliRunner()
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=_fake_llm(),
    ):
        result = runner.invoke(cli, [
            "report",
            str(batch_dir),
            "--yes",
            "--backend", "gemini",
        ])
    assert result.exit_code == 0, result.output

    # Some PDF landed under the batch_dir.
    pdfs = list(batch_dir.glob("report_*.pdf"))
    assert pdfs, f"No PDFs in {batch_dir}, stdout={result.output}"
    assert pdfs[0].read_bytes()[:4] == b"%PDF"


def test_report_no_manifest_fails_gracefully(tmp_path):
    empty = tmp_path / "no-batch"
    empty.mkdir()
    runner = CliRunner()
    result = runner.invoke(cli, ["report", str(empty), "--yes"])
    # Either missing-deps (exit 4) or no-manifest (exit 3). Most CI
    # boxes have the deps; assert the user got a clear error either way.
    assert result.exit_code in {3, 4}, (result.exit_code, result.output)


def test_report_invalid_prompt_combo(tmp_path, monkeypatch):
    """--prompt and --prompt-file together → exit 2."""
    batch_dir = _make_synthetic_batch(tmp_path)
    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(
        "skills.neurolearn.transcribe.get_api_key",
        lambda *a, **kw: "fake-key",
    )
    runner = CliRunner()
    result = runner.invoke(cli, [
        "report", str(batch_dir), "--yes",
        "--prompt", "x", "--prompt-file", str(prompt_file),
    ])
    assert result.exit_code == 2, result.output


def test_report_keep_html_flag(tmp_path, monkeypatch):
    pytest.importorskip("weasyprint")
    batch_dir = _make_synthetic_batch(tmp_path)
    monkeypatch.setattr(
        "skills.neurolearn.transcribe.get_api_key",
        lambda *a, **kw: "fake-key",
    )
    runner = CliRunner()
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=_fake_llm(),
    ):
        result = runner.invoke(cli, [
            "report", str(batch_dir), "--yes", "--keep-html",
        ])
    assert result.exit_code == 0, result.output
    htmls = list(batch_dir.glob("report_*.html"))
    assert htmls, f"keep-html didn't write HTML, stdout={result.output}"


def test_report_output_flag_writes_to_custom_path(tmp_path, monkeypatch):
    pytest.importorskip("weasyprint")
    batch_dir = _make_synthetic_batch(tmp_path)
    custom_out = tmp_path / "deep" / "nested" / "myreport.pdf"
    monkeypatch.setattr(
        "skills.neurolearn.transcribe.get_api_key",
        lambda *a, **kw: "fake-key",
    )
    runner = CliRunner()
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=_fake_llm(),
    ):
        result = runner.invoke(cli, [
            "report", str(batch_dir), "--yes",
            "--output", str(custom_out),
        ])
    assert result.exit_code == 0, result.output
    assert custom_out.exists()
