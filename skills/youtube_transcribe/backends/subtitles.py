"""subtitles backend — fast path via youtube-transcript-api, no API key needed."""
from __future__ import annotations

from dataclasses import dataclass

from skills.youtube_transcribe.backends.base import (
    BackendError,
    TranscriptionResult,
)
from skills.youtube_transcribe.utils.downloader import (
    extract_youtube_video_id,
    is_youtube_url,
)
from skills.youtube_transcribe.utils.output_writer import Segment


class _ApiAdapter:
    """Thin adapter that wraps the installed youtube-transcript-api version,
    exposing a stable ``get_transcript(video_id, languages)`` interface
    regardless of whether the library uses the old class-method API or the
    newer instance-based API (0.6+)."""

    def get_transcript(self, video_id: str, languages: list[str] | None = None) -> list[dict]:
        from youtube_transcript_api import YouTubeTranscriptApi

        langs = languages or ["en"]

        # ---- new API (≥0.6): instance with .fetch() → FetchedTranscript ----
        if hasattr(YouTubeTranscriptApi, "fetch") and not hasattr(YouTubeTranscriptApi, "get_transcript"):
            api = YouTubeTranscriptApi()
            try:
                fetched = api.fetch(video_id, languages=langs)
            except Exception as e:
                raise e
            # FetchedTranscript has a .snippets list of FetchedTranscriptSnippet dataclasses
            snippets = getattr(fetched, "snippets", None)
            if snippets is not None:
                return [
                    {"start": s.start, "duration": s.duration, "text": s.text}
                    for s in snippets
                ]
            # Fallback: try iterating (some versions make FetchedTranscript iterable)
            return [
                {"start": s.start, "duration": s.duration, "text": s.text}
                for s in fetched
            ]

        # ---- old API (<0.6): class-method .get_transcript() → list[dict] ----
        return YouTubeTranscriptApi.get_transcript(video_id, languages=langs)


def _get_transcript_api() -> _ApiAdapter:
    """Return an API adapter object. Lazy-imported so youtube-transcript-api
    is only required at call time. Patched in unit tests."""
    try:
        import youtube_transcript_api  # noqa: F401
    except ImportError as e:
        raise ImportError("youtube-transcript-api не установлен. Запусти `uv sync`.") from e
    return _ApiAdapter()


@dataclass
class SubtitlesBackend:
    name: str = "subtitles"
    supports_url: bool = True
    supports_local_file: bool = False

    def is_configured(self) -> tuple[bool, str | None]:
        try:
            import youtube_transcript_api  # noqa: F401
            return True, None
        except ImportError:
            return False, "youtube-transcript-api не установлен. Запусти `uv sync`."

    def transcribe(self, audio_or_url, *, language: str = "auto", **opts) -> TranscriptionResult:
        url = str(audio_or_url)
        if not is_youtube_url(url):
            raise BackendError("Бэкенд subtitles работает только с YouTube-ссылками.")

        video_id = extract_youtube_video_id(url)
        if not video_id:
            raise BackendError(f"Не смог извлечь ID YouTube-видео из URL: {url}")

        api = _get_transcript_api()
        languages = None if language == "auto" else [language]
        try:
            raw = api.get_transcript(video_id, languages=languages or ["en"])
        except Exception as e:
            raise BackendError(
                f"Субтитры недоступны для этого видео ({type(e).__name__}). "
                "Попробуй другой бэкенд."
            ) from e

        segments: list[Segment] = []
        for item in raw:
            start = float(item.get("start", 0.0))
            duration = float(item.get("duration", 0.0))
            segments.append(Segment(
                start=start,
                end=start + duration,
                text=str(item.get("text", "")).strip(),
            ))
        text = " ".join(s.text for s in segments)
        return TranscriptionResult(
            text=text,
            segments=segments,
            language_detected=language if language != "auto" else None,
            backend_name=self.name,
            duration_seconds=segments[-1].end if segments else 0.0,
        )
