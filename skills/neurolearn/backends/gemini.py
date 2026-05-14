"""Gemini backend — Google AI Studio (google-genai 2.x)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from skills.neurolearn.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.neurolearn.config import get_api_key
from skills.neurolearn.utils.output_writer import Segment


_PROMPT = """\
Transcribe this audio precisely. Return ONLY valid JSON in this exact shape:
{
  "language": "<2-letter ISO code or 'unknown'>",
  "segments": [
    {"start": <seconds, float>, "end": <seconds, float>, "text": "<utterance>"},
    ...
  ]
}
Use precise timestamps. Do not add commentary, do not wrap in markdown fences."""


def _build_client(api_key: str):
    from google import genai
    return genai.Client(api_key=api_key)


def _extract_json(text: str) -> dict:
    """Strip optional markdown fences, parse JSON."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


@dataclass
class GeminiBackend:
    name: str = field(default="gemini", init=False)
    supports_url: bool = field(default=False, init=False)
    supports_local_file: bool = field(default=True, init=False)

    model: str = "gemini-2.5-flash"
    language_hint: str = "auto"

    def is_configured(self) -> tuple[bool, str | None]:
        key = get_api_key("gemini")
        if not key:
            return False, (
                "GEMINI_API_KEY is not set. Get a key at https://aistudio.google.com/apikey "
                "and register it via `neurolearn config set-key gemini`."
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

        api_key = get_api_key("gemini")
        if not api_key:
            raise BackendNotConfigured("GEMINI_API_KEY missing.")

        client = _build_client(api_key)
        try:
            uploaded = client.files.upload(file=str(audio))
            response = client.models.generate_content(
                model=self.model,
                contents=[_PROMPT, uploaded],
            )
        except Exception as e:
            raise BackendError(f"Gemini API error: {e}") from e

        raw_text = getattr(response, "text", "") or ""
        try:
            data = _extract_json(raw_text)
        except json.JSONDecodeError as e:
            raise BackendError(
                f"Gemini returned a non-JSON response. Try another backend or retry. "
                f"Error: {e}"
            ) from e

        segments: list[Segment] = []
        for s in data.get("segments", []):
            segments.append(Segment(
                start=float(s.get("start", 0.0)),
                end=float(s.get("end", 0.0)),
                text=str(s.get("text", "")).strip(),
            ))

        text = " ".join(s.text for s in segments)
        return TranscriptionResult(
            text=text,
            segments=segments,
            language_detected=data.get("language"),
            backend_name=self.name,
            duration_seconds=segments[-1].end if segments else 0.0,
        )
