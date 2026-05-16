"""LLM-driven outline builder for report generation.

Takes already-produced visual_segments + transcript and returns a
structured `Outline` ready for the renderer.

Two routing modes:
  • Short video (transcript under _SHORT_VIDEO_THRESHOLD_TOKENS) →
    single LLM call. Lower overhead, fine quality for typical content.
  • Long video → hierarchical: split transcript into chunks, run a
    per-chunk LLM call to get partial section list, then a final
    assembly call to weld everything together with a coherent TOC.

The LLM is invoked via `skills.neurolearn.analyze.runner.run_analysis`
— the same runner already used by `analyze` command. It abstracts
gemini/claude/openai/ollama so this module doesn't have to.

Outline shape is JSON-serializable for embedding into manifest.json
and for debugging via `--keep-json` flag.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from skills.neurolearn.analyze.runner import run_analysis
from skills.neurolearn.report.prompts import (
    format_report_prompt, load_report_prompt,
)


# Heuristic: words → tokens (~4 chars per token average). Real
# tokenization varies by provider; we err on the side of overestimating
# so we don't accidentally feed too much to the model.
_CHARS_PER_TOKEN = 4

# Above this many transcript tokens we switch to hierarchical mode.
# Picked to keep each LLM call comfortable on attention budget — even
# gemini-2.5-flash with 1M context degrades attention past ~30k input.
_SHORT_VIDEO_THRESHOLD_TOKENS = 15_000

# Target chunk size for hierarchical mode. Each chunk should be small
# enough for the model to attend to fully (under ~10k input tokens of
# transcript text plus the prompt overhead).
_CHUNK_TARGET_TOKENS = 8_000


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """One section of the final report outline."""
    title: str
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    image_refs: list[str] = field(default_factory=list)
    timestamps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Outline:
    """Full report outline ready for rendering."""
    title: str = ""
    summary: str = ""
    sections: list[Section] = field(default_factory=list)
    # Internal debug fields — never rendered, useful in --keep-json mode.
    source_chunks: int = 1
    used_hierarchical: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections],
            "_meta": {
                "source_chunks": self.source_chunks,
                "used_hierarchical": self.used_hierarchical,
            },
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_outline(
    *,
    segments: list,                   # list[Segment] from transcription
    visual_segments: list[dict],      # list of dicts from manifest.json
    report_type: str,                 # "tutorial" | "vlog" | "generic" | ...
    target_language: str,             # "en" | "ru" | ...
    user_filter: str = "",            # user --prompt content, optional
    backend: str = "gemini",          # analyze backend
    api_key: str | None = None,       # backend API key
    custom_template: str | None = None,   # CLI --prompt-file content, optional
    use_global_prefix: bool = True,
    ollama_model: str = "llama3.2:3b",
    ollama_host: str = "http://localhost:11434",
) -> Outline:
    """Produce a structured outline for the report.

    Routes between short-video (single call) and long-video
    (hierarchical) automatically based on transcript length. Returns
    a populated Outline; on LLM/parse failure returns a degraded
    outline so the renderer can still produce a PDF.
    """
    if not segments:
        return Outline()

    transcript_text = _join_transcript(segments)
    token_estimate = _estimate_tokens(transcript_text)

    # Resolve the prompt template once — same for both routing modes.
    spec = load_report_prompt(
        report_type,
        custom_template=custom_template,
        use_global_prefix=use_global_prefix,
    )

    if token_estimate <= _SHORT_VIDEO_THRESHOLD_TOKENS:
        return _build_outline_single_call(
            transcript_text=transcript_text,
            visual_segments=visual_segments,
            spec_template=spec.template,
            target_language=target_language,
            user_filter=user_filter,
            backend=backend,
            api_key=api_key,
            ollama_model=ollama_model,
            ollama_host=ollama_host,
        )

    return _build_outline_hierarchical(
        segments=segments,
        visual_segments=visual_segments,
        spec_template=spec.template,
        target_language=target_language,
        user_filter=user_filter,
        backend=backend,
        api_key=api_key,
        ollama_model=ollama_model,
        ollama_host=ollama_host,
    )


# ---------------------------------------------------------------------------
# Single-call path
# ---------------------------------------------------------------------------


def _build_outline_single_call(
    *,
    transcript_text: str,
    visual_segments: list[dict],
    spec_template: str,
    target_language: str,
    user_filter: str,
    backend: str,
    api_key: str | None,
    ollama_model: str = "llama3.2:3b",
    ollama_host: str = "http://localhost:11434",
) -> Outline:
    """One shot — for short videos."""
    visual_excerpt = _render_visual_segments(visual_segments)
    prompt = _build_full_prompt(
        spec_template=spec_template,
        target_language=target_language,
        user_filter=user_filter,
        transcript_excerpt=transcript_text,
        visual_segments_excerpt=visual_excerpt,
    )
    raw = run_analysis(
        prompt, backend=backend, api_key=api_key,
        ollama_model=ollama_model, ollama_host=ollama_host,
    )
    outline = _parse_outline_response(raw)
    outline.source_chunks = 1
    outline.used_hierarchical = False
    return outline


# ---------------------------------------------------------------------------
# Hierarchical path
# ---------------------------------------------------------------------------


def _build_outline_hierarchical(
    *,
    segments: list,
    visual_segments: list[dict],
    spec_template: str,
    target_language: str,
    user_filter: str,
    backend: str,
    api_key: str | None,
    ollama_model: str = "llama3.2:3b",
    ollama_host: str = "http://localhost:11434",
) -> Outline:
    """Long-video path. Chunks transcript by time, runs one LLM call per
    chunk, then a final assembly call to weld outputs together."""
    chunks = _split_into_chunks(segments, target_tokens=_CHUNK_TARGET_TOKENS)
    if not chunks:
        return Outline()

    # Step 1: per-chunk outlines.
    partial_outlines: list[Outline] = []
    for chunk in chunks:
        chunk_text = _join_transcript(chunk)
        chunk_visuals = _filter_visuals_for_chunk(visual_segments, chunk)
        chunk_visual_excerpt = _render_visual_segments(chunk_visuals)
        prompt = _build_full_prompt(
            spec_template=spec_template,
            target_language=target_language,
            user_filter=user_filter,
            transcript_excerpt=chunk_text,
            visual_segments_excerpt=chunk_visual_excerpt,
        )
        raw = run_analysis(
            prompt, backend=backend, api_key=api_key,
            ollama_model=ollama_model, ollama_host=ollama_host,
        )
        partial = _parse_outline_response(raw)
        partial_outlines.append(partial)

    # Step 2: final assembly. Combine all partial sections into one
    # coherent outline. We use a light LLM call here ONLY to set the
    # top-level title + summary; the sections concatenate mechanically
    # (the per-chunk LLM already structured them correctly).
    all_sections: list[Section] = []
    for p in partial_outlines:
        all_sections.extend(p.sections)

    final = Outline(
        title=partial_outlines[0].title if partial_outlines else "",
        summary=" ".join(p.summary for p in partial_outlines if p.summary)[:500],
        sections=all_sections,
        source_chunks=len(chunks),
        used_hierarchical=True,
    )

    # If we have multiple chunks, ask the LLM to produce a top-level
    # title + executive summary covering everything. The sections stay
    # as they are. Failures here are non-fatal — we keep the
    # mechanical assembly.
    if len(partial_outlines) > 1:
        assembly_prompt = _build_assembly_prompt(
            partial_outlines, target_language, user_filter,
        )
        try:
            raw = run_analysis(
                assembly_prompt, backend=backend, api_key=api_key,
                ollama_model=ollama_model, ollama_host=ollama_host,
            )
            assembled = _parse_outline_response(raw)
            if assembled.title:
                final.title = assembled.title
            if assembled.summary:
                final.summary = assembled.summary
        except Exception:
            pass

    return final


def _build_assembly_prompt(
    partials: list[Outline], target_language: str, user_filter: str,
) -> str:
    """Build a compact prompt asking the LLM for just a top-level
    title + summary covering the per-chunk outlines below."""
    section_titles = []
    for i, p in enumerate(partials):
        for s in p.sections:
            section_titles.append(f"  - {s.title}")
    titles_block = "\n".join(section_titles[:60])
    return (
        f"Output language: {target_language}.\n"
        f"User filter: {user_filter or '(none)'}\n\n"
        "You have a list of section titles from a long video already "
        "broken into chapter outlines. Produce a top-level title and "
        "a 2-3 sentence executive summary covering the whole video.\n\n"
        "Return JSON: {\"title\": \"...\", \"summary\": \"...\"}\n"
        "No preamble, no markdown fences.\n\n"
        f"SECTION TITLES:\n{titles_block}\n"
    )


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _build_full_prompt(
    *,
    spec_template: str,
    target_language: str,
    user_filter: str,
    transcript_excerpt: str,
    visual_segments_excerpt: str,
) -> str:
    """Append the actual transcript + visuals to the rendered template.

    Templates focus on instructions and don't need to reference
    placeholders themselves — we always tack the content block onto
    the end. This way user-supplied templates (CLI --prompt-template-file
    or ~/.neurolearn/report_prompts.toml) work without any placeholder
    bookkeeping.
    """
    rendered = format_report_prompt(
        spec_template,
        target_language=target_language,
        user_filter=user_filter,
        transcript_excerpt="",      # consumed by content block below
        visual_segments_excerpt="",
    )
    content_block = (
        "\n\n"
        "=== TRANSCRIPT (timestamps in [HH:MM:SS]) ===\n"
        f"{transcript_excerpt}\n\n"
        "=== VISUAL SEGMENTS ===\n"
        f"{visual_segments_excerpt}\n\n"
        "Now produce the JSON outline. No preamble. No markdown fences."
    )
    return rendered + content_block


def _split_into_chunks(segments: list, *, target_tokens: int) -> list[list]:
    """Split a flat segment list into contiguous time-ordered chunks
    where each chunk fits roughly within `target_tokens`. Preserves
    segment order within each chunk."""
    if not segments:
        return []

    chunks: list[list] = []
    current: list = []
    current_tokens = 0
    for seg in segments:
        seg_tokens = _estimate_tokens(getattr(seg, "text", "") or "")
        if current and current_tokens + seg_tokens > target_tokens:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(seg)
        current_tokens += seg_tokens
    if current:
        chunks.append(current)
    return chunks


def _filter_visuals_for_chunk(
    visual_segments: list[dict], chunk: list,
) -> list[dict]:
    """Keep only the visuals whose timestamp falls within this chunk."""
    if not chunk:
        return []
    chunk_start = float(getattr(chunk[0], "start", 0.0) or 0.0)
    chunk_end = float(getattr(chunk[-1], "end", 0.0) or 0.0)
    out = []
    for vs in visual_segments:
        s = float(vs.get("start", 0.0))
        if chunk_start <= s <= chunk_end:
            out.append(vs)
    return out


# ---------------------------------------------------------------------------
# Helpers — transcript serialization and parsing
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Cheap char-based estimate. Real tokenizers vary by provider."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _join_transcript(segments: list) -> str:
    """Flatten segments into a single string with [HH:MM:SS] markers
    so the LLM can cite timestamps in its output."""
    lines: list[str] = []
    for seg in segments:
        start = float(getattr(seg, "start", 0.0) or 0.0)
        text = getattr(seg, "text", "") or ""
        if text.strip():
            lines.append(f"[{_format_timestamp(start)}] {text.strip()}")
    return "\n".join(lines)


def _render_visual_segments(visual_segments: list[dict]) -> str:
    """Serialize visual_segments[] into a compact text block for the prompt."""
    if not visual_segments:
        return "(no visual segments)"
    lines = []
    for vs in visual_segments:
        start = float(vs.get("start", 0.0))
        desc = (vs.get("description") or "").strip()
        kfs = vs.get("keyframes") or []
        importance = vs.get("importance", "medium")
        kf_str = ", ".join(kfs[:3]) if kfs else ""
        lines.append(
            f"[{_format_timestamp(start)}] ({importance}) {desc}"
            + (f"\n  keyframes: {kf_str}" if kf_str else "")
        )
    return "\n".join(lines)


def _format_timestamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _parse_outline_response(raw: str) -> Outline:
    """Parse the LLM's JSON response into an Outline. Resilient to
    common formatting noise (markdown fences, leading commentary)."""
    if not raw:
        return Outline()
    text = raw.strip()
    # Strip ```json or plain ``` fences if the model included them.
    if text.startswith("```"):
        # Drop the first fence line and the trailing fence.
        lines = text.split("\n")
        # Skip opening ```...
        lines = lines[1:]
        # Drop trailing ``` if present.
        while lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try to extract the first JSON object — some models prepend
    # explanation despite our instructions.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Degraded mode: return raw text in a single section so the
        # user sees SOMETHING instead of an empty PDF.
        return Outline(
            title="Outline parse failed",
            summary="LLM response could not be parsed as JSON.",
            sections=[Section(
                title="Raw model output",
                summary=raw[:1000],
            )],
        )

    if not isinstance(data, dict):
        return Outline(
            title="Outline parse failed",
            sections=[Section(title="Unexpected response shape")],
        )

    title = str(data.get("title", "") or "")
    summary = str(data.get("summary", "") or "")
    raw_sections = data.get("sections", []) or []
    sections: list[Section] = []
    if isinstance(raw_sections, list):
        for raw_s in raw_sections:
            if not isinstance(raw_s, dict):
                continue
            sections.append(Section(
                title=str(raw_s.get("title", "") or ""),
                summary=str(raw_s.get("summary", "") or ""),
                key_points=_coerce_str_list(raw_s.get("key_points")),
                image_refs=_coerce_str_list(raw_s.get("image_refs")),
                timestamps=[
                    _normalize_timestamp(t)
                    for t in _coerce_str_list(raw_s.get("timestamps"))
                ],
            ))

    return Outline(title=title, summary=summary, sections=sections)


def _normalize_timestamp(ts: str) -> str:
    """Strip surrounding [] / spaces — the renderer adds its own brackets."""
    return ts.strip().strip("[]").strip()


def _coerce_str_list(value: Any) -> list[str]:
    """Normalize a JSON value to a list[str].

    LLMs sometimes return a single string where the schema expects a
    list — without this, Python iterates that string and we end up
    with one entry per character. Also tolerates list-of-mixed-types
    by stringifying and dropping None entries."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for p in value:
            if p is None:
                continue
            if isinstance(p, (str, int, float)):
                out.append(str(p))
        return out
    return []
