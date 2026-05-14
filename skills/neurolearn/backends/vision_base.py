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
