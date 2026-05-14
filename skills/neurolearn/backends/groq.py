"""Groq backend — Whisper API on LPU hardware."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from skills.neurolearn.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.neurolearn.config import get_api_key
from skills.neurolearn.utils.output_writer import Segment


def _build_client(api_key: str):
    from groq import Groq
    return Groq(api_key=api_key)


@dataclass
class GroqBackend:
    name: str = field(default="groq", init=False)
    supports_url: bool = field(default=False, init=False)
    supports_local_file: bool = field(default=True, init=False)

    model: str = "whisper-large-v3-turbo"

    def is_configured(self) -> tuple[bool, str | None]:
        if not get_api_key("groq"):
            return False, (
                "GROQ_API_KEY is not set. Get one at https://console.groq.com/keys "
                "and register via `neurolearn config set-key groq`."
            )
        return True, None

    def transcribe(
        self,
        audio_or_url: str | Path,
        *,
        language: str = "auto",
        **opts,
    ) -> TranscriptionResult:
        audio = Path(audio_or_url)
        if not audio.exists():
            raise BackendError(f"Audio file not found: {audio}")

        key = get_api_key("groq")
        if not key:
            raise BackendNotConfigured("GROQ_API_KEY missing.")

        client = _build_client(key)
        lang = None if language == "auto" else language

        try:
            with audio.open("rb") as f:
                resp = client.audio.transcriptions.create(
                    file=(audio.name, f.read()),
                    model=self.model,
                    language=lang,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
        except Exception as e:
            raise BackendError(f"Groq API error: {e}") from e

        segments_data = getattr(resp, "segments", None) or []
        segments = [
            Segment(
                start=float(s.get("start", 0.0)) if isinstance(s, dict) else float(s.start),
                end=float(s.get("end", 0.0)) if isinstance(s, dict) else float(s.end),
                text=(s.get("text") if isinstance(s, dict) else s.text).strip(),
            )
            for s in segments_data
        ]

        return TranscriptionResult(
            text=getattr(resp, "text", "").strip(),
            segments=segments,
            language_detected=getattr(resp, "language", None),
            backend_name=self.name,
            duration_seconds=float(getattr(resp, "duration", 0.0) or 0.0),
        )
