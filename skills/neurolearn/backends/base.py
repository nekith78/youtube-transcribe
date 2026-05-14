"""Base abstractions for all transcription backends."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from skills.neurolearn.utils.output_writer import Segment


class BackendError(Exception):
    """Generic backend failure."""


class BackendNotConfigured(BackendError):
    """Raised when a backend is missing its API key or required config."""


@dataclass
class TranscriptionResult:
    text: str
    segments: list[Segment]
    language_detected: str | None
    backend_name: str
    duration_seconds: float
    # === v0.2 ===
    quality: object | None = None                           # QualityReport | None
    visual_segments: list = field(default_factory=list)     # list[VisualSegment]


@runtime_checkable
class Transcriber(Protocol):
    name: str
    supports_url: bool       # True if backend can take a URL directly (subtitles)
    supports_local_file: bool

    def is_configured(self) -> tuple[bool, str | None]:
        """Return (True, None) if ready; (False, reason) otherwise."""
        ...

    def transcribe(
        self,
        audio_or_url: str | Path,
        *,
        language: str = "auto",
        **opts,
    ) -> TranscriptionResult:
        ...
