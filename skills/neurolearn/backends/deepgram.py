"""Deepgram Nova-3 backend — REST pre-recorded transcription.

Uses deepgram-sdk>=7.x.
API path: client.listen.v1.media.transcribe_file(request=bytes_data, ...)
Response: Pydantic model accessed via .results.channels[0].alternatives[0].words

Word-level → segment grouping strategy (in priority order):
  1. Sentence-ending punctuation (.  !  ?  …) on the word itself.
  2. Pause gap >1.0 s between consecutive words.
  3. Hard cap of 15 words per segment.
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

_SENTENCE_ENDS = (".", "!", "?", "…")
_GAP_THRESHOLD = 1.0  # seconds
_MAX_WORDS_PER_SEGMENT = 15


def _build_client(api_key: str):
    from deepgram import DeepgramClient
    return DeepgramClient(api_key=api_key)


def _group_words_into_segments(words: list) -> list[Segment]:
    """Group word-level Deepgram output into sentence-level Segments.

    Each item in *words* is expected to expose .word, .punctuated_word (optional),
    .start, .end (Pydantic model fields from deepgram SDK 7.x, or any MagicMock
    equivalent used in tests).
    """
    segments: list[Segment] = []
    if not words:
        return segments

    cur_words: list[str] = []
    cur_start: float = float(words[0].start or 0.0)
    prev_end: float = cur_start

    def _flush(end: float) -> None:
        if cur_words:
            segments.append(Segment(
                start=cur_start,
                end=end,
                text=" ".join(cur_words).strip(),
            ))

    for i, w in enumerate(words):
        _pw = getattr(w, "punctuated_word", None)
        w_text: str = ((_pw if isinstance(_pw, str) else None) or w.word or "").strip()
        w_start: float = float(w.start or 0.0)
        w_end: float = float(w.end or w_start)

        # Check gap between previous word and this one
        gap = w_start - prev_end
        if cur_words and gap > _GAP_THRESHOLD:
            _flush(prev_end)
            cur_words = []
            cur_start = w_start

        cur_words.append(w_text)
        prev_end = w_end

        # Flush on sentence-ending punctuation
        ends_sentence = w_text.endswith(_SENTENCE_ENDS)
        # Flush on hard word-count cap (only if more words follow)
        at_cap = len(cur_words) >= _MAX_WORDS_PER_SEGMENT and i < len(words) - 1

        if ends_sentence or at_cap:
            _flush(w_end)
            cur_words = []
            if i + 1 < len(words):
                cur_start = float(words[i + 1].start or w_end)

    # Flush any remaining words
    if cur_words:
        _flush(prev_end)

    return segments


@dataclass
class DeepgramBackend:
    name: str = field(default="deepgram", init=False)
    supports_url: bool = field(default=False, init=False)
    supports_local_file: bool = field(default=True, init=False)

    model: str = "nova-3"

    def is_configured(self) -> tuple[bool, str | None]:
        if not get_api_key("deepgram"):
            return False, (
                "DEEPGRAM_API_KEY is not set. Get one at https://console.deepgram.com/ "
                "and register via `neurolearn config set-key deepgram`."
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

        key = get_api_key("deepgram")
        if not key:
            raise BackendNotConfigured("DEEPGRAM_API_KEY missing.")

        client = _build_client(key)
        auto = language == "auto"

        try:
            with audio.open("rb") as f:
                audio_bytes = f.read()

            response = client.listen.v1.media.transcribe_file(
                request=audio_bytes,
                model=self.model,
                smart_format=True,
                punctuate=True,
                detect_language=auto,
                language=None if auto else language,
            )
        except Exception as e:
            raise BackendError(f"Deepgram API error: {e}") from e

        try:
            channel = response.results.channels[0]
            alt = channel.alternatives[0]
            words = alt.words or []
            language_detected = channel.detected_language
        except (AttributeError, IndexError) as e:
            raise BackendError(f"Unexpected Deepgram response format: {e}")

        segments = _group_words_into_segments(words)
        text = (alt.transcript or "").strip()
        return TranscriptionResult(
            text=text,
            segments=segments,
            language_detected=language_detected,
            backend_name=self.name,
            duration_seconds=segments[-1].end if segments else 0.0,
        )
