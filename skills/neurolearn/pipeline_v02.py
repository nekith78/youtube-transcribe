"""v0.2 pipeline stages: quality check + visual detection/annotation.

Wrapper applied after the v0.1 transcribe stage. Returns enriched
TranscriptionResult with .quality and .visual_segments populated.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import skills.neurolearn.config as _config_mod
from skills.neurolearn.backends.base import TranscriptionResult
from skills.neurolearn.detection.base import DetectionWindow
from skills.neurolearn.detection.llm_classify import find_visual_moments_via_llm
from skills.neurolearn.detection.matcher import match_segment
from skills.neurolearn.detection.scene import find_scene_boundaries
from skills.neurolearn.detection.triggers import load_triggers, TriggerConfig
from skills.neurolearn.detection.window_merge import (
    merge_overlapping_windows,
    refine_with_frame_diff,
    select_windows_by_budget,
)
from skills.neurolearn.quality.heuristic_checker import HeuristicChecker
from skills.neurolearn.vision.gemini import GeminiVisionBackend
from skills.neurolearn.vision.prompts import (
    DEFAULT_VIDEO_TYPE, format_prompt, load_prompt,
)


def _autodetect_video_type(result) -> str:
    """Auto-detect video type from transcript segments. Defensive — any
    failure falls back to 'generic' so the pipeline never breaks."""
    try:
        from skills.neurolearn.detection.video_type_detect import (
            detect_video_type,
        )
        sig = detect_video_type(result.segments)
        return sig.video_type
    except Exception:
        return DEFAULT_VIDEO_TYPE


def _resolve_vision_prompt(cfg: dict[str, Any], video_type: str) -> str:
    """Resolve the vision-prompt template to send to the LLM.

    Priority:
      1. `vision_prompt_path` cfg option / `--prompt-file` CLI flag —
         loads the file verbatim and (by default) prepends the global
         prefix from prompts_default.toml.
      2. Otherwise look up `prompts.<video_type>` via load_prompt(), which
         honors user overrides at ~/.neurolearn/prompts.toml.

    Path errors fall back to the generic built-in template; bad config
    shouldn't break the pipeline.
    """
    path_str = (cfg.get("vision_prompt_path") or "").strip()
    use_global = not cfg.get("no_global_prefix", False)
    if path_str:
        try:
            custom = Path(path_str).expanduser().read_text(encoding="utf-8")
        except Exception:
            spec = load_prompt(video_type, use_global_prefix=use_global)
            return spec.template
        spec = load_prompt(
            video_type, custom_template=custom, use_global_prefix=use_global,
        )
        return spec.template
    spec = load_prompt(video_type, use_global_prefix=use_global)
    return spec.template


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
    audio_path: Path | None = None,
) -> TranscriptionResult:
    """Apply quality check + detect + vision stages. Returns enriched result.

    triggers_path: override default user triggers.toml location
                   (CLI flag `--triggers /path/to/file.toml`).
    no_default_triggers: skip built-in default phrases — use only user file
                        (CLI flag `--no-default-triggers`).
    audio_path: optional path to audio file for diarization. If `video_path`
                is set (mp4), pyannote can use it directly so `audio_path`
                is unnecessary.
    """
    # === Speaker diarization (opt-in, runs first to enrich segments
    # before quality scoring sees the speaker labels) ===
    if cfg.get("diarize") and result.segments:
        diar_source = audio_path or video_path
        if diar_source is not None:
            from skills.neurolearn.quality.diarization import (
                attach_speakers_to_segments, diarize_audio,
            )
            num_spk = int(cfg.get("diarize_num_speakers") or 0) or None
            intervals = diarize_audio(diar_source, num_speakers=num_spk)
            if intervals:
                result.segments = attach_speakers_to_segments(
                    result.segments, intervals,
                )

    # === Quality check ===
    if cfg.get("quality_check"):
        checker = HeuristicChecker(enable_perplexity=bool(cfg.get("quality_perplexity")))
        report = checker.check(result.segments, result.language_detected or "en", source=source)
        result.quality = report

        # === ASR correction (opt-in, only on bad transcripts) ===
        if (
            cfg.get("correct_asr")
            and report.recommendation != "use_as_is"
            and result.segments
        ):
            from skills.neurolearn.quality.asr_corrector import (
                correct_transcript_via_llm,
            )
            corrector_backend = cfg.get("correct_asr_backend", "gemini")
            # Ollama is local-only; cloud backends need an API key.
            if corrector_backend == "ollama":
                corrector_api_key = None  # not needed
                can_run = True
            else:
                corrector_key = {
                    "gemini": "gemini",
                    "claude": "anthropic",
                    "openai": "openai",
                }.get(corrector_backend)
                corrector_api_key = (
                    _config_mod.get_api_key(corrector_key) if corrector_key else None
                )
                can_run = corrector_api_key is not None

            if can_run:
                corrected = correct_transcript_via_llm(
                    result.segments,
                    result.language_detected or "en",
                    api_key=corrector_api_key,
                    backend=corrector_backend,
                    ollama_model=cfg.get("ollama_model", "llama3.2:3b"),
                    ollama_host=cfg.get("ollama_host", "http://localhost:11434"),
                )
                if corrected is not result.segments:
                    result.segments = corrected
                    new_breakdown = dict(report.breakdown)
                    new_breakdown["asr_corrected"] = corrector_backend
                    object.__setattr__(report, "breakdown", new_breakdown)

    # === Translation (opt-in, runs after quality+correction, before vision) ===
    target_lang = (cfg.get("translate_to") or "").strip()
    if target_lang and result.segments:
        from skills.neurolearn.quality.translator import translate_transcript
        tr_backend = cfg.get("translate_backend", "gemini")
        if tr_backend == "ollama":
            tr_api_key = None
            tr_can_run = True
        else:
            tr_key = {
                "gemini": "gemini",
                "claude": "anthropic",
                "openai": "openai",
            }.get(tr_backend)
            tr_api_key = _config_mod.get_api_key(tr_key) if tr_key else None
            tr_can_run = tr_api_key is not None

        if tr_can_run:
            translated = translate_transcript(
                result.segments,
                source_lang=result.language_detected or "auto",
                target_lang=target_lang,
                api_key=tr_api_key,
                backend=tr_backend,
                ollama_model=cfg.get("ollama_model", "llama3.2:3b"),
                ollama_host=cfg.get("ollama_host", "http://localhost:11434"),
            )
            if translated is not result.segments:
                result.segments = translated
                # Reflect translation in language_detected so downstream
                # writers know the output is in target_lang.
                try:
                    object.__setattr__(result, "language_detected", target_lang)
                except Exception:
                    pass

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
            asym = bool(cfg.get("asymmetric_frames", False))
            # v0.10.1: resolve video_type → prompt. CLI / preset can pin
            # it; otherwise auto-detect from the transcript.
            video_type = cfg.get("video_type") or _autodetect_video_type(result)
            prompt_template = _resolve_vision_prompt(cfg, video_type)
            if vision_backend_name == "claude":
                from skills.neurolearn.vision.claude_vision import (
                    ClaudeVisionBackend,
                )
                backend = ClaudeVisionBackend(api_key=api_key, frames_per_window=fpw)
            elif vision_backend_name == "openai":
                from skills.neurolearn.vision.openai_vision import (
                    OpenAIVisionBackend,
                )
                backend = OpenAIVisionBackend(api_key=api_key, frames_per_window=fpw)
            else:  # gemini
                from skills.neurolearn.vision.gemini import concurrency_for_tier
                tier = cfg.get("gemini_tier") or "free"
                backend = GeminiVisionBackend(
                    api_key=api_key,
                    frames_per_window=fpw,
                    use_asymmetric_offsets=asym,
                    max_concurrent=concurrency_for_tier(tier),
                )
            visuals = backend.annotate_segments(
                video_path=video_path,
                windows=windows,
                prompt_template=prompt_template,
                language=result.language_detected or "en",
                video_id=video_id,
                out_dir=out_dir,
            )
            result.visual_segments = visuals

            # Capture Gemini token usage into the BudgetTracker so it
            # surfaces in manifest.json. Only Gemini backend exposes the
            # `last_run_usage` field (#8); Claude/OpenAI report usage via
            # their own SDKs — wire those when we add per-model tracking.
            try:
                last_usage = getattr(backend, "last_run_usage", [])
            except Exception:
                last_usage = []
            if last_usage:
                from skills.neurolearn.budget import BudgetTracker
                tracker = getattr(result, "budget", None) or BudgetTracker()
                model_name = getattr(backend, "model", "gemini-2.5-flash")
                for usage in last_usage:
                    tracker.record(
                        "vision_gemini", model_name,
                        prompt_tokens=usage.prompt_tokens,
                        output_tokens=usage.output_tokens,
                        cached_tokens=usage.cached_tokens,
                    )
                # Attach to the result so the writer can serialize it.
                try:
                    object.__setattr__(result, "budget", tracker)
                except Exception:
                    pass

            # === Claude fallback on low-confidence segments ===
            # Only fires when primary is Gemini AND user opted in via
            # the tutorial preset (or `claude_fallback = true` override).
            # ANTHROPIC_API_KEY must be set; otherwise silently skipped.
            if (
                vision_backend_name == "gemini"
                and cfg.get("claude_fallback", False)
                and result.visual_segments
            ):
                anthropic_key = _config_mod.get_api_key("anthropic")
                if anthropic_key:
                    result.visual_segments = _refine_low_confidence_with_claude(
                        visuals=result.visual_segments,
                        windows=windows,
                        video_path=video_path,
                        api_key=anthropic_key,
                        prompt_template=prompt_template,
                        language=result.language_detected or "en",
                        video_id=video_id,
                        out_dir=out_dir,
                        frames_per_window=fpw,
                    )

        # === v0.2: OCR (opt-in) ===
        if cfg.get("ocr") and result.visual_segments:
            from dataclasses import replace
            from skills.neurolearn.vision.ocr import ocr_keyframes
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


# Confidence threshold below which a Gemini description is treated as
# uncertain enough to merit a Claude re-check. Calibrated against the
# tutorial-pipeline guide: typical Gemini outputs score 0.75-0.90, so
# 0.7 catches the bottom ~15-20% of segments where small text or
# similar-looking elements caused doubt.
_CLAUDE_REFINE_THRESHOLD = 0.7


def _refine_low_confidence_with_claude(
    *,
    visuals: list,
    windows: list[DetectionWindow],
    video_path: Path,
    api_key: str,
    prompt_template: str,
    language: str,
    video_id: str,
    out_dir: Path,
    frames_per_window: int,
) -> list:
    """Re-process low-confidence visual segments through Claude.

    Pairs each VisualSegment with its source DetectionWindow by index
    (Gemini emits one segment per window, in order). Segments where
    `confidence < 0.7` OR `needs_refinement = True` are sent to Claude
    Vision for a second-pass description. The replacement re-uses the
    same keyframes — we don't re-extract.

    On any Claude error (rate limit, network, malformed reply), the
    original Gemini segment stays. Failure is silent and non-fatal.
    """
    if not visuals or not windows:
        return visuals
    # Identify candidates needing refinement.
    refine_indices = [
        i for i, v in enumerate(visuals)
        if (
            getattr(v, "confidence", 1.0) < _CLAUDE_REFINE_THRESHOLD
            or getattr(v, "needs_refinement", False)
        )
    ]
    if not refine_indices:
        return visuals
    # Pair indices to source windows. annotate_segments returns one
    # result per successfully-processed window in input order, so the
    # index mapping is identity unless some windows were skipped — we
    # accept that minor risk; refinement on the wrong window only hurts
    # quality (yields slightly less relevant description), never crashes.
    refine_windows = [windows[i] for i in refine_indices if i < len(windows)]
    if not refine_windows:
        return visuals

    try:
        from skills.neurolearn.vision.claude_vision import (
            ClaudeVisionBackend,
        )
        refiner = ClaudeVisionBackend(
            api_key=api_key,
            frames_per_window=frames_per_window,
        )
        refined = refiner.annotate_segments(
            video_path=video_path,
            windows=refine_windows,
            prompt_template=prompt_template,
            language=language,
            video_id=video_id,
            out_dir=out_dir,
        )
    except Exception:
        # Claude unavailable / errored — keep original Gemini outputs.
        return visuals

    if not refined:
        return visuals

    # Splice refined results back into the visuals list at their
    # original positions. If Claude returned fewer than expected
    # (some failed), keep the original Gemini segment at those slots.
    out = list(visuals)
    for slot, ref in zip(refine_indices, refined):
        if slot < len(out):
            out[slot] = ref
    return out
