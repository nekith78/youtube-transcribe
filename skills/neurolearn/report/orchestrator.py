"""High-level orchestrator — manifest + transcript → PDF report.

This is the glue that the CLI calls. It does NOT do LLM work or PDF
rendering itself — it delegates to `outliner` and `renderer`. The
goal is one well-named entry point users (and the CLI) can call.

Pipeline:
  1. Load manifest.json from batch_dir, pick the target video entry.
  2. Reconstruct Segment[] from the SRT file (timing-accurate).
  3. Resolve report_type (CLI override → auto-detect → generic).
  4. Resolve target_language (CLI override → manifest's detected lang
     → "en").
  5. Call `outliner.build_outline` → Outline.
  6. Call `renderer.render_pdf` → PDF.

Returns a `ReportResult` with paths and metadata for the CLI to show
the user.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from skills.neurolearn.report.outliner import Outline, build_outline
from skills.neurolearn.report.prompts import (
    DEFAULT_REPORT_TYPE, map_video_type_to_report_type,
)
from skills.neurolearn.report.renderer import render_pdf
from skills.neurolearn.utils.output_writer import Segment


@dataclass
class ReportResult:
    """Everything the CLI needs after a successful render."""
    pdf_path: Path
    html_path: Path | None
    batch_dir: Path
    report_type: str
    target_language: str
    video_title: str
    section_count: int
    used_hierarchical: bool
    outline: Outline
    meta: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_report(
    *,
    batch_dir: Path | str,
    video_index: int = 0,
    output_path: Path | None = None,
    backend: str = "gemini",
    api_key: str | None = None,
    user_filter: str = "",
    custom_template: str | None = None,
    report_type: str | None = None,
    target_language: str | None = None,
    include_screenshots: bool = True,
    max_images: int = 50,
    image_max_width: int = 1000,
    keep_html: bool = False,
    version: str = "",
    ollama_model: str = "llama3.2:3b",
    ollama_host: str = "http://localhost:11434",
) -> ReportResult:
    """Produce a PDF report for one video inside a batch_dir.

    Most parameters mirror the CLI flags. `video_index` picks the
    target video when the batch has more than one (default: the first).
    """
    batch_dir = Path(batch_dir).resolve()
    manifest = _load_manifest(batch_dir)
    video = _pick_video(manifest, video_index)

    segments = _segments_from_video_entry(batch_dir, video)
    visual_segments = video.get("visual_segments") or []

    if report_type is None or report_type == "auto":
        detected_video_type = _detect_video_type_safe(segments)
        report_type = map_video_type_to_report_type(detected_video_type)
    elif report_type not in {"tutorial", "vlog", "generic"} and (
        custom_template is None
    ):
        # Unknown user-supplied type but no inline custom template —
        # fall back to generic so we don't crash.
        report_type = DEFAULT_REPORT_TYPE

    if target_language is None or target_language.lower() == "auto":
        target_language = (
            video.get("language_detected")
            or video.get("source_language")
            or "en"
        )

    outline = build_outline(
        segments=segments,
        visual_segments=visual_segments,
        report_type=report_type,
        target_language=target_language,
        user_filter=user_filter,
        backend=backend,
        api_key=api_key,
        custom_template=custom_template,
        ollama_model=ollama_model,
        ollama_host=ollama_host,
    )

    pdf_path = _resolve_output_path(output_path, batch_dir, video)

    meta = _build_meta(video, manifest, report_type)

    render_pdf(
        outline,
        output_path=pdf_path,
        batch_dir=batch_dir,
        lang=target_language,
        include_screenshots=include_screenshots,
        max_images=max_images,
        image_max_width=image_max_width,
        meta=meta,
        version=version,
        keep_html=keep_html,
    )

    return ReportResult(
        pdf_path=pdf_path,
        html_path=pdf_path.with_suffix(".html") if keep_html else None,
        batch_dir=batch_dir,
        report_type=report_type,
        target_language=target_language,
        video_title=video.get("title", "(untitled)") or "(untitled)",
        section_count=len(outline.sections),
        used_hierarchical=outline.used_hierarchical,
        outline=outline,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Manifest + transcript loading
# ---------------------------------------------------------------------------


def _load_manifest(batch_dir: Path) -> dict[str, Any]:
    mf = batch_dir / "manifest.json"
    if not mf.exists():
        raise FileNotFoundError(
            f"manifest.json not found in {batch_dir}. "
            "Pass a valid batch directory produced by transcribe/batch."
        )
    return json.loads(mf.read_text(encoding="utf-8"))


def _pick_video(manifest: dict[str, Any], video_index: int) -> dict[str, Any]:
    videos = manifest.get("videos") or []
    if not videos:
        raise ValueError("Manifest contains zero videos.")
    if video_index < 0 or video_index >= len(videos):
        raise IndexError(
            f"video_index={video_index} out of range "
            f"(batch has {len(videos)} videos)."
        )
    return videos[video_index]


def _segments_from_video_entry(
    batch_dir: Path, video: dict[str, Any],
) -> list[Segment]:
    files = video.get("files") or {}
    srt_rel = files.get("srt")
    if srt_rel:
        srt_path = batch_dir / srt_rel
        if srt_path.exists():
            return list(_parse_srt(srt_path))

    txt_rel = files.get("txt")
    if txt_rel:
        txt_path = batch_dir / txt_rel
        if txt_path.exists():
            return _segments_from_txt(txt_path, video.get("duration_sec", 0))

    return []


_SRT_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _parse_srt(path: Path) -> list[Segment]:
    """Cheap-and-cheerful SRT parser. Skips index lines and empties."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # Split into blocks separated by blank lines.
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    segs: list[Segment] = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        # First line could be the index OR the timing — handle both.
        time_line = None
        text_lines: list[str] = []
        for ln in lines:
            if _SRT_TIME_RE.search(ln):
                time_line = ln
            elif time_line is None and ln.strip().isdigit():
                continue   # index line
            else:
                text_lines.append(ln)
        if not time_line:
            continue
        m = _SRT_TIME_RE.search(time_line)
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
        start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000.0
        end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000.0
        if not text_lines:
            continue
        segs.append(Segment(
            start=start, end=end, text=" ".join(text_lines).strip(),
        ))
    return segs


