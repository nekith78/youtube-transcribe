"""Extract keyframes from video via ffmpeg.

Output naming: <video_id>_<seconds>.jpg, relative to out_dir/frames/.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _tmp_pattern(out_dir: Path) -> Path:
    """Pattern for ffmpeg output files (overridable in tests)."""
    return out_dir / "tmp_%04d.jpg"


def extract_keyframes(
    video_path: Path,
    start: float,
    end: float,
    count: int,
    out_dir: Path,
    video_id: str,
) -> list[Path]:
    """Extract <count> evenly-spaced keyframes from [start, end] window.

    Files named <video_id>_<sec>.jpg in out_dir.
    Returns list of created file paths.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = max(end - start, 0.1)
    fps = count / duration

    pattern = _tmp_pattern(out_dir)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start),
        "-to", str(end),
        "-i", str(video_path),
        "-vf", f"fps={fps}",
        "-frames:v", str(count),
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
