"""Window merge (combine overlaps + close gaps) and budget selection."""
from __future__ import annotations

from pathlib import Path

from skills.neurolearn.detection.base import DetectionWindow


def merge_overlapping_windows(
    windows: list[DetectionWindow], max_gap: float = 1.0
) -> list[DetectionWindow]:
    """Sort by start, merge if overlap or gap < max_gap. Keep best (priority_score) reason/phrase."""
    if not windows:
        return []
    sorted_ws = sorted(windows, key=lambda w: w.start)
    out: list[DetectionWindow] = [sorted_ws[0]]
    for w in sorted_ws[1:]:
        last = out[-1]
        if w.start <= last.end + max_gap:
            best = last if last.priority_score >= w.priority_score else w
            out[-1] = DetectionWindow(
                start=min(last.start, w.start),
                end=max(last.end, w.end),
                reason=best.reason,
                score=best.score,
                weight=best.weight,
                phrase=best.phrase,
            )
        else:
            out.append(w)
    return out


def refine_with_frame_diff(
    windows: list[DetectionWindow],
    video_path: Path,
    *,
    change_threshold: int = 20,
    fps: float = 1.0,
    min_changes: int = 1,
    rich_changes: int = 5,
    rich_score_boost: float = 1.3,
) -> list[DetectionWindow]:
    """Refine windows with perceptual-hash frame diffing (spec §5 brick C).

    For each window:
      - Count frame changes inside (hamming distance > change_threshold).
      - If 0 < changes < min_changes: drop the window (static talking-head,
        not worth a Gemini call).
      - If changes >= rich_changes: boost score (visually-rich moment).
      - Otherwise: keep as-is.

    Failures (e.g. ffmpeg hiccup) → keep window unchanged. Non-fatal.
    """
    if not windows:
        return []

    # Lazy import: frame_diff calls ffmpeg subprocess; keep this module
    # importable in pure unit-test contexts that mock at the top level.
    from skills.neurolearn.detection.frame_diff import (
        detect_frame_changes_in_window,
    )

    # High-confidence signals — never drop, never re-score. The user (raw/strict
    # exact-match triggers) or an LLM (llm_full_pass) explicitly flagged these
    # moments as worth capturing; frame_diff shouldn't second-guess that.
    _STRONG_REASONS = ("raw", "strict:", "llm_full_pass:")

    out: list[DetectionWindow] = []
    for w in windows:
        if w.reason.startswith(_STRONG_REASONS):
            out.append(w)
            continue

        try:
            diffs = detect_frame_changes_in_window(
                video_path, start=w.start, end=w.end,
                threshold=change_threshold, fps=fps,
            )
        except Exception:
            # ffmpeg failed for this window — keep it, let vision backend decide.
            out.append(w)
            continue

        n = len(diffs)
        if n < min_changes:
            # Static talking-head — drop this weak-signal window.
            continue
        if n >= rich_changes:
            new_score = min(w.score * rich_score_boost, 1.0)
            out.append(DetectionWindow(
                start=w.start, end=w.end, reason=w.reason,
                score=new_score, weight=w.weight, phrase=w.phrase,
            ))
        else:
            out.append(w)
    return out


def select_windows_by_budget(
    windows: list[DetectionWindow],
    max_windows: int,
    video_duration: float,
) -> list[DetectionWindow]:
    """If matches fit within budget — return all. Otherwise:
      1. Divide video into max_windows time buckets.
      2. In each bucket — pick window with highest priority_score (score * weight).
      3. Return list (may be < max_windows if some buckets empty).
    """
    if max_windows <= 0 or video_duration <= 0 or not windows:
        return []
    if len(windows) <= max_windows:
        return list(windows)

    bucket_size = video_duration / max_windows
    buckets: list[list[DetectionWindow]] = [[] for _ in range(max_windows)]
    for w in windows:
        idx = min(int(w.start / bucket_size), max_windows - 1)
        buckets[idx].append(w)
    out = []
    for bucket in buckets:
        if bucket:
            out.append(max(bucket, key=lambda w: w.priority_score))
    return out
