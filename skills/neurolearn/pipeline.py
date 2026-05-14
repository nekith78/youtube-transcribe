"""Core transcription pipeline. Used by both single (Task 20)
and batch (Task 20B) sub-commands. One target → one TranscriptionResult."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Callable, Iterator
from contextlib import contextmanager

from skills.neurolearn.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.neurolearn.backends.factory import build_backend, run_smart
from skills.neurolearn.config import Config
from skills.neurolearn.utils.downloader import (
    download_audio,
    is_url,
    maybe_auto_update_ytdlp,
)
from skills.neurolearn.utils.resolver import ResolvedTarget


@contextmanager
def _audio_workdir(keep_audio: bool, persist_to: Path | None = None) -> Iterator[Path]:
    """System temp dir for downloaded audio. If keep_audio and persist_to set,
    files are copied there before cleanup."""
    tmp = Path(tempfile.mkdtemp(prefix="yt-transcribe-"))
    try:
        yield tmp
    finally:
        if keep_audio and persist_to is not None:
            persist_to.mkdir(parents=True, exist_ok=True)
            for f in tmp.glob("*"):
                if f.is_file():
                    shutil.copy2(f, persist_to / f.name)
        shutil.rmtree(tmp, ignore_errors=True)


def run_pipeline(
    target: ResolvedTarget,
    cfg: Config,
    *,
    backend_override: str | None = None,
    keep_audio_to: Path | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> TranscriptionResult:
    """One target → one TranscriptionResult.

    Behaviour matches the table in spec §5 / §11:
    - subtitles / smart: pass URL straight to backend, no download
    - other backends + URL: yt-dlp -x mp3 into system temp, transcribe, cleanup
    - local file: pass path straight to backend

    `on_stage(msg)` is called at each phase boundary so callers can drive
    a spinner / status line. Always optional — None means "no progress UI".
    """
    backend_name = backend_override or cfg.default_backend
    notify = on_stage or (lambda _msg: None)

    # Local file → no download, no temp
    if not is_url(target.url):
        path = Path(target.url).expanduser().resolve()
        if not path.exists():
            raise BackendError(f"File not found: {path}")
        notify(f"Transcribing via {backend_name}...")
        return _transcribe_one(
            backend_name, path, cfg, language=cfg.language, on_stage=notify,
        )

    # URL paths
    if backend_name in ("subtitles", "smart"):
        # Subtitles handles URL directly without download.
        # Smart-composer drives its own stage notifications (subtitles
        # attempt, download on fallback, fallback transcription).
        if backend_name == "subtitles":
            notify("Fetching subtitles...")
        return _transcribe_one(
            backend_name, target.url, cfg, language=cfg.language, on_stage=notify,
        )

    # All other backends need local audio. Download → transcribe → cleanup.
    maybe_auto_update_ytdlp(cfg.yt_dlp_auto_update)
    with _audio_workdir(keep_audio=cfg.keep_audio, persist_to=keep_audio_to) as tmp:
        notify("Downloading audio...")
        audio_path = download_audio(
            target.url, tmp,
            cookies_file=cfg.cookies_file,
        )
        notify(f"Transcribing via {backend_name}...")
        return _transcribe_one(
            backend_name, audio_path, cfg, language=cfg.language, on_stage=notify,
        )


def _transcribe_one(
    backend_name: str, audio_or_url, cfg: Config, *, language: str,
    on_stage: Callable[[str], None] | None = None,
) -> TranscriptionResult:
    if backend_name == "smart":
        return run_smart(audio_or_url, cfg, language=language, on_stage=on_stage)
    backend = build_backend(backend_name, cfg)
    return backend.transcribe(audio_or_url, language=language)
