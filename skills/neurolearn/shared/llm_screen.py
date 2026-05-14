"""LLM-based pre-screening of candidate videos by title+metadata.

Used by --filter flag in research and subscribes. Sends a structured
prompt to the chosen LLM backend and expects a JSON array of 1-based
indices back. Falls back to keeping all candidates if the response
can't be parsed.
"""
from __future__ import annotations

import json
import re
from typing import TypeVar

from skills.neurolearn.analyze.runner import run_analysis

T = TypeVar("T")


def screen_candidates(
    candidates: list[T],
    filter_text: str | None,
    *,
    backend: str,
    api_key: str | None,
    ollama_model: str = "llama3.2:3b",
    ollama_host: str = "http://localhost:11434",
) -> list[T]:
    """Return subset chosen by the LLM, or all candidates on parse failure.

    `candidates` must have `.title` and optionally `.channel`,
    `.upload_date`, `.duration_sec` attributes.
    """
    if not filter_text or not candidates:
        return list(candidates)

    prompt = _build_prompt(candidates, filter_text)
    response = run_analysis(
        prompt,
        backend=backend,
        api_key=api_key,
        ollama_model=ollama_model,
        ollama_host=ollama_host,
    )

    indices = _extract_indices(response, total=len(candidates))
    if indices is None:
        return list(candidates)
    return [candidates[i - 1] for i in indices if 1 <= i <= len(candidates)]


def _build_prompt(candidates: list, filter_text: str) -> str:
    lines = [
        "You select videos relevant to the user's filter from a candidate list.",
        "",
        f"User filter: {filter_text}",
        "",
        "Candidates (1-indexed):",
    ]
    for i, c in enumerate(candidates, start=1):
        title = c.title or "(no title)"
        channel = getattr(c, "channel", None) or "?"
        date = getattr(c, "upload_date", None) or "?"
        dur_sec = getattr(c, "duration_sec", None)
        dur = _fmt_dur(dur_sec) if dur_sec else "?"
        lines.append(f"[{i}] {title} — {channel} — {date} — {dur}")
    lines.extend([
        "",
        "Return ONLY a JSON array of selected indices (e.g. [1, 3, 5]).",
        "No prose, no explanation, no code fence.",
    ])
    return "\n".join(lines)


def _fmt_dur(sec: int) -> str:
    mm, ss = divmod(sec, 60)
    hh, mm = divmod(mm, 60)
    return f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"


def _extract_indices(response: str, *, total: int) -> list[int] | None:
    """Parse JSON array of ints from LLM output. None on failure."""
    if not response or not response.strip():
        return None
    # Find first [...] in response (LLM may wrap in code fence or text).
    m = re.search(r"\[[^\]]*\]", response)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    try:
        return [int(x) for x in parsed]
    except (TypeError, ValueError):
        return None
