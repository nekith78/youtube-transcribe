"""AssemblyAI backend — best/nano speech models.

Uses assemblyai>=0.64.0 SDK.
API:
    aai.settings.api_key = key
    aai.Transcriber(config=aai.TranscriptionConfig(...)).transcribe(path)

Utterance timestamps come back in **milliseconds**; we convert to seconds
before building Segment objects.

speaker_labels NOT enabled in v1.
"""
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


def _build_transcriber(api_key: str, model: str):
    """Lazy-import assemblyai and return a configured Transcriber instance."""
    import assemblyai as aai  # noqa: PLC0415

    aai.settings.api_key = api_key

    speech_model = aai.SpeechModel.best if model == "best" else aai.SpeechModel.nano
    config = aai.TranscriptionConfig(
        speech_model=speech_model,
        language_detection=True,
    )
    return aai.Transcriber(config=config)


@dataclass
class AssemblyAIBackend:
    name: str = field(default="assemblyai", init=False)
    supports_url: bool = field(default=False, init=False)
    supports_local_file: bool = field(default=True, init=False)

    model: str = "best"

    def is_configured(self) -> tuple[bool, str | None]:
        if not get_api_key("assemblyai"):
            return False, (
                "ASSEMBLYAI_API_KEY is not set. Get one at https://www.assemblyai.com/dashboard/signup "
                "and register via `neurolearn config set-key assemblyai`."
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

        key = get_api_key("assemblyai")
        if not key:
            raise BackendNotConfigured("ASSEMBLYAI_API_KEY missing.")

        transcriber = _build_transcriber(key, self.model)
        try:
            transcript = transcriber.transcribe(str(audio))
        except Exception as e:
            raise BackendError(f"AssemblyAI API error: {e}") from e

        # Check for transcription error status (error is a str when set, None otherwise)
        error_msg = getattr(transcript, "error", None)
        if isinstance(error_msg, str) and error_msg:
            raise BackendError(f"AssemblyAI transcription failed: {error_msg}")

        # Convert utterances from ms to seconds
        utterances = getattr(transcript, "utterances", None) or []
        segments: list[Segment] = []
        for u in utterances:
            segments.append(Segment(
                start=float(u.start) / 1000.0,
                end=float(u.end) / 1000.0,
                text=str(u.text).strip(),
            ))

        return TranscriptionResult(
            text=str(getattr(transcript, "text", "") or "").strip(),
            segments=segments,
            language_detected=getattr(transcript, "language_code", None),
            backend_name=self.name,
            duration_seconds=float(getattr(transcript, "audio_duration", 0.0) or 0.0),
        )
