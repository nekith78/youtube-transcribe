"""Vision backend Protocol + VisualSegment data type."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from skills.neurolearn.detection.base import DetectionWindow

Importance = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class VisualSegment:
    """One annotated visual moment."""
    start: float
    end: float
    description: str
    keyframes: list[str]               # relative paths to jpg files
    detected_objects: list[str] = field(default_factory=list)
    trigger_reason: str = ""
    importance: Importance = "medium"
    # 0.0–1.0 — how sure the model is about its description.
    # 1.0 = transcript + frames unambiguously confirm; 0.4 = uncertain which
    # element; 0.0 = action not visible. Drives Claude-fallback escalation
    # in the tutorial / smart pipelines (see pipeline_v02.apply_v02_stages).
    confidence: float = 1.0
    # True when the model itself flagged a frame as needing zoom/refinement
    # (e.g. small text it couldn't read). Also drives Claude fallback.
    needs_refinement: bool = False


class VisionBackend(Protocol):
    """Multimodal LLM that can describe video+audio together."""

    def annotate_segments(
        self,
        video_path: Path,
        windows: list[DetectionWindow],
        prompt_template: str,
        language: str,
        video_id: str,
        out_dir: Path,
    ) -> list[VisualSegment]:
        ...
