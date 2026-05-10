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
from skills.youtube_transcribe.detection.llm_classify import find_visual_moments_via_llm
from skills.youtube_transcribe.detection.matcher import match_segment
from skills.youtube_transcribe.detection.scene import find_scene_boundaries
from skills.youtube_transcribe.detection.triggers import load_triggers, TriggerConfig
from skills.youtube_transcribe.detection.window_merge import (
    merge_overlapping_windows,
    refine_with_frame_diff,
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
    *,
    api_key: str | None = None,
) -> list[DetectionWindow]:
    """Build list of windows from triggers + scenes + LLM classify (per spec §5).

    Stages activated per detect_method:
      keywords_only / semantic: triggers only
      hybrid: triggers + scenes
      llm_full_pass: triggers + scenes + LLM classifier
    """
    windows: list[DetectionWindow] = []

    # 1. Trigger-based windows from transcript
    # Pass detect_method as `mode` so matcher can skip universal embeddings
    # in keywords_only / per-lang in semantic. See spec §5 composition table.
    for seg in result.segments:
        m = match_segment(seg.text, triggers, mode=detect_method)
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

    # 3. LLM-classify pass (only for llm_full_pass)
    if detect_method == "llm_full_pass" and api_key:
        try:
            llm_windows = find_visual_moments_via_llm(
                result.segments,
                api_key=api_key,
                language=result.language_detected or "en",
            )
            windows.extend(llm_windows)
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
    triggers_path: Path | None = None,
    no_default_triggers: bool = False,
) -> TranscriptionResult:
    """Apply quality check + detect + vision stages. Returns enriched result.

    triggers_path: override default user triggers.toml location
                   (CLI flag `--triggers /path/to/file.toml`).
    no_default_triggers: skip built-in default phrases — use only user file
                        (CLI flag `--no-default-triggers`).
    """
    # === Quality check ===
    if cfg.get("quality_check"):
        checker = HeuristicChecker(enable_perplexity=bool(cfg.get("quality_perplexity")))
        report = checker.check(result.segments, result.language_detected or "en", source=source)
        result.quality = report

    # === Visual detection + annotation ===
    vision_backend_name = cfg.get("vision_backend", "off")
    if vision_backend_name in ("gemini", "claude", "openai") and video_path is not None:
        # Each multimodal backend uses its own API key.
        api_key_lookup = {
            "gemini": "gemini",
            "claude": "anthropic",
            "openai": "openai",
        }[vision_backend_name]
        api_key = _config_mod.get_api_key(api_key_lookup)
        if not api_key:
            return result

        triggers = load_triggers(
            user_path=triggers_path if triggers_path else None,
            force_replace=no_default_triggers,
        ) if triggers_path or no_default_triggers else load_triggers()
        detect_method = cfg.get("detect_method", "keywords_only")
        windows = find_detection_windows(
            result, video_path, triggers, detect_method, api_key=api_key,
        )
        windows = merge_overlapping_windows(windows, max_gap=1.0)

        # Frame-diff refinement (spec §5 brick C) — hybrid / llm_full_pass only.
        # Drops static talking-head windows, boosts visually-rich ones.
        if detect_method in ("hybrid", "llm_full_pass") and windows:
            windows = refine_with_frame_diff(windows, video_path)

        video_duration = result.segments[-1].end if result.segments else 0.0
        windows = select_windows_by_budget(
            windows,
            max_windows=cfg.get("max_windows_per_video", 20),
            video_duration=video_duration,
        )

        if windows:
            fpw = cfg.get("frames_per_window", 3)
            if vision_backend_name == "claude":
                from skills.youtube_transcribe.vision.claude_vision import (
                    ClaudeVisionBackend,
                )
                backend = ClaudeVisionBackend(api_key=api_key, frames_per_window=fpw)
            elif vision_backend_name == "openai":
                from skills.youtube_transcribe.vision.openai_vision import (
                    OpenAIVisionBackend,
                )
                backend = OpenAIVisionBackend(api_key=api_key, frames_per_window=fpw)
            else:  # gemini
                backend = GeminiVisionBackend(api_key=api_key, frames_per_window=fpw)
            visuals = backend.annotate_segments(
                video_path=video_path,
                windows=windows,
                prompt_template=DEFAULT_PROMPT,
                language=result.language_detected or "en",
                video_id=video_id,
                out_dir=out_dir,
            )
            result.visual_segments = visuals

        # === v0.2: OCR (opt-in) ===
        if cfg.get("ocr") and result.visual_segments:
            from dataclasses import replace
            from skills.youtube_transcribe.vision.ocr import ocr_keyframes
            new_visuals = []
            for vs in result.visual_segments:
                kf_paths = [out_dir / kf for kf in vs.keyframes]
                ocr_texts = ocr_keyframes(kf_paths)
                additions = [f"ocr:{t[:200]}" for t in ocr_texts if t]
                if additions:
                    new_visuals.append(replace(
                        vs,
                        detected_objects=list(vs.detected_objects) + additions,
                    ))
                else:
                    new_visuals.append(vs)
            result.visual_segments = new_visuals

    return result
