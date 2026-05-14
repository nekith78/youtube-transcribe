"""Custom backend — generic OpenAI-compatible endpoint.

For users running LiteLLM, vLLM, Deepgram-OpenAI bridge, or any other
service that speaks the OpenAI Whisper transcription API.

Configuration (config.toml [custom] section):
  base_url  — full base URL of the OpenAI-compatible API
  model     — model name to pass to the API

API key comes from CUSTOM_API_KEY (env var or ~/.neurolearn/.env).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skills.neurolearn.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.neurolearn.config import get_api_key
from skills.neurolearn.utils.output_writer import Segment


def _build_client(api_key: str, base_url: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=base_url)


@dataclass
class CustomBackend:
    name: str = "custom"
    supports_url: bool = False
    supports_local_file: bool = True

    base_url: str = ""
    model: str = ""

    def is_configured(self) -> tuple[bool, str | None]:
        if not self.base_url:
            return False, (
                "base_url is not set for custom backend. "
                "Set: `neurolearn config set custom.base_url <URL>`."
            )
        if not self.model:
            return False, (
                "model is not set for custom backend. "
                "Set: `neurolearn config set custom.model <NAME>`."
            )
        if not get_api_key("custom"):
            return False, (
                "CUSTOM_API_KEY is not set. "
                "Register via `neurolearn config set-key custom`."
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

        ok, reason = self.is_configured()
        if not ok:
            raise BackendNotConfigured(reason or "")

        client = _build_client(get_api_key("custom"), self.base_url)  # type: ignore[arg-type]
        lang = None if language == "auto" else language

        try:
            with audio.open("rb") as f:
                resp = client.audio.transcriptions.create(
                    file=f,
                    model=self.model,
                    language=lang,
                    response_format="verbose_json",
                )
        except Exception as e:
            raise BackendError(f"Custom backend API error: {e}") from e

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
