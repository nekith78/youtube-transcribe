"""Scene boundary detection via PySceneDetect.

Returns scene START timestamps in seconds (excluding the very first scene
which starts at 0.0). These boundaries are used as visual cues for windowing.
"""
from __future__ import annotations

from pathlib import Path


def find_scene_boundaries(video_path: Path, threshold: float = 27.0) -> list[float]:
    """Returns list of scene-change timestamps in seconds.

    threshold: ContentDetector threshold; 27 is PySceneDetect default; lower
    means more sensitive (more boundaries).
    """
    import scenedetect

    scenes = scenedetect.detect(str(video_path), scenedetect.ContentDetector(threshold=threshold))
    # First scene starts at 0 — it's not a boundary, skip it.
    return [start.get_seconds() for start, _end in scenes[1:]]
