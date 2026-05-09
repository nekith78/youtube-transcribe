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


import json as _json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Literal


SourceType = Literal["channel", "playlist", "file", "inline", "mixed"]
Stage = Literal["resolve", "download", "backend", "write"]


@dataclass
class BatchMeta:
    """Метадата batch-прогона. Передаётся в writers, попадает в YAML/JSON."""
    batch_name: str
    created_at: datetime
    source_type: SourceType
    source_url: str | None
    backend: str
    backend_options: dict
    language: str


@dataclass
class BatchVideoStatus:
    """Один итоговый ряд таблицы по результату прогона одного видео."""
    index: int
    url: str
    video_id: str | None
    title: str | None
    upload_date: date | None
    duration_sec: int | None
    channel: str | None
    language_detected: str | None
    text: str                              # flat-text транскрипта (без таймкодов)
    files: dict                            # {"txt": "...", "srt": "..."} relative paths
    status: Literal["ok", "failed"]
    error: str | None = None


@dataclass
class BatchFailure:
    """Один отказ в batch — для errors.log и manifest.json."""
    index: int
    url: str
    stage: Stage
    error_text: str
    hint: str | None = None


def _fmt_duration(sec: int | None) -> str:
    if sec is None:
        return "—"
    mm, ss = divmod(sec, 60)
    hh, mm = divmod(mm, 60)
    return f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"


def _fmt_date(d: date | None) -> str:
    return d.isoformat() if d else "—"


def _yaml_frontmatter(meta: BatchMeta, ok: int, failed: int, total: int) -> str:
    return (
        "---\n"
        f"batch_name: {meta.batch_name}\n"
        f"created_at: {meta.created_at.isoformat()}\n"
        f"source: {meta.source_type}\n"
        f"source_url: {meta.source_url or 'null'}\n"
        f"total: {total}\n"
        f"ok: {ok}\n"
        f"failed: {failed}\n"
        f"backend: {meta.backend}\n"
        + "".join(f"{k}: {v}\n" for k, v in meta.backend_options.items())
        + f"language: {meta.language}\n"
        "---\n"
    )


def write_combined_md(
    videos: list[BatchVideoStatus],
    meta: BatchMeta,
    output_dir: Path,
) -> Path:
    """Render combined.md with YAML front-matter + per-video sections (flat text, no timestamps)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ok = sum(1 for v in videos if v.status == "ok")
    failed = sum(1 for v in videos if v.status == "failed")
    total = ok + failed

    parts: list[str] = []
    parts.append(_yaml_frontmatter(meta, ok=ok, failed=failed, total=total))
    parts.append(f"\n# Batch transcript — {meta.batch_name} — {meta.created_at.date().isoformat()}\n")
    parts.append(f"\n{total} видео, бэкенд: {meta.backend}. {ok} успешно, {failed} с ошибкой.\n")

    for v in videos:
        if v.status != "ok":
            continue
        parts.append("\n---\n\n")
        parts.append(f"## {v.index}. {v.title or '(без названия)'}\n\n")
        parts.append("| Поле | Значение |\n|---|---|\n")
        parts.append(f"| URL | {v.url} |\n")
        parts.append(f"| Video ID | {v.video_id or '—'} |\n")
        parts.append(f"| Date | {_fmt_date(v.upload_date)} |\n")
        parts.append(f"| Duration | {_fmt_duration(v.duration_sec)} |\n")
        parts.append(f"| Channel | {v.channel or '—'} |\n")
        parts.append(f"| Language detected | {v.language_detected or '—'} |\n\n")
        parts.append(v.text.strip() + "\n")

    path = output_dir / "combined.md"
    path.write_text("".join(parts), encoding="utf-8")
    return path


def write_manifest_json(
    videos: list[BatchVideoStatus],
    failures: list[BatchFailure],
    meta: BatchMeta,
    output_dir: Path,
) -> Path:
    """Render machine-readable manifest.json mirroring combined.md structure."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ok = sum(1 for v in videos if v.status == "ok")
    failed = len(failures) + sum(1 for v in videos if v.status == "failed")
    total = ok + failed

    out: list[dict] = []
    for v in videos:
        out.append({
            "index": v.index,
            "url": v.url,
            "video_id": v.video_id,
            "title": v.title,
            "upload_date": v.upload_date.isoformat() if v.upload_date else None,
            "duration_sec": v.duration_sec,
            "channel": v.channel,
            "language_detected": v.language_detected,
            "files": v.files,
            "status": v.status,
            "error": v.error,
        })
    for f in failures:
        out.append({
            "index": f.index,
            "url": f.url,
            "status": "failed",
            "stage": f.stage,
            "error": f.error_text,
            "hint": f.hint,
        })
    out.sort(key=lambda x: x["index"])

    payload = {
        "batch_name": meta.batch_name,
        "created_at": meta.created_at.isoformat(),
        "source": {"type": meta.source_type, "url": meta.source_url},
        "config": {"backend": meta.backend, **meta.backend_options, "language": meta.language},
        "stats": {"total": total, "ok": ok, "failed": failed},
        "videos": out,
    }
    path = output_dir / "manifest.json"
    path.write_text(_json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_errors_log(
    failures: list[BatchFailure],
    output_dir: Path,
) -> Path | None:
    """Write errors.log only if there were failures; otherwise return None."""
    if not failures:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for f in failures:
        lines.append(f"[{datetime.now().isoformat(timespec='seconds')}] FAILED #{f.index} {f.url}")
        lines.append(f"  Stage: {f.stage}")
        lines.append(f"  Reason: {f.error_text}")
        if f.hint:
            lines.append(f"  Hint: {f.hint}")
        lines.append("")
    path = output_dir / "errors.log"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
