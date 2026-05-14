"""Local Whisper backend.

Two implementations:
  - faster-whisper for Windows/Linux/Intel-Mac (CUDA or CPU)
  - mlx-whisper for Apple Silicon  <- added in Task 10
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from skills.neurolearn.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.neurolearn.utils.output_writer import Segment


_MODEL_MAP = {
    "turbo":  {"mlx": "mlx-community/whisper-large-v3-turbo", "faster": "large-v3-turbo"},
    "large":  {"mlx": "mlx-community/whisper-large-v3-mlx",   "faster": "large-v3"},
    "medium": {"mlx": "mlx-community/whisper-medium-mlx",     "faster": "medium"},
    "small":  {"mlx": "mlx-community/whisper-small-mlx",      "faster": "small"},
    "distil": {"mlx": None,                                   "faster": "distil-large-v3"},
}


def _load_faster_whisper_model(name: str, device: str, compute_type: str):
    """Indirection to make this trivially mockable in tests.

    faster-whisper is imported lazily here so that this module can be
    imported on Mac arm64 (where faster-whisper is not installed) without
    raising an ImportError at import time.
    """
    from faster_whisper import WhisperModel  # noqa: PLC0415
    return WhisperModel(name, device=device, compute_type=compute_type)


def _resolve_compute_type(compute_type: str, device: str) -> str:
    if compute_type != "auto":
        return compute_type
    if device == "cuda":
        # Default safe choice; platform_detect can pre-set explicit value
        return "float16"
    return "int8"


def _resolve_device(device: str, impl: str) -> str:
    if device != "auto":
        return device
    if impl == "mlx":
        return "mps"
    # Try CUDA, fall back to CPU
    try:
        import torch  # type: ignore  # noqa: PLC0415
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    # faster-whisper has its own check via CTranslate2; default to cpu
    return "cpu"


@dataclass
class WhisperLocalBackend:
    name: str = field(default="whisper-local")
    supports_url: bool = field(default=False)
    supports_local_file: bool = field(default=True)

    model: Literal["turbo", "large", "medium", "small", "distil"] = field(default="turbo")
    device: str = field(default="auto")       # auto | cuda | cpu | mps
    compute_type: str = field(default="auto")
    impl: Literal["mlx", "faster"] = field(default="faster")
    beam_size: int = field(default=5)
    vad: bool = field(default=True)

    def is_configured(self) -> tuple[bool, str | None]:
        if self.impl == "mlx":
            try:
                import mlx_whisper  # noqa: F401, PLC0415
                return True, None
            except ImportError:
                return False, "mlx-whisper is not installed (requires macOS Apple Silicon)."
        try:
            import faster_whisper  # noqa: F401, PLC0415
            return True, None
        except ImportError:
            return False, "faster-whisper is not installed. Run `uv sync`."

    def _resolve_model_name(self) -> str:
        m = _MODEL_MAP.get(self.model)
        if not m:
            raise ValueError(f"Unknown model: {self.model}")
        name = m[self.impl]
        if name is None:
            raise ValueError(f"Model '{self.model}' is not supported for impl='{self.impl}'.")
        return name

    def transcribe(
        self,
        audio_or_url,
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

        model_name = self._resolve_model_name()

        if self.impl == "faster":
            return self._transcribe_faster(audio, model_name, language)
        elif self.impl == "mlx":
            # Task 10: dispatch to mlx implementation
            return self._transcribe_mlx(audio, model_name, language)
        else:
            raise BackendError(f"Unknown impl: {self.impl}")

    def _transcribe_faster(self, audio: Path, model_name: str, language: str) -> TranscriptionResult:
        device = _resolve_device(self.device, "faster")
        compute_type = _resolve_compute_type(self.compute_type, device)
        model = _load_faster_whisper_model(model_name, device, compute_type)
        lang = None if language == "auto" else language
        segments_iter, info = model.transcribe(
            str(audio),
            language=lang,
            beam_size=self.beam_size,
            vad_filter=self.vad,
            word_timestamps=False,
        )
        segments: list[Segment] = []
        for s in segments_iter:
            segments.append(Segment(start=float(s.start), end=float(s.end), text=s.text))
        text = " ".join(s.text.strip() for s in segments)
        return TranscriptionResult(
            text=text,
            segments=segments,
            language_detected=getattr(info, "language", None),
            backend_name=self.name,
            duration_seconds=float(getattr(info, "duration", 0.0)),
        )

    def _transcribe_mlx(self, audio: Path, model_name: str, language: str) -> TranscriptionResult:
        import mlx_whisper  # type: ignore  # noqa: PLC0415
        lang = None if language == "auto" else language
        # mlx_whisper.transcribe returns dict with "text", "segments", "language"
        result = mlx_whisper.transcribe(
            str(audio),
            path_or_hf_repo=model_name,
            language=lang,
            word_timestamps=False,
        )
        segments: list[Segment] = []
        total_duration = 0.0
        for s in result.get("segments", []):
            seg = Segment(
                start=float(s.get("start", 0.0)),
                end=float(s.get("end", 0.0)),
                text=str(s.get("text", "")),
            )
            segments.append(seg)
            total_duration = max(total_duration, seg.end)
        text = result.get("text") or " ".join(s.text.strip() for s in segments)
        return TranscriptionResult(
            text=text,
            segments=segments,
            language_detected=result.get("language"),
            backend_name=self.name,
            duration_seconds=total_duration,
        )
