"""Persistent log of research/subscribes runs as a TOML file.

Stored at ~/.neurolearn/history.toml. Each entry has run id,
type (research/subscribes), timestamp, summary fields, output folder
path, status. Append-only; never modifies past entries.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path

import tomlkit


@dataclass
class RunEntry:
    id: str
    type: str                    # "research" | "subscribes"
    timestamp: str               # ISO 8601 UTC
    query: str | None            # research query (or None for subscribes)
    group: str | None            # subscribes group (or None for research)
    output: str                  # path to batch folder
    videos_found: int
    analyze_backend: str | None  # None if --no-analyze
    analyze_prompt_preview: str | None  # first ~200 chars of prompt
    status: str = "ok"           # "ok" | "failed" | "partial"
    languages: list[str] = field(default_factory=list)


def append_run(path: Path, entry: RunEntry) -> None:
    """Append a run to history.toml."""
    doc = (
        tomlkit.parse(path.read_text(encoding="utf-8"))
        if path.exists() else tomlkit.document()
    )
    arr = doc.get("runs")
    if arr is None:
        arr = tomlkit.aot()
        doc["runs"] = arr
    tbl = tomlkit.table()
    for k, v in asdict(entry).items():
        if v is not None:
            tbl[k] = v
    arr.append(tbl)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def list_runs(
    path: Path,
    *,
    limit: int | None = None,
    type_filter: str | None = None,
) -> list[RunEntry]:
    """Return runs newest-first. Filter by type if given."""
    if not path.exists():
        return []
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    raw = doc.get("runs") or []
    runs = [_from_dict(dict(r)) for r in raw]
    if type_filter:
        runs = [r for r in runs if r.type == type_filter]
    runs.sort(key=lambda r: r.timestamp, reverse=True)
    if limit is not None:
        runs = runs[:limit]
    return runs


def get_run(path: Path, run_id: str) -> RunEntry | None:
    for r in list_runs(path):
        if r.id == run_id:
            return r
    return None


def _from_dict(d: dict) -> RunEntry:
    return RunEntry(
        id=d.get("id", ""),
        type=d.get("type", "research"),
        timestamp=d.get("timestamp", ""),
        query=d.get("query"),
        group=d.get("group"),
        output=d.get("output", ""),
        videos_found=int(d.get("videos_found", 0)),
        analyze_backend=d.get("analyze_backend"),
        analyze_prompt_preview=d.get("analyze_prompt_preview"),
        status=d.get("status", "ok"),
        languages=list(d.get("languages") or []),
    )
