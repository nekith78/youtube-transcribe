"""Base types for quality check subsystem."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Recommendation = Literal["use_as_is", "fallback_recommended", "low_quality"]
TranscriptSource = Literal["youtube_manual", "youtube_auto", "whisper", "external_asr"]


@dataclass(frozen=True)
class QualityReport:
    """Result of running QualityChecker.check on a transcript."""

    score: float  # 0.0 — garbage, 1.0 — perfect
    breakdown: dict[str, float] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    recommendation: Recommendation = "use_as_is"


class QualityChecker(Protocol):
    """Anything that can score a transcript locally."""

    def check(
        self,
        segments: list,  # list[Segment] from output_writer
        language: str,
        source: TranscriptSource,
    ) -> QualityReport:
        ...
