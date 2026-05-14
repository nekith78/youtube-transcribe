"""Interactive selection of batch + videos via questionary.

TTY-gated. Caller is expected to check sys.stdin.isatty() before calling.
"""
from __future__ import annotations

from pathlib import Path

from skills.neurolearn.analyze.source_resolver import (
    VideoSource,
    pick_latest_batch,
)


class PickerCancelled(Exception):
    """User hit Ctrl-C / esc in the picker."""


def pick_batch(outputs_dir: Path) -> Path:
    """Single-select picker over subfolders containing manifest.json.

    Newest first. Raises PickerCancelled if user aborts.
    Raises FileNotFoundError if no batches exist.
    """
    import questionary
    import json

    candidates = sorted(
        (p for p in outputs_dir.iterdir()
         if p.is_dir() and (p / "manifest.json").exists()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"no batches with manifest.json in {outputs_dir}")

    choices = []
    for b in candidates:
        try:
            meta = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
            stats = meta.get("stats", {})
            ok = stats.get("ok", "?")
            total = stats.get("total", "?")
            backend = meta.get("config", {}).get("backend", "?")
            label = f"{b.name}  {ok}/{total} ok  {backend}"
        except Exception:
            label = b.name
        choices.append(questionary.Choice(title=label, value=str(b)))

    answer = questionary.select(
        "Pick a batch:", choices=choices,
    ).ask()
    if answer is None:
        raise PickerCancelled()
    return Path(answer)


def pick_videos(videos: list[VideoSource]) -> list[VideoSource]:
    """Multi-select checkbox over videos. Returns chosen subset.

    Raises PickerCancelled if user aborts.
    """
    import questionary

    if not videos:
        return []

    choices = []
    for i, v in enumerate(videos, start=1):
        title = v.title or v.transcript_path.stem
        title = title if len(title) <= 60 else title[:57] + "..."
        date = v.upload_date or "—"
        dur = _fmt_duration(v.duration_sec)
        label = f"{date}  {dur:>6}  {title}"
        choices.append(questionary.Choice(title=label, value=i - 1, checked=True))

    answer = questionary.checkbox(
        "Pick videos to analyze (Space=toggle, Enter=ok):",
        choices=choices,
    ).ask()
    if answer is None:
        raise PickerCancelled()
    return [videos[i] for i in answer]


def _fmt_duration(sec: int | None) -> str:
    if sec is None:
        return "—"
    mm, ss = divmod(sec, 60)
    hh, mm = divmod(mm, 60)
    return f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"


__all__ = ["pick_batch", "pick_videos", "PickerCancelled"]
