"""Auto-translate transcript segments via LLM (spec v0.5).

Translates each segment's text to a target language while preserving
timestamps and structure. Same provider-set as ASR correction:
gemini / claude / openai / ollama. Best-effort: failures return originals.

Use cases:
- Watch a Russian tutorial, ask for English transcript
- Watch English content with non-native viewers, output in Russian/Spanish/...

One LLM call per video. Cheap: gemini-flash, claude-haiku, gpt-4o-mini.
"""
from __future__ import annotations

import json
import re

from skills.youtube_transcribe.quality.asr_corrector import (
    _call_claude, _call_gemini, _call_ollama, _call_openai,
)
from skills.youtube_transcribe.utils.output_writer import Segment


_TRANSLATE_PROMPT = """\
Translate the following transcript from {source_lang} to {target_lang}.

Rules:
- Same number of segments as input.
- Preserve each segment's `start` and `end` exactly (do not change timing).
- Translate the `text` of each segment naturally.
- Preserve speaker labels like `[SPEAKER_00]` at the start of text — keep
  them as-is, only translate the spoken content after them.
- Preserve technical terms, code, brand names, and proper nouns verbatim
  when they wouldn't normally be translated.

Input transcript (JSON):
{transcript_json}

Output: JSON array of {{start, end, text}}, same length as input, with
text translated into {target_lang}. Return ONLY the JSON, no preamble,
no markdown fence.
"""


def _build_input_json(segments: list[Segment]) -> str:
    payload = [
        {"start": float(s.start), "end": float(s.end), "text": s.text}
        for s in segments
    ]
    return json.dumps(payload, ensure_ascii=False)


def _parse_translated(raw: str, original: list[Segment]) -> list[Segment]:
    """Parse LLM response. On any error, return `original` unchanged."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return original
    if not isinstance(data, list) or len(data) != len(original):
        return original

    out: list[Segment] = []
    for orig, item in zip(original, data):
        if not isinstance(item, dict) or "text" not in item:
            return original
        out.append(Segment(start=orig.start, end=orig.end, text=str(item["text"])))
    return out


def translate_transcript(
    segments: list[Segment],
    source_lang: str,
    target_lang: str,
    *,
    api_key: str | None,
    backend: str = "gemini",
    ollama_model: str = "llama3.2:3b",
    ollama_host: str = "http://localhost:11434",
) -> list[Segment]:
    """Translate transcript to target_lang. Best-effort.

    Skips translation if source_lang == target_lang.
    Returns original segments unchanged on any failure.
    """
    if not segments:
        return segments
    if source_lang and target_lang and source_lang.lower() == target_lang.lower():
        return segments

    transcript_json = _build_input_json(segments)
    prompt = _TRANSLATE_PROMPT.format(
        source_lang=source_lang or "auto-detect",
        target_lang=target_lang,
        transcript_json=transcript_json,
    )

    try:
        if backend == "gemini":
            text = _call_gemini(prompt, api_key or "")
        elif backend == "claude":
            text = _call_claude(prompt, api_key or "")
        elif backend == "openai":
            text = _call_openai(prompt, api_key or "")
        elif backend == "ollama":
            text = _call_ollama(prompt, model=ollama_model, host=ollama_host)
        else:
            return segments
    except Exception:
        return segments

    return _parse_translated(text, segments)
