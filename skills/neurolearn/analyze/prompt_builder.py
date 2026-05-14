"""Build the final prompt sent to the LLM for `analyze`.

Concatenates a neutral system instruction, the user's free-form prompt,
and a numbered list of transcript sections with metadata headers.
"""
from __future__ import annotations

from pathlib import Path

from skills.neurolearn.analyze.source_resolver import VideoSource
from skills.neurolearn.utils.transcript_loader import (
    load_transcript_segments,
)
from skills.neurolearn.utils.output_writer import Segment


SYSTEM_PROMPT = (
    "You are an assistant that answers user questions about the content "
    "of the provided video transcripts. Reply in the language of the "
    "user query."
)


def build_prompt(
    user_prompt: str,
    videos: list[VideoSource],
    *,
    max_chars: int = 60_000,
) -> str:
    """Render the full prompt string.

    Layout:
        {SYSTEM_PROMPT}

        {user_prompt}

        ---
        Transcripts:

        ### [1] {title} ({date}, {duration}, {lang})
        Source: {url}

        {body}

        ---

        ### [2] ...

    Bodies are read from disk via transcript_loader. Each body is
    soft-truncated at `max_chars` with a `[...truncated...]` marker.
    Unreadable files contribute a `(failed to load)` placeholder so the
    LLM still sees the rest of the batch.
    """
    parts = [SYSTEM_PROMPT, "", user_prompt, "", "---", "Transcripts:", ""]

    for idx, v in enumerate(videos, start=1):
        parts.append(_video_header(idx, v))
        parts.append("")
        parts.append(_video_body(v, max_chars))
        parts.append("")
        parts.append("---")
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _video_header(idx: int, v: VideoSource) -> str:
    title = v.title or v.transcript_path.stem
    bits: list[str] = []
    if v.upload_date:
        bits.append(v.upload_date)
    if v.duration_sec is not None:
        bits.append(_fmt_duration(v.duration_sec))
    if v.language:
        bits.append(v.language)
    suffix = f" ({', '.join(bits)})" if bits else ""
    head = f"### [{idx}] {title}{suffix}"
    if v.url:
        head += f"\nSource: {v.url}"
    return head


def _fmt_duration(sec: int) -> str:
    mm, ss = divmod(sec, 60)
    hh, mm = divmod(mm, 60)
    return f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"


def _video_body(v: VideoSource, max_chars: int) -> str:
    """Read transcript from disk and format. Truncate at max_chars."""
    try:
        segs, _ = load_transcript_segments(v.transcript_path)
    except Exception as e:
        return f"(failed to load {v.transcript_path.name}: {e})"

    if not segs:
        return "(empty transcript)"

    # If the original .txt has time-prefixed lines, prefer those as-is.
    if v.transcript_path.suffix.lower() == ".txt":
        raw = v.transcript_path.read_text(encoding="utf-8")
        return _truncate(raw, max_chars)

    return _truncate(_format_segments(segs), max_chars)


def _format_segments(segs: list[Segment]) -> str:
    lines = []
    for s in segs:
        h = int(s.start // 3600)
        m = int((s.start % 3600) // 60)
        sec = int(s.start % 60)
        lines.append(f"[{h:02d}:{m:02d}:{sec:02d}] {s.text.strip()}")
    return "\n".join(lines)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[...truncated...]"
