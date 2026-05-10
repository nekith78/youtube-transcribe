"""v0.2 pipeline stages: quality check + visual detection/annotation.

Wrapper applied after the v0.1 transcribe stage. Returns enriched
TranscriptionResult with .quality and .visual_segments populated.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import skills.youtube_transcribe.config as _config_mod
from skills.youtube_transcribe.backends.base import TranscriptionResult
from skills.youtube_transcribe.detection.base import DetectionWindow
from skills.youtube_transcribe.detection.matcher import match_segment
from skills.youtube_transcribe.detection.scene import find_scene_boundaries
from skills.youtube_transcribe.detection.triggers import load_triggers, TriggerConfig
from skills.youtube_transcribe.detection.window_merge import (
    merge_overlapping_windows,
    select_windows_by_budget,
)
from skills.youtube_transcribe.quality.heuristic_checker import HeuristicChecker
from skills.youtube_transcribe.vision.gemini import GeminiVisionBackend
from skills.youtube_transcribe.vision.prompts import DEFAULT_PROMPT


Source = Literal["youtube_manual", "youtube_auto", "whisper", "external_asr"]


def find_detection_windows(
    result: TranscriptionResult,
    video_path: Path | None,
    triggers: TriggerConfig,
    detect_method: str,
) -> list[DetectionWindow]:
    """Build list of windows from triggers + (optionally) scene boundaries."""
    windows: list[DetectionWindow] = []

    # 1. Trigger-based windows from transcript
    for seg in result.segments:
        m = match_segment(seg.text, triggers)
        if m:
            windows.append(DetectionWindow(
                start=max(seg.start - 1.5, 0.0),
                end=seg.end + 1.5,
                reason=m.reason,
                score=m.score,
                weight=m.weight,
                phrase=m.phrase,
            ))

    # 2. Scene-change boundaries (only for hybrid / llm_full_pass)
    if detect_method in ("hybrid", "llm_full_pass") and video_path is not None:
        try:
            boundaries = find_scene_boundaries(video_path)
            for t in boundaries:
                windows.append(DetectionWindow(
                    start=max(t - 0.5, 0.0),
                    end=t + 1.5,
                    reason="scene_change",
                    score=0.5,
                    weight=1.0,
                    phrase="",
                ))
        except Exception:
            pass

    return windows


def apply_v02_stages(
    *,
    result: TranscriptionResult,
    cfg: dict[str, Any],
    video_path: Path | None,
    video_id: str,
    out_dir: Path,
    source: Source,
) -> TranscriptionResult:
    """Apply quality check + detect + vision stages. Returns enriched result."""
    # === Quality check ===
    if cfg.get("quality_check"):
        checker = HeuristicChecker()
        report = checker.check(result.segments, result.language_detected or "en", source=source)
        result.quality = report

    # === Visual detection + annotation ===
    if cfg.get("vision_backend") == "gemini" and video_path is not None:
        api_key = _config_mod.get_api_key("gemini")
        if not api_key:
            return result

        triggers = load_triggers()
        windows = find_detection_windows(
            result, video_path, triggers, cfg.get("detect_method", "keywords_only")
        )
        windows = merge_overlapping_windows(windows, max_gap=1.0)

        video_duration = result.segments[-1].end if result.segments else 0.0
        windows = select_windows_by_budget(
            windows,
            max_windows=cfg.get("max_windows_per_video", 20),
            video_duration=video_duration,
        )

        if windows:
            backend = GeminiVisionBackend(
                api_key=api_key,
                frames_per_window=cfg.get("frames_per_window", 3),
            )
            visuals = backend.annotate_segments(
                video_path=video_path,
                windows=windows,
                prompt_template=DEFAULT_PROMPT,
                language=result.language_detected or "en",
                video_id=video_id,
                out_dir=out_dir,
            )
            result.visual_segments = visuals

    return result
