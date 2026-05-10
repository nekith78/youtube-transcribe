"""Single source of truth for all v0.2 options.

Used by:
- CLI flag generation (Click options)
- TUI prompts (`youtube-transcribe config`)
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
        description="Чем транскрибировать. subtitles = брать готовые с YouTube.",
        section="transcribe",
    ),
    OptionField(
        key="fallback_backend", type=str, default="whisper-local",
        choices=["whisper-local", "gemini", "groq", "openai", "deepgram",
                 "assemblyai", "custom"],
        description="Куда переключиться, если subtitles не подошли (smart-режим).",
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
        description="Сколько keyframes извлекать на одно visual-окно.",
        section="vision",
    ),
    OptionField(
        key="max_windows_per_video", type=int, default=20,
        choices=None,
        description="Максимум окон vision-анализа на одно видео.",
        section="vision",
    ),
    # === detection ===
    OptionField(
        key="detect_method", type=str, default="keywords_only",
        choices=["keywords_only", "semantic", "hybrid", "llm_full_pass"],
        description="Метод поиска визуально-важных моментов.",
        section="detection",
    ),
    # === smart ===
    OptionField(
        key="quality_check", type=bool, default=False,
        choices=None,
        description="Запускать quality check на полученном транскрипте.",
        section="smart",
    ),
    OptionField(
        key="subtitle_quality_threshold", type=float, default=0.6,
        choices=None,
        description="Score < этого → fallback к whisper в smart-режиме.",
        section="smart",
    ),
    OptionField(
        key="quality_perplexity", type=bool, default=False,
        choices=None,
        description="Включить kenlm perplexity (требует extra `perplexity`).",
        section="smart",
    ),
    # === output ===
    OptionField(
        key="ocr", type=bool, default=False,
        choices=None,
        description="OCR на keyframes (требует extra `ocr` + системный tesseract).",
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
