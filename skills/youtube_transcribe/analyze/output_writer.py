"""Write `analysis-*.md` files for the `analyze` sub-command."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from skills.youtube_transcribe.analyze.source_resolver import VideoSource

_PROMPT_QUOTE_MAX = 200


def analysis_filename(now: datetime) -> str:
    """Default `analysis-YYYY-MM-DD-HHMM.md` filename."""
    return f"analysis-{now:%Y-%m-%d-%H%M}.md"


def write_analysis(
    *,
    out_path: Path,
    body: str,
    user_prompt: str,
    backend_label: str,
    videos: list[VideoSource],
    total_videos: int,
    now: datetime,
) -> Path:
    """Write a fresh analysis file. Resolves filename collisions with `-N`."""
    out_path = _resolve_collision(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        _render_block(
            heading=f"# Analysis — {now:%Y-%m-%d %H:%M}",
            body=body,
            user_prompt=user_prompt,
            backend_label=backend_label,
            videos=videos,
            total_videos=total_videos,
        ),
        encoding="utf-8",
    )
    return out_path


def append_analysis(
    *,
    target: Path,
    body: str,
    user_prompt: str,
    backend_label: str,
    videos: list[VideoSource],
    total_videos: int,
    now: datetime,
) -> Path:
    """Append a block to `target`. Creates with `# Combined analyses` if new."""
    target.parent.mkdir(parents=True, exist_ok=True)
    block = _render_block(
        heading=f"## Analysis — {now:%Y-%m-%d %H:%M}",
        body=body,
        user_prompt=user_prompt,
        backend_label=backend_label,
        videos=videos,
        total_videos=total_videos,
    )
    if target.exists():
        with target.open("a", encoding="utf-8") as f:
            f.write("\n")
            f.write(block)
    else:
        target.write_text(
            "# Combined analyses\n\n" + block,
            encoding="utf-8",
        )
    return target


def _resolve_collision(path: Path) -> Path:
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    for n in range(2, 1000):
        candidate = path.with_name(f"{stem}-{n}{ext}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"too many collisions for {path}")


def _render_block(
    *,
    heading: str,
    body: str,
    user_prompt: str,
    backend_label: str,
    videos: list[VideoSource],
    total_videos: int,
) -> str:
    quote = user_prompt.strip().splitlines()
    quote_text = " ".join(quote)
    if len(quote_text) > _PROMPT_QUOTE_MAX:
        quote_text = quote_text[:_PROMPT_QUOTE_MAX].rstrip() + "..."
    titles_lines = "\n".join(
        f"- {v.title or v.transcript_path.stem}" for v in videos
    )
    return (
        f"{heading}\n\n"
        f"**Backend:** {backend_label}\n"
        f"**Videos:** {len(videos)} of {total_videos}\n"
        f"{titles_lines}\n\n"
        f"**Prompt:**\n> {quote_text}\n\n"
        f"---\n\n"
        f"{body.rstrip()}\n"
    )
