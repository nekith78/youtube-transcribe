"""Tests for OCR layer (--ocr flag)."""
from pathlib import Path
from unittest.mock import patch

from skills.youtube_transcribe.vision.ocr import ocr_keyframes


def test_ocr_returns_strings_per_keyframe(tmp_path):
    kf1 = tmp_path / "f1.jpg"
    kf2 = tmp_path / "f2.jpg"
    kf1.write_bytes(b"fake jpeg")
    kf2.write_bytes(b"fake jpeg")

    with patch(
        "skills.youtube_transcribe.vision.ocr._run_tesseract",
        side_effect=["import anthropic", "function call"],
    ):
        results = ocr_keyframes([kf1, kf2])

    assert results == ["import anthropic", "function call"]


def test_ocr_skips_unreadable_files(tmp_path):
    kf = tmp_path / "broken.jpg"
    kf.write_bytes(b"")
    with patch(
        "skills.youtube_transcribe.vision.ocr._run_tesseract",
        side_effect=Exception("can't read"),
    ):
        results = ocr_keyframes([kf])
    # Errors → empty string for that frame
    assert results == [""]


def test_ocr_returns_empty_for_empty_input():
    assert ocr_keyframes([]) == []
