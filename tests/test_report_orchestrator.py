"""Tests for report.orchestrator — manifest → PDF glue.

Builds a synthetic batch_dir on disk (manifest.json + SRT + keyframes)
and drives the orchestrator end-to-end. LLM calls are mocked.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from skills.neurolearn.report.orchestrator import (
    ReportResult, _parse_srt, generate_report,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic batch_dir
# ---------------------------------------------------------------------------


def _make_synthetic_batch(tmp_path: Path, *, with_keyframes: bool = True) -> Path:
    """Build a minimal batch_dir resembling what transcribe/batch emit."""
    batch_dir = tmp_path / "batch1"
    (batch_dir / "videos").mkdir(parents=True)
    if with_keyframes:
        (batch_dir / "frames").mkdir(parents=True)

    srt_rel = "videos/01_test.srt"
    srt = batch_dir / srt_rel
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:05,000\nWelcome to the tutorial.\n\n"
        "2\n00:00:05,000 --> 00:00:10,000\nClick Save in the toolbar.\n\n"
        "3\n00:00:10,000 --> 00:00:15,000\nPress Enter to confirm.\n",
        encoding="utf-8",
    )

    if with_keyframes:
        # Create a real JPEG so the renderer can downscale it.
        PIL = pytest.importorskip("PIL")
        from PIL import Image
        img = Image.new("RGB", (1200, 700), color=(100, 150, 200))
        img.save(batch_dir / "frames" / "v_00005.jpg", "JPEG", quality=80)

    manifest = {
        "batch_name": "test-batch",
        "created_at": "2026-05-16T12:00:00Z",
        "source": {"kind": "test"},
        "config": {},
        "stats": {"ok": 1, "failed": 0, "total": 1},
        "videos": [{
            "index": 1,
            "url": "https://example.com/test",
            "video_id": "test123",
            "title": "Test Tutorial Video",
            "channel": "TestChannel",
            "duration_sec": 15,
            "language_detected": "en",
            "files": {"srt": srt_rel, "txt": ""},
            "status": "ok",
            "visual_segments": [
                {
                    "start": 5.0, "end": 10.0,
                    "description": "Save button highlighted",
                    "keyframes": ["frames/v_00005.jpg"],
                    "importance": "high",
                }
            ] if with_keyframes else [],
        }],
    }
    (batch_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return batch_dir


def _fake_llm_response() -> str:
    """Outline-shaped JSON for the mocked LLM."""
    return json.dumps({
        "title": "Test Tutorial",
        "summary": "A test report rendered from a synthetic batch.",
        "sections": [
            {
                "title": "Step 1 — Welcome",
                "summary": "Intro to the tutorial.",
                "key_points": ["Friendly greeting"],
                "image_refs": [],
                "timestamps": ["00:00:00"],
            },
            {
                "title": "Step 2 — Save",
                "summary": "Click Save in the toolbar.",
                "key_points": ["Look for the toolbar"],
                "image_refs": ["frames/v_00005.jpg"],
                "timestamps": ["00:00:05"],
            },
        ],
    })


# ---------------------------------------------------------------------------
# SRT parser
# ---------------------------------------------------------------------------


def test_parse_srt_handles_basic_blocks(tmp_path):
    srt = tmp_path / "x.srt"
    srt.write_text(
        "1\n00:00:00,500 --> 00:00:03,250\nHello world.\n\n"
        "2\n00:00:03,250 --> 00:00:06,000\nSecond line here.\n",
        encoding="utf-8",
    )
    segs = _parse_srt(srt)
    assert len(segs) == 2
    assert segs[0].text == "Hello world."
    assert abs(segs[0].start - 0.5) < 0.01
    assert segs[1].text == "Second line here."


def test_parse_srt_handles_multiline_text(tmp_path):
    srt = tmp_path / "y.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:05,000\nFirst part.\nSecond part.\n",
        encoding="utf-8",
    )
    segs = _parse_srt(srt)
    assert len(segs) == 1
    assert "First part" in segs[0].text
    assert "Second part" in segs[0].text


# ---------------------------------------------------------------------------
# Orchestrator end-to-end (with mocked LLM)
# ---------------------------------------------------------------------------


def test_generate_report_end_to_end_pdf(tmp_path):
    """Full glue: synthetic batch → mocked LLM → real PDF on disk."""
    pytest.importorskip("weasyprint")
    pytest.importorskip("jinja2")

    batch_dir = _make_synthetic_batch(tmp_path)

    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=_fake_llm_response(),
    ):
        result = generate_report(
            batch_dir=batch_dir,
            backend="gemini",
            api_key="fake-key",
            user_filter="",
            include_screenshots=True,
        )

    assert isinstance(result, ReportResult)
    assert result.pdf_path.exists()
    head = result.pdf_path.read_bytes()[:8]
    assert head.startswith(b"%PDF"), f"Not a PDF: {head!r}"

    assert result.section_count == 2
    assert result.video_title == "Test Tutorial Video"
    assert result.report_type in {"tutorial", "vlog", "generic"}
    assert result.target_language == "en"


def test_generate_report_respects_explicit_report_type(tmp_path):
    """--report-type vlog overrides auto-detection."""
    pytest.importorskip("weasyprint")

    batch_dir = _make_synthetic_batch(tmp_path)
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=_fake_llm_response(),
    ):
        result = generate_report(
            batch_dir=batch_dir,
            backend="gemini",
            api_key="fake",
            report_type="vlog",
        )
    assert result.report_type == "vlog"


def test_generate_report_explicit_language_override(tmp_path):
    """--report-language ru overrides the auto-detected lang."""
    pytest.importorskip("weasyprint")

    batch_dir = _make_synthetic_batch(tmp_path)
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=_fake_llm_response(),
    ):
        result = generate_report(
            batch_dir=batch_dir,
            backend="gemini",
            api_key="fake",
            target_language="ru",
        )
    assert result.target_language == "ru"


def test_generate_report_keep_html_writes_sibling(tmp_path):
    pytest.importorskip("weasyprint")

    batch_dir = _make_synthetic_batch(tmp_path)
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=_fake_llm_response(),
    ):
        result = generate_report(
            batch_dir=batch_dir,
            backend="gemini",
            api_key="fake",
            keep_html=True,
        )
    assert result.html_path is not None
    assert result.html_path.exists()
    assert "Test Tutorial" in result.html_path.read_text(encoding="utf-8")


def test_generate_report_no_screenshots_drops_images(tmp_path):
    pytest.importorskip("weasyprint")

    batch_dir = _make_synthetic_batch(tmp_path)
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=_fake_llm_response(),
    ):
        result = generate_report(
            batch_dir=batch_dir,
            backend="gemini",
            api_key="fake",
            include_screenshots=False,
            keep_html=True,
        )
    html_text = result.html_path.read_text(encoding="utf-8")
    assert "<img" not in html_text


def test_generate_report_missing_manifest_raises(tmp_path):
    """Pointed at a non-batch dir → FileNotFoundError with clear msg."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="manifest"):
        generate_report(batch_dir=empty, api_key="x")


def test_generate_report_explicit_output_path(tmp_path):
    """--output overrides the default report path."""
    pytest.importorskip("weasyprint")

    batch_dir = _make_synthetic_batch(tmp_path)
    target = tmp_path / "my-custom" / "out.pdf"
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=_fake_llm_response(),
    ):
        result = generate_report(
            batch_dir=batch_dir,
            backend="gemini",
            api_key="fake",
            output_path=target,
        )
    assert result.pdf_path == target
    assert target.exists()
