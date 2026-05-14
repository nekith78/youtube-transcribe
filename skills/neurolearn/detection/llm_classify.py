"""LLM full-pass classifier for visual moments (spec §5 brick D).

Sends the entire transcript to a cheap text-only LLM and asks it to
identify time ranges where the visual content is more important than the
spoken audio.

Used only when `detect_method = "llm_full_pass"`. Adds a few targeted
DetectionWindows on top of trigger / scene / frame_diff signals.

Cost (Gemini 2.5-flash):
  ~25k input tokens for a 1h transcript + prompt.
  Free tier (1500 RPD, 1M TPM): one call per video, well within budget.
"""
from __future__ import annotations

import json
import re

from skills.neurolearn.detection.base import DetectionWindow
from skills.neurolearn.utils.output_writer import Segment


_DEFAULT_PROMPT = """\
You are analyzing a YouTube video transcript. Below is the transcript with
timestamps in seconds.

Identify time ranges where the **visual content** is likely MORE important
than the spoken audio. Examples: code being typed on screen, diagrams being
drawn, demonstrations, comparisons of UI states, results being shown.

Return ONLY a JSON array (no preamble, no markdown fence) of objects:

[
  {{"start": 45.0, "end": 60.0, "reason": "<short why>", "score": 0.9}},
  ...
]

Rules:
- start/end in seconds (floats).
- score 0.0-1.0 (how visually important).
- Pick at most 10 most important moments. Skip pure talking-head segments.
- If nothing visually noteworthy, return [].

Language for the `reason` field: {language}.

Transcript:
{transcript}
"""


def _format_transcript(segments: list[Segment], max_chars: int = 60_000) -> str:
    """Format segments as `[start_sec - end_sec] text` lines.

    Truncates at ~60k chars (≈15-20k tokens) to stay within free-tier TPM.
    """
    lines = []
    total = 0
    for s in segments:
        line = f"[{s.start:.1f} - {s.end:.1f}] {s.text.strip()}"
        if total + len(line) > max_chars:
            lines.append("[...transcript truncated...]")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def _parse_response(text: str) -> list[dict]:
    """Strip code fences and parse JSON array. Returns [] on any error."""
    text = text.strip()
    # Strip ``` fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


def find_visual_moments_via_llm(
    segments: list[Segment],
    *,
    api_key: str,
    language: str = "en",
    model: str = "gemini-2.5-flash",
) -> list[DetectionWindow]:
    """Send transcript to Gemini text-only API, parse timecode list.

    Returns list[DetectionWindow] with reason="llm_full_pass".
    On any error (network, parsing, empty response) returns [].
    """
    if not segments:
        return []

    transcript = _format_transcript(segments)
    prompt = _DEFAULT_PROMPT.format(language=language, transcript=transcript)

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=model, contents=[prompt])
        items = _parse_response(resp.text or "")
    except Exception:
        return []

    out: list[DetectionWindow] = []
    for item in items:
        try:
            start = float(item["start"])
            end = float(item["end"])
            score = float(item.get("score", 0.7))
            reason_text = str(item.get("reason", "llm-suggested"))[:120]
        except (KeyError, ValueError, TypeError):
            continue
        if end <= start:
            continue
        out.append(DetectionWindow(
            start=max(start, 0.0),
            end=end,
            reason=f"llm_full_pass:{reason_text}",
            score=min(max(score, 0.0), 1.0),
            weight=1.0,
            phrase="",
        ))
    return out
