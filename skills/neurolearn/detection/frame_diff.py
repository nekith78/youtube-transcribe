"""Frame difference detection via perceptual hashing (imagehash).

Used inside trigger windows to find sub-moments where visuals actually change
(vs. talking-head with static screen).
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FrameDiff:
    timestamp: float
    hamming_distance: int       # 0 = identical, ~64 = completely different


def _extract_frame_hashes(video_path: Path, start: float, end: float, fps: float = 1.0):
    """Use ffmpeg to dump frames at fps, hash each. Returns list[(timestamp, hash)]."""
    import imagehash
    from PIL import Image

    out: list[tuple[float, object]] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(start), "-to", str(end),
            "-i", str(video_path),
            "-vf", f"fps={fps}",
            str(tmp_dir / "frame_%04d.jpg"),
        ]
        subprocess.run(cmd, check=True)
        files = sorted(tmp_dir.glob("frame_*.jpg"))
        for idx, f in enumerate(files):
            img = Image.open(f)
            h = imagehash.phash(img)
            timestamp = start + idx / fps
            out.append((timestamp, h))
    return out


def detect_frame_changes_in_window(
    video_path: Path,
    start: float,
    end: float,
    threshold: int = 20,
    fps: float = 1.0,
) -> list[FrameDiff]:
    """Returns frame timestamps where visual changed substantially vs. previous frame.

    threshold: hamming distance cut-off (0..64). 20 ≈ noticeable change.
    """
    hashes = _extract_frame_hashes(video_path, start, end, fps=fps)
    if len(hashes) < 2:
        return []
    out: list[FrameDiff] = []
    for i in range(1, len(hashes)):
        prev_t, prev_h = hashes[i - 1]
        cur_t, cur_h = hashes[i]
        dist = cur_h - prev_h
        if dist >= threshold:
            out.append(FrameDiff(timestamp=cur_t, hamming_distance=int(dist)))
    return out
