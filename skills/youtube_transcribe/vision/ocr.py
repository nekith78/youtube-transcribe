"""OCR for keyframes — opt-in via --ocr flag.

Tries pytesseract first (requires system `tesseract` binary).
Falls back to easyocr (heavy 60MB model, but no system binary needed).
"""
from __future__ import annotations

from pathlib import Path


def _run_tesseract(image_path: Path) -> str:
    """Single keyframe → text. Override-able for testing."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        return pytesseract.image_to_string(img).strip()
    except ImportError:
        # Fallback to easyocr
        try:
            import easyocr
            reader = easyocr.Reader(["en", "ru"], gpu=False)
            results = reader.readtext(str(image_path), detail=0)
            return " ".join(results)
        except ImportError as e:
            raise ImportError(
                "OCR requires either pytesseract+system tesseract or easyocr. "
                "Install with `uv sync --extra ocr`."
            ) from e


def ocr_keyframes(keyframes: list[Path]) -> list[str]:
    """Returns one OCR'd string per keyframe. Errors → empty string for that frame."""
    out: list[str] = []
    for kf in keyframes:
        try:
            text = _run_tesseract(kf)
        except Exception:
            text = ""
        out.append(text)
    return out
