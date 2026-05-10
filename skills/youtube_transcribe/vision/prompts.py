"""Prompt templates for vision-LLM annotation of video moments."""
from __future__ import annotations

DEFAULT_PROMPT = """\
You are analyzing a YouTube video. Below is the transcript snippet for a specific
moment. Describe what is shown VISUALLY on the screen during this moment in
{language}, structured as JSON with these keys:
- description: 1-3 sentences. What is happening visually. Mention UI, code,
  diagrams, demonstrations. NOT what is said.
- key_objects: list of distinct visual objects/UI-elements/code-fragments shown.
- importance: "high" | "medium" | "low" — how visually informative is this moment
  beyond the spoken content.

Transcript context (audio only):
{transcript_snippet}

Time window: {start_sec:.1f}s — {end_sec:.1f}s.

Return ONLY valid JSON, no preamble.
"""


def format_prompt(
    template: str,
    *,
    language: str,
    transcript_snippet: str,
    start_sec: float,
    end_sec: float,
) -> str:
    return template.format(
        language=language,
        transcript_snippet=transcript_snippet,
        start_sec=start_sec,
        end_sec=end_sec,
    )
