"""Extract keyframes from video via ffmpeg.

Two extraction modes:

  • `extract_keyframes(start, end, count)` — evenly spaced inside a
    window. Used by smart / standard / premium presets (lectures, reviews,
    arbitrary visual moments).

  • `extract_keyframes_asymmetric(event_ts)` — three offsets relative to
    a speech event: `-1.5s` (before), `+0.3s` (the action — accounts for
    motor lag between speech and click), `+2.0s` (UI settled after). Used
    by the tutorial preset where the interesting frame is offset from
    when the speaker says the action word.

JPEG quality is capped at q:3 (~80% — LLMs don't see the difference)
and width is downscaled to 1280px (UI tutorials don't need 4K). For
text-heavy content (IDE / code) callers can pass `max_width=1920`.

Output naming: <video_id>_<seconds>.jpg under out_dir/frames/.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


# JPEG quality 3 in ffmpeg's -q:v scale (1=best, 31=worst). q:3 maps to
# ~80% quality — visually indistinguishable but 5–10× smaller than PNG.
_DEFAULT_JPEG_QUALITY = 3
# 1280px wide is enough for UI tutorials; bump to 1920 for IDE / code.
_DEFAULT_MAX_WIDTH = 1280


def _tmp_pattern(out_dir: Path) -> Path:
    """Pattern for ffmpeg output files (overridable in tests)."""
    return out_dir / "tmp_%04d.jpg"


def _vf_filter(max_width: int) -> str:
    """Single ffmpeg -vf filter clause that downscales while preserving aspect.
    `-1` height makes ffmpeg compute height to keep aspect ratio."""
    return f"scale='min({max_width},iw)':-2"


def extract_keyframes(
    video_path: Path,
    start: float,
    end: float,
    count: int,
    out_dir: Path,
    video_id: str,
    max_width: int = _DEFAULT_MAX_WIDTH,
    jpeg_quality: int = _DEFAULT_JPEG_QUALITY,
) -> list[Path]:
    """Extract <count> evenly-spaced keyframes from [start, end] window.

    Files named <video_id>_<sec>.jpg in out_dir.
    Returns list of created file paths.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = max(end - start, 0.1)
    fps = count / duration

    pattern = _tmp_pattern(out_dir)
    # `-ss` BEFORE `-i` = fast input seeking (~50ms precision, 100× faster
    # than output seeking). `-q:v` controls JPEG quality. The scale filter
    # downscales — `min(W,iw)` so we don't accidentally upscale tiny inputs.
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start),
        "-to", str(end),
        "-i", str(video_path),
        "-vf", f"fps={fps},{_vf_filter(max_width)}",
        "-frames:v", str(count),
        "-q:v", str(jpeg_quality),
        str(pattern),
    ]
    subprocess.run(cmd, check=True)

    # Rename tmp_NNNN.jpg → <video_id>_<sec>.jpg
    tmp_files = sorted(out_dir.glob("tmp_*.jpg"))
    out_paths: list[Path] = []
    for idx, tmp in enumerate(tmp_files):
        sec = int(start + idx / fps)
        new_path = out_dir / f"{video_id}_{sec:05d}.jpg"
        tmp.rename(new_path)
        out_paths.append(new_path)
    return out_paths


# Default asymmetric offsets — speech-anchored. -1.5s captures the
# "before" state, +0.3s captures the action moment (motor lag between
# speech and physical click is ~200–400ms), +2.0s captures the UI
# settled response. Sourced from tutorial-pipeline production guidance.
_TUTORIAL_OFFSETS = (-1.5, 0.3, 2.0)


def extract_keyframes_asymmetric(
    video_path: Path,
    event_ts: float,
    out_dir: Path,
    video_id: str,
    offsets: tuple[float, ...] = _TUTORIAL_OFFSETS,
    max_width: int = _DEFAULT_MAX_WIDTH,
    jpeg_quality: int = _DEFAULT_JPEG_QUALITY,
) -> list[Path]:
    """Extract one frame per offset relative to `event_ts`.

    `event_ts` is the moment in the video when the speaker said the action
    word. Default offsets `-1.5 / +0.3 / +2.0` give the canonical
    "before / action / after" trio for UI tutorials. Frames written to
    out_dir as <video_id>_<sec>.jpg.

    Negative offsets are clamped to 0.0 (don't seek before video start).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for offset in offsets:
        ts = max(0.0, event_ts + offset)
        # One frame at this exact timestamp via output-frame limit.
        # Each call is a separate ffmpeg invocation — three windows is
        # cheap (each takes ~100ms with input seeking).
        out_path = out_dir / f"{video_id}_{int(ts):05d}.jpg"
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{ts:.3f}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", str(jpeg_quality),
            "-vf", _vf_filter(max_width),
            str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            # Skip frames we can't extract (e.g. past end of video) —
            # never fail the whole annotation pipeline over one frame.
            continue
        if out_path.exists():
            paths.append(out_path)
    return paths
