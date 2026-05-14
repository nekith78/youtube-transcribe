"""Backend factory + smart-mode composition.

Public API:
  build_backend(name, cfg) -> Transcriber
  run_smart(audio_or_url, cfg, *, language) -> TranscriptionResult
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Union

from skills.neurolearn.backends.assemblyai import AssemblyAIBackend
from skills.neurolearn.backends.base import (
    BackendError,
    Transcriber,
    TranscriptionResult,
)
from skills.neurolearn.backends.custom import CustomBackend
from skills.neurolearn.backends.deepgram import DeepgramBackend
from skills.neurolearn.backends.gemini import GeminiBackend
from skills.neurolearn.backends.groq import GroqBackend
from skills.neurolearn.backends.openai_api import OpenAIBackend
from skills.neurolearn.backends.subtitles import SubtitlesBackend
from skills.neurolearn.backends.whisper_local import WhisperLocalBackend
from skills.neurolearn.config import Config
from skills.neurolearn.utils.downloader import download_audio, is_url, is_youtube_url
from skills.neurolearn.utils.platform_detect import detect_platform


def build_backend(name: str, cfg: Config) -> Transcriber:
    """Return a configured Transcriber instance for *name*.

    Raises ValueError for unknown names.
    """
    if name == "subtitles":
        return SubtitlesBackend()

    if name == "whisper-local":
        info = detect_platform()
        impl = info.backend_impl
        device = info.device if cfg.whisper_device == "auto" else cfg.whisper_device
        compute = (
            info.recommended_compute_type
            if cfg.whisper_compute_type == "auto"
            else cfg.whisper_compute_type
        )
        return WhisperLocalBackend(
            model=cfg.whisper_model,
            device=device,
            compute_type=compute,
            impl=impl,
            beam_size=cfg.beam_size,
            vad=cfg.vad,
        )

    if name == "gemini":
        return GeminiBackend(model=cfg.gemini_model)

    if name == "groq":
        return GroqBackend(model=cfg.groq_model)

    if name == "openai":
        return OpenAIBackend(model=cfg.openai_model)

    if name == "deepgram":
        return DeepgramBackend(model=cfg.deepgram_model)

    if name == "assemblyai":
        return AssemblyAIBackend(model=cfg.assemblyai_model)

    if name == "custom":
        return CustomBackend(base_url=cfg.custom_base_url, model=cfg.custom_model)

    raise ValueError(f"Unknown backend: {name!r}")


def run_smart(
    audio_or_url: Union[str, Path],
    cfg: Config,
    *,
    language: str = "auto",
    on_stage: Callable[[str], None] | None = None,
) -> TranscriptionResult:
    """Smart-mode composition: subtitles fast-path → fallback_backend.

    Logic (spec §5.9):
    1. If cfg.fast_path_enabled AND audio_or_url is a YouTube URL:
       - Try SubtitlesBackend; on success return immediately.
       - On BackendError: fall through to fallback.
    2. Fall back to cfg.fallback_backend. The fallback backends
       (whisper-local, gemini, groq, ...) all require a local audio file
       — none of them accept URLs directly. If the input is a URL, the
       smart composer is responsible for downloading audio first.

    `on_stage(msg)` is called at each phase boundary so callers can drive
    a spinner / status line ("Fetching subtitles...", "Downloading audio...",
    "Transcribing via <fallback>...").
    """
    notify = on_stage or (lambda _msg: None)
    src = str(audio_or_url)
    if cfg.fast_path_enabled and is_youtube_url(src):
        notify("Fetching subtitles...")
        try:
            subs = build_backend("subtitles", cfg)
            return subs.transcribe(src, language=language)
        except BackendError:
            pass  # fall through to fallback

    fb_name = cfg.fallback_backend
    fb = build_backend(fb_name, cfg)
    if is_url(src):
        # Fallback backend needs a local file. Download into a temp dir;
        # the file is cleaned up on context exit (transcription has
        # already returned by then with its result in memory).
        import tempfile
        notify("Downloading audio...")
        with tempfile.TemporaryDirectory(prefix="yt-smart-fb-") as tmp:
            audio_path = download_audio(
                src, Path(tmp), cookies_file=cfg.cookies_file,
            )
            notify(f"Transcribing via {fb_name}...")
            return fb.transcribe(audio_path, language=language)
    notify(f"Transcribing via {fb_name}...")
    return fb.transcribe(audio_or_url, language=language)
