"""Read an existing transcript file (.txt with timestamps / .json / .srt)
back into a list[Segment] for downstream commands like `summarize`.

Used by the standalone `neurolearn summarize <file>` command.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from skills.neurolearn.utils.output_writer import Segment


# Matches "[HH:MM:SS.mmm --> HH:MM:SS.mmm] text" from write_txt_with_timestamps
_TXT_RE = re.compile(
    r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]\s*(.+)$"
)
# Matches "HH:MM:SS,mmm --> HH:MM:SS,mmm" from .srt (and dotted variant)
_SRT_TIME_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*$"
)


def _hms_ms_to_sec(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _load_json(path: Path) -> tuple[list[Segment], str | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "segments" not in data:
        raise ValueError("JSON does not look like a transcript (no 'segments' key)")
    segs: list[Segment] = []
    for s in data.get("segments") or []:
        if not isinstance(s, dict) or "text" not in s:
            continue
        segs.append(Segment(
            start=float(s.get("start", 0.0)),
            end=float(s.get("end", 0.0)),
            text=str(s["text"]),
        ))
    return segs, data.get("language")


def _load_srt(path: Path) -> tuple[list[Segment], str | None]:
    """Parse SRT: numeric index lines and time-range lines, then text."""
    segs: list[Segment] = []
    blocks = re.split(r"\r?\n\r?\n+", path.read_text(encoding="utf-8").strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        # First line may be the SRT index; time-range is usually the second
        time_line = None
        text_lines: list[str] = []
        for i, ln in enumerate(lines):
            if _SRT_TIME_RE.match(ln):
                time_line = ln
                text_lines = lines[i + 1:]
                break
        if not time_line:
            continue
        m = _SRT_TIME_RE.match(time_line)
        if not m:
            continue
        start = _hms_ms_to_sec(*m.group(1, 2, 3, 4))
        end = _hms_ms_to_sec(*m.group(5, 6, 7, 8))
        segs.append(Segment(start=start, end=end, text=" ".join(text_lines).strip()))
    return segs, None


def _load_txt(path: Path) -> tuple[list[Segment], str | None]:
    """Parse our own write_txt_with_timestamps format. Falls back to a
    single Segment covering [0, 0] if file has no time-prefixes (plain
    text from write_txt_plain)."""
    segs: list[Segment] = []
    has_any_time = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        m = _TXT_RE.match(raw_line)
        if m:
            has_any_time = True
            start = _hms_ms_to_sec(*m.group(1, 2, 3, 4))
            end = _hms_ms_to_sec(*m.group(5, 6, 7, 8))
            segs.append(Segment(start=start, end=end, text=m.group(9).strip()))
    if not has_any_time:
        # Plain text — one big segment so summarizer at least has content.
        text = path.read_text(encoding="utf-8").strip()
        if text:
            segs.append(Segment(start=0.0, end=0.0, text=text))
    return segs, None


def load_transcript_segments(path: Path) -> tuple[list[Segment], str | None]:
    """Read a transcript file into (segments, detected_language).

    Format is inferred from file extension. Unknown extensions are
    treated as .txt.
    """
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json(path)
    if suffix == ".srt":
        return _load_srt(path)
    # Default .txt parser (also handles unknown extensions)
    return _load_txt(path)
