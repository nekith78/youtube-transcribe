"""Tests for report.renderer — HTML/PDF generation from Outline.

The renderer takes a populated Outline + the source batch_dir (for
image resolution) and produces an HTML string + an optional PDF.

WeasyPrint and Pillow are optional deps gated on the `report` extra;
PDF-touching tests skip if weasyprint isn't installed locally.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from skills.neurolearn.report.outliner import Outline, Section
from skills.neurolearn.report.renderer import (
    downscale_image, render_html, render_pdf,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_outline() -> Outline:
    return Outline(
        title="My Test Tutorial",
        summary="A short test outline for unit-testing the renderer.",
        sections=[
            Section(
                title="Step 1 — Open the panel",
                summary="Click the gear icon to open Settings.",
                key_points=[
                    "Look for the gear in the top-right corner.",
                    "The panel slides in from the right.",
                ],
                image_refs=["frames/v_00030.jpg"],
                timestamps=["00:00:30"],
            ),
            Section(
                title="Step 2 — Save preferences",
                summary="Hit Save and confirm.",
                key_points=["Press Cmd+S", "Confirm in the dialog"],
                image_refs=[],
                timestamps=["00:01:15"],
            ),
        ],
    )


def _make_dummy_image(path: Path, size=(1600, 900)) -> Path:
    """Create a real JPEG so the image processor can read it."""
    PIL = pytest.importorskip("PIL")
    from PIL import Image
    img = Image.new("RGB", size, color=(120, 180, 240))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=85)
    return path


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def test_render_html_basic(tmp_path):
    """Generated HTML contains the outline's title, summary, sections."""
    outline = _sample_outline()
    html = render_html(outline, batch_dir=tmp_path)
    assert "My Test Tutorial" in html
    assert "Open the panel" in html
    assert "Save preferences" in html
    assert "00:00:30" in html
    # Key points should appear as list items.
    assert "Press Cmd+S" in html


def test_render_html_no_sections(tmp_path):
    """Empty outline still renders — no crashes."""
    outline = Outline(title="Empty report", summary="No content.")
    html = render_html(outline, batch_dir=tmp_path)
    assert "Empty report" in html
    assert "<html" in html.lower()


def test_render_html_includes_toc(tmp_path):
    """Outline with multiple sections gets a TOC in the HTML."""
    outline = _sample_outline()
    html = render_html(outline, batch_dir=tmp_path)
    # The TOC anchor / heading must be present.
    assert "Table of Contents" in html or "contents" in html.lower()


def test_render_html_no_screenshots_flag(tmp_path):
    """include_screenshots=False drops all <img> tags."""
    outline = _sample_outline()
    # Need a real image for the include-screenshots=True path to make
    # sense — but the False path doesn't care.
    html = render_html(
        outline, batch_dir=tmp_path, include_screenshots=False,
    )
    assert "<img" not in html


def test_render_html_with_screenshot(tmp_path):
    """include_screenshots=True + valid image_refs → <img> tag in HTML."""
    img_path = tmp_path / "frames" / "v_00030.jpg"
    _make_dummy_image(img_path)

    outline = _sample_outline()
    html = render_html(outline, batch_dir=tmp_path, include_screenshots=True)
    # The image src must reference our downscaled path (we embed as
    # data URI or as a relative file path — accept either).
    assert "<img" in html
    # The downscaled image landed somewhere — either data: URI or file://
    assert ("data:image" in html) or ("v_00030" in html)


def test_render_html_max_images_caps(tmp_path):
    """When sections reference many images, max_images limits how many
    actually land in the HTML."""
    # Build a heavier outline: 5 images per section.
    sections = []
    for i in range(5):
        img_name = f"frames/img_{i:02d}.jpg"
        _make_dummy_image(tmp_path / img_name)
        sections.append(Section(
            title=f"Section {i}", image_refs=[img_name], timestamps=["00:00:00"],
        ))
    outline = Outline(title="Many", summary="lots", sections=sections)
    html = render_html(
        outline, batch_dir=tmp_path, include_screenshots=True, max_images=2,
    )
    # Only 2 <img> tags should make it in.
    assert html.count("<img") == 2


# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------


def test_downscale_image_reduces_width(tmp_path):
    """downscale_image returns bytes of a smaller image."""
    src = tmp_path / "src.jpg"
    _make_dummy_image(src, size=(2400, 1350))    # 2.7MP
    out_bytes = downscale_image(src, max_width=1000)
    assert isinstance(out_bytes, (bytes, bytearray))
    # Reopen the result and verify smaller than source.
    from PIL import Image
    img = Image.open(io.BytesIO(out_bytes))
    assert img.width <= 1000
    assert img.height < 1350


def test_downscale_image_skips_when_already_small(tmp_path):
    """Already-small images pass through without upscaling."""
    src = tmp_path / "small.jpg"
    _make_dummy_image(src, size=(400, 300))
    out_bytes = downscale_image(src, max_width=1000)
    from PIL import Image
    img = Image.open(io.BytesIO(out_bytes))
    # Width must NOT have been upscaled.
    assert img.width == 400


def test_downscale_image_missing_returns_none(tmp_path):
    """Bad path → None (caller is responsible for skipping the image)."""
    result = downscale_image(tmp_path / "does-not-exist.jpg", max_width=1000)
    assert result is None


# ---------------------------------------------------------------------------
# PDF rendering — needs weasyprint installed
# ---------------------------------------------------------------------------


def test_render_pdf_produces_file(tmp_path):
    """End-to-end: render_pdf writes a non-empty PDF to disk."""
    pytest.importorskip("weasyprint")

    outline = _sample_outline()
    out = tmp_path / "report.pdf"
    result = render_pdf(outline, output_path=out, batch_dir=tmp_path)
    assert result == out
    assert out.exists()
    # PDF magic bytes: %PDF
    head = out.read_bytes()[:8]
    assert head.startswith(b"%PDF"), f"Not a PDF: {head!r}"


def test_render_pdf_with_keep_html(tmp_path):
    """keep_html=True writes the intermediate HTML alongside the PDF."""
    pytest.importorskip("weasyprint")

    outline = _sample_outline()
    out = tmp_path / "report.pdf"
    render_pdf(outline, output_path=out, batch_dir=tmp_path, keep_html=True)
    html_file = out.with_suffix(".html")
    assert html_file.exists()
    assert "My Test Tutorial" in html_file.read_text(encoding="utf-8")


def test_render_pdf_overwrites_existing(tmp_path):
    """Re-running on the same path overwrites (no FileExistsError)."""
    pytest.importorskip("weasyprint")

    outline = _sample_outline()
    out = tmp_path / "report.pdf"
    render_pdf(outline, output_path=out, batch_dir=tmp_path)
    first_size = out.stat().st_size
    # Re-render with a slightly different outline.
    outline.title = "Updated title"
    render_pdf(outline, output_path=out, batch_dir=tmp_path)
    assert out.exists()
    assert out.stat().st_size > 0
