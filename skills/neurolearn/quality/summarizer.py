"""LLM-based summary of transcripts.

Thin wrapper over analyze.runner with a hardcoded structured
TL;DR + key points + notable quotes prompt template. Kept as a
separate entry point for backwards compatibility with v0.5 callers
and the existing `neurolearn summarize` CLI.
"""
from __future__ import annotations

from skills.neurolearn.utils.output_writer import Segment
from skills.neurolearn.analyze import runner as analyze_runner


_SUMMARY_PROMPT = """\
You are summarizing a video transcript. Produce a structured Markdown
summary in {language}.

Format (use these EXACT section headers):

## TL;DR
<one paragraph, 2-4 sentences>

## Key points
- <bullet 1>
- <bullet 2>
- ...

## Notable quotes
- [HH:MM:SS] "<quote>"
- ...

Rules:
- Be concise. Don't repeat the same idea twice.
- Quotes should be exact spans from the transcript (not paraphrased).
- Timestamps in `HH:MM:SS` (no fractional seconds).
- 3–7 key points; 0–5 notable quotes.

Transcript (with timecodes in seconds):
{transcript_text}

Output ONLY the markdown summary. No preamble, no code fence.
"""


def _format_transcript_for_summary(segments: list[Segment]) -> str:
    """Compact `[HH:MM:SS] text` lines, truncated at 60k chars."""
    lines = []
    total = 0
    for s in segments:
        h = int(s.start // 3600)
        m = int((s.start % 3600) // 60)
        sec = int(s.start % 60)
        line = f"[{h:02d}:{m:02d}:{sec:02d}] {s.text.strip()}"
        if total + len(line) > 60_000:
            lines.append("[...truncated...]")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def summarize_transcript(
    segments: list[Segment],
    language: str = "en",
    *,
    api_key: str | None,
    backend: str = "gemini",
    ollama_model: str = "llama3.2:3b",
    ollama_host: str = "http://localhost:11434",
) -> str:
    """Return Markdown summary or empty string on failure."""
    if not segments:
        return ""

    prompt = _SUMMARY_PROMPT.format(
        language=language or "en",
        transcript_text=_format_transcript_for_summary(segments),
    )
    try:
        return analyze_runner.run_analysis(
            prompt,
            backend=backend,
            api_key=api_key,
            ollama_model=ollama_model,
            ollama_host=ollama_host,
        )
    except Exception:
        return ""
