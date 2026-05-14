"""Single source of truth for all v0.2 options.

Used by:
- CLI flag generation (Click options)
- TUI prompts (`neurolearn config`)
- Future v0.4+ web UI form rendering
- Default config.toml comment generation
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OptionField:
    key: str
    type: type
    default: Any
    choices: list | None
    description: str
    section: str


REGISTRY: list[OptionField] = [
    # === transcribe ===
    OptionField(
        key="transcribe_backend", type=str, default="subtitles",
        choices=["subtitles", "whisper-local", "gemini", "groq", "openai",
                 "deepgram", "assemblyai", "custom"],
        description="Transcription backend. subtitles = use YouTube's own subs.",
        section="transcribe",
    ),
    OptionField(
        key="fallback_backend", type=str, default="whisper-local",
        choices=["whisper-local", "gemini", "groq", "openai", "deepgram",
                 "assemblyai", "custom"],
        description="What to fall back to when subtitles don't fit (smart mode).",
        section="transcribe",
    ),
    # === vision ===
    OptionField(
        key="vision_backend", type=str, default="off",
        choices=["off", "gemini", "claude", "openai"],
        description=(
            "Visual mode. off = audio only. "
            "gemini = multimodal (video+frames via File API). "
            "claude = images-only (keyframes via ffmpeg). "
            "openai = GPT-4o vision (keyframes via ffmpeg)."
        ),
        section="vision",
    ),
    OptionField(
        key="frames_per_window", type=int, default=3,
        choices=None,
        description="How many keyframes to extract per visual window.",
        section="vision",
    ),
    OptionField(
        key="max_windows_per_video", type=int, default=20,
        choices=None,
        description="Max number of vision-analysis windows per video.",
        section="vision",
    ),
    # === detection ===
    OptionField(
        key="detect_method", type=str, default="keywords_only",
        choices=["keywords_only", "semantic", "hybrid", "llm_full_pass"],
        description="Method for finding visually important moments.",
        section="detection",
    ),
    # === smart ===
    OptionField(
        key="quality_check", type=bool, default=False,
        choices=None,
        description="Run quality check on the produced transcript.",
        section="smart",
    ),
    OptionField(
        key="subtitle_quality_threshold", type=float, default=0.6,
        choices=None,
        description="Score below this → fall back to whisper in smart mode.",
        section="smart",
    ),
    OptionField(
        key="quality_perplexity", type=bool, default=False,
        choices=None,
        description="Enable kenlm perplexity (requires the `perplexity` extra).",
        section="smart",
    ),
    # === output ===
    OptionField(
        key="ocr", type=bool, default=False,
        choices=None,
        description="OCR on keyframes (requires the `ocr` extra + system tesseract).",
        section="output",
    ),
    # === ASR correction (v0.4) ===
    OptionField(
        key="correct_asr", type=bool, default=False,
        choices=None,
        description=(
            "Post-process transcript through a cheap LLM to fix garbled "
            "words. Triggered only when quality.recommendation != 'use_as_is'."
        ),
        section="smart",
    ),
    OptionField(
        key="correct_asr_backend", type=str, default="gemini",
        choices=["gemini", "claude", "openai", "ollama"],
        description=(
            "LLM provider for ASR correction. gemini=2.5-flash; "
            "claude=haiku-4-5; openai=gpt-4o-mini; ollama=local llama3.2:3b "
            "(requires `ollama serve` running)."
        ),
        section="smart",
    ),
    OptionField(
        key="ollama_model", type=str, default="llama3.2:3b",
        choices=None,
        description="Ollama model tag (default llama3.2:3b, ~2 GB).",
        section="smart",
    ),
    OptionField(
        key="ollama_host", type=str, default="http://localhost:11434",
        choices=None,
        description="Ollama HTTP host. Default = local daemon.",
        section="smart",
    ),
    # === Diarization (v0.5) ===
    OptionField(
        key="diarize", type=bool, default=False,
        choices=None,
        description=(
            "Run speaker diarization (pyannote.audio). Requires "
            "`[diarization]` extra and HF_TOKEN env var. Prepends each "
            "segment's text with `[SPEAKER_NN]`."
        ),
        section="smart",
    ),
    OptionField(
        key="diarize_num_speakers", type=int, default=0,
        choices=None,
        description=(
            "If known, constrain diarization to this exact number of "
            "speakers. 0 = auto-detect."
        ),
        section="smart",
    ),
    # === Translation (v0.5) ===
    OptionField(
        key="translate_to", type=str, default="",
        choices=None,
        description=(
            "Target language for auto-translation (ISO code like 'en', "
            "'ru', 'es', or full name 'English'). Empty = no translation."
        ),
        section="output",
    ),
    OptionField(
        key="translate_backend", type=str, default="gemini",
        choices=["gemini", "claude", "openai", "ollama"],
        description="LLM provider for translation (same options as correct_asr).",
        section="output",
    ),
    # === Custom vision prompt (v0.5.1) ===
    OptionField(
        key="vision_prompt_path", type=str, default="",
        choices=None,
        description=(
            "Path to a file with a custom vision prompt template. "
            "Must use placeholders {language}, {transcript_snippet}, "
            "{start_sec}, {end_sec}."
        ),
        section="vision",
    ),
    # === Tutorial / UI-action mode (v0.10) ===
    OptionField(
        key="asymmetric_frames", type=bool, default=False,
        choices=None,
        description=(
            "Speech-anchored frame offsets (-1.5s / +0.3s / +2.0s) "
            "instead of evenly spaced. Captures before-state, the click "
            "moment (motor lag from speech), and post-action UI state. "
            "Default on in the tutorial preset; off elsewhere."
        ),
        section="vision",
    ),
    OptionField(
        key="claude_fallback", type=bool, default=False,
        choices=None,
        description=(
            "After Gemini annotation, re-process low-confidence segments "
            "(confidence < 0.7 or needs_refinement) through Claude. "
            "Improves accuracy on small UI text / similar-looking elements "
            "without paying Claude prices for the entire video."
        ),
        section="vision",
    ),
    OptionField(
        key="auto_tutorial_detect", type=bool, default=True,
        choices=None,
        description=(
            "When using the smart preset, count tutorial-action triggers "
            "(click / press / нажимаем / выбираем / ...) in the transcript "
            "and auto-switch to tutorial preset if density exceeds the "
            "threshold. Set to false to disable auto-promotion."
        ),
        section="smart",
    ),
]


def get_field(key: str) -> OptionField | None:
    for f in REGISTRY:
        if f.key == key:
            return f
    return None


def fields_by_section() -> dict[str, list[OptionField]]:
    out: dict[str, list[OptionField]] = {}
    for f in REGISTRY:
        out.setdefault(f.section, []).append(f)
    return out