def _segments_from_txt(path: Path, duration_sec: float | int) -> list[Segment]:
    """Last-resort: split plain .txt into pseudo-segments by paragraph.
    Time is evenly distributed across `duration_sec`. Used only when no
    SRT is available."""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []
    total = float(duration_sec or 60 * len(paragraphs))
    step = total / max(1, len(paragraphs))
    return [
        Segment(start=i * step, end=(i + 1) * step, text=p)
        for i, p in enumerate(paragraphs)
    ]


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------


def _detect_video_type_safe(segments: list[Segment]) -> str:
    """Best-effort video_type detection. Falls back to 'generic' if the
    detector module raises (e.g. missing optional dep) — never blocks
    report generation on a heuristic failure."""
    try:
        from skills.neurolearn.detection.video_type_detect import (
            detect_video_type,
        )
        return detect_video_type(segments).video_type
    except Exception:
        return "generic"


# ---------------------------------------------------------------------------
# Output path resolution
# ---------------------------------------------------------------------------


def _resolve_output_path(
    explicit: Path | None,
    batch_dir: Path,
    video: dict[str, Any],
) -> Path:
    if explicit is not None:
        return Path(explicit)
    title = video.get("title") or "report"
    safe = re.sub(r"[^A-Za-z0-9_\-]+", "-", title).strip("-")[:60] or "report"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return batch_dir / f"report_{safe}_{stamp}.pdf"


# ---------------------------------------------------------------------------
# Meta block — header info displayed in the report
# ---------------------------------------------------------------------------


def _build_meta(
    video: dict[str, Any], manifest: dict[str, Any], report_type: str,
) -> dict[str, Any]:
    duration = video.get("duration_sec")
    if isinstance(duration, (int, float)) and duration > 0:
        h = int(duration) // 3600
        m = (int(duration) % 3600) // 60
        s = int(duration) % 60
        duration_str = (
            f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"
        )
    else:
        duration_str = ""

    return {
        "source_url": video.get("url", "") or "",
        "channel": video.get("channel", "") or "",
        "duration": duration_str,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "report_type": report_type,
        "batch_name": manifest.get("batch_name", "") or "",
    }
