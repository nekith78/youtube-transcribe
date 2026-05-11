"""Resolve `analyze` SOURCE argument into a list of transcript files.

SOURCE может быть:
 - путь к файлу (.txt/.json/.srt) → один VideoSource без metadata
 - путь к папке с manifest.json → videos из manifest
 - путь к папке без manifest → все *.txt/*.json/*.srt отсортированные
 - None + latest=True → берём свежайшую подпапку с manifest.json
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

_TRANSCRIPT_EXTS = {".txt", ".json", ".srt"}


@dataclass
class VideoSource:
    """Один транскрипт + метаданные (если есть)."""
    transcript_path: Path
    title: str | None = None
    upload_date: str | None = None   # ISO YYYY-MM-DD
    duration_sec: int | None = None
    language: str | None = None
    url: str | None = None


def resolve_source(
    source: Path | None,
    *,
    outputs_dir: Path,
    latest: bool,
) -> list[VideoSource]:
    """Return list of VideoSource based on SOURCE / --latest.

    Raises FileNotFoundError if SOURCE doesn't exist or no batches found.
    Returns empty list if folder has no transcripts.
    """
    if source is None:
        if not latest:
            raise FileNotFoundError(
                "no SOURCE and --latest not set — cannot resolve"
            )
        source = pick_latest_batch(outputs_dir)

    if not source.exists():
        raise FileNotFoundError(f"SOURCE does not exist: {source}")

    if source.is_file():
        return [VideoSource(transcript_path=source)]

    manifest = source / "manifest.json"
    if manifest.exists():
        return _from_manifest(source, manifest)

    # Folder without manifest — pick up loose transcripts.
    files = sorted(
        p for p in source.iterdir()
        if p.is_file() and p.suffix.lower() in _TRANSCRIPT_EXTS
    )
    return [VideoSource(transcript_path=p) for p in files]


def pick_latest_batch(outputs_dir: Path) -> Path:
    """Return the most-recently-modified subdir containing manifest.json."""
    if not outputs_dir.exists():
        raise FileNotFoundError(f"outputs dir does not exist: {outputs_dir}")
    candidates = [
        p for p in outputs_dir.iterdir()
        if p.is_dir() and (p / "manifest.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError(f"no batches with manifest.json in {outputs_dir}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _from_manifest(batch_dir: Path, manifest: Path) -> list[VideoSource]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    out: list[VideoSource] = []
    for v in data.get("videos") or []:
        if v.get("status") != "ok":
            continue
        files = v.get("files") or {}
        # Prefer .txt, fall back to .json, then .srt.
        rel = files.get("txt") or files.get("json") or files.get("srt")
        if not rel:
            continue
        path = batch_dir / rel
        if not path.exists():
            continue
        out.append(VideoSource(
            transcript_path=path,
            title=v.get("title"),
            upload_date=v.get("upload_date"),
            duration_sec=v.get("duration_sec"),
            language=v.get("language_detected"),
            url=v.get("url"),
        ))
    return out
