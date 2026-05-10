"""Window merge (combine overlaps + close gaps) and budget selection."""
from __future__ import annotations

from skills.youtube_transcribe.detection.base import DetectionWindow


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
