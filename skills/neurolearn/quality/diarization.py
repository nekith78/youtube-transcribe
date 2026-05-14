"""Speaker diarization via pyannote.audio (spec v0.5).

Returns list of (start, end, speaker_label) intervals. Map to transcript
segments by time overlap and prepend speaker label to each segment's text.

Opt-in via `[diarization]` extra (heavy: pyannote + torch_audio + ~500 MB
model on first call). Requires:
  1. `pip install neurolearn[diarization]` (or `uv sync --extra diarization`)
  2. HuggingFace token in HF_TOKEN env var
  3. License accepted at https://huggingface.co/pyannote/speaker-diarization-3.1

Failure modes return original segments unchanged with a logged warning —
the rest of the pipeline keeps working.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from skills.neurolearn.utils.output_writer import Segment


@lru_cache(maxsize=1)
def _get_pipeline(hf_token: str):
    """Lazy-load the pretrained pyannote pipeline."""
    from pyannote.audio import Pipeline
    return Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )


def is_diarization_available() -> bool:
    """Both pyannote installed AND HF token present?"""
    try:
        import pyannote.audio  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"))


def diarize_audio(
    audio_path: Path,
    *,
    hf_token: str | None = None,
    num_speakers: int | None = None,
) -> list[tuple[float, float, str]]:
    """Run pyannote diarization on an audio/video file.

    Returns list of (start_sec, end_sec, speaker_label) — labels like
    "SPEAKER_00", "SPEAKER_01". Empty list on failure.

    num_speakers: if known, pass to constrain the model; else auto-detected.
    """
    token = hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        return []
    try:
        pipeline = _get_pipeline(token)
    except Exception:
        return []
    try:
        kwargs = {}
        if num_speakers is not None:
            kwargs["num_speakers"] = int(num_speakers)
        annotation = pipeline(str(audio_path), **kwargs)
    except Exception:
        return []

    out: list[tuple[float, float, str]] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        out.append((float(turn.start), float(turn.end), str(speaker)))
    return out


def attach_speakers_to_segments(
    segments: list[Segment],
    diarization: list[tuple[float, float, str]],
) -> list[Segment]:
    """Map diarization intervals to transcript segments by midpoint overlap.

    For each segment, find the diarization interval that covers its
    midpoint. If multiple overlap, pick the one with greatest overlap.
    If no overlap (e.g., segment outside diarized region), leave text
    unchanged.

    Returns a new list of Segments with text prefixed by `[SPEAKER_NN] `.
    Original segment timing is preserved.
    """
    if not segments or not diarization:
        return segments

    def _best_speaker(seg_start: float, seg_end: float) -> str | None:
        best_label: str | None = None
        best_overlap = 0.0
        for d_start, d_end, label in diarization:
            overlap = min(seg_end, d_end) - max(seg_start, d_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_label = label
        return best_label

    out: list[Segment] = []
    for s in segments:
        speaker = _best_speaker(s.start, s.end)
        if speaker is None:
            out.append(s)
        else:
            out.append(Segment(
                start=s.start, end=s.end,
                text=f"[{speaker}] {s.text}",
            ))
    return out
