"""Format transcription segments into .txt and .srt files."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PARAGRAPH_PAUSE_SECONDS = 2.0
PARAGRAPH_AFTER_N_SEGMENTS = 5


@dataclass(frozen=True)
class Segment:
    start: float  # seconds
    end: float
    text: str


def _format_timestamp_dotted(seconds: float) -> str:
    """01:02:03.456 — used in .txt with timestamps."""
    if seconds < 0:
        seconds = 0.0
    hh = int(seconds // 3600)
    mm = int((seconds % 3600) // 60)
    ss_full = seconds - hh * 3600 - mm * 60
    ss = int(ss_full)
    ms = int(round((ss_full - ss) * 1000))
    if ms == 1000:
        ss += 1
        ms = 0
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"


def format_timestamp_srt(seconds: float) -> str:
    """01:02:03,456 — used in .srt (note comma)."""
    return _format_timestamp_dotted(seconds).replace(".", ",")


def write_txt_with_timestamps(segments: Iterable[Segment], path: Path) -> None:
    lines = [
        f"[{_format_timestamp_dotted(s.start)} --> {_format_timestamp_dotted(s.end)}] {s.text.strip()}"
        for s in segments
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_txt_plain(segments: Iterable[Segment], path: Path) -> None:
    """Plain text, paragraph breaks on 2+ second pauses or every 5 segments."""
    segs = list(segments)
    if not segs:
        path.write_text("", encoding="utf-8")
        return

    paragraphs: list[list[str]] = [[]]
    last_end = segs[0].start
    in_para_count = 0

    for s in segs:
        gap = s.start - last_end
        if (gap >= PARAGRAPH_PAUSE_SECONDS or in_para_count >= PARAGRAPH_AFTER_N_SEGMENTS) and paragraphs[-1]:
            paragraphs.append([])
            in_para_count = 0
        paragraphs[-1].append(s.text.strip())
        last_end = s.end
        in_para_count += 1

    text = "\n\n".join(" ".join(p) for p in paragraphs if p)
    path.write_text(text + "\n", encoding="utf-8")


def write_srt(segments: Iterable[Segment], path: Path) -> None:
    blocks: list[str] = []
    for i, s in enumerate(segments, start=1):
        blocks.append(
            f"{i}\n"
            f"{format_timestamp_srt(s.start)} --> {format_timestamp_srt(s.end)}\n"
            f"{s.text.strip()}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")


_SAFE_NAME_RE = re.compile(r"[^\wЀ-ӿ\-]+", re.UNICODE)


def sanitize_filename(name: str) -> str:
    """Keep letters/digits/Cyrillic/-/_, collapse everything else into _."""
    cleaned = _SAFE_NAME_RE.sub("_", name).strip("_")
    return cleaned or "transcript"
