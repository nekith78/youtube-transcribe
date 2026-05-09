"""CLI root + `transcribe` sub-command. Bare-URL form routes to `transcribe`.
The `batch` sub-command is added in Task 20B (registered into the same `cli` group)."""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console

from skills.youtube_transcribe.backends.base import BackendError, BackendNotConfigured
from skills.youtube_transcribe.config import (
    CONFIG_PATH,
    Config,
    load_config,
)
from skills.youtube_transcribe.pipeline import run_pipeline
from skills.youtube_transcribe.utils.downloader import (
    extract_youtube_video_id,
    is_url,
    is_youtube_url,
)
from skills.youtube_transcribe.utils.output_writer import (
    BatchFailure,
    BatchMeta,
    BatchVideoStatus,
    sanitize_filename,
    write_combined_md,
    write_errors_log,
    write_manifest_json,
    write_srt,
    write_txt_plain,
    write_txt_with_timestamps,
)
from skills.youtube_transcribe.utils.resolver import (
    ResolvedTarget,
    ResolverFilters,
    resolve,
)
from skills.youtube_transcribe.wizard import run_wizard

console = Console()

BACKEND_CHOICES = [
    "smart", "subtitles", "whisper-local",
    "gemini", "groq", "openai", "deepgram", "assemblyai", "custom",
]


class _BareURLGroup(click.Group):
    """If the first positional looks like a URL or existing file path,
    inject the implicit `transcribe` sub-command in front of it.

    Required to keep base spec §8 UX (`youtube-transcribe <URL>`)
    while exposing `batch` as a separate sub-command."""

    def resolve_command(self, ctx, args):
        if args and args[0] not in self.commands:
            first = args[0]
            looks_like_input = (
                is_url(first)
                or first.startswith("/") or first.startswith("./") or first.startswith("../")
                or (len(first) > 1 and first[1:3] == ":\\")    # Windows drive
                or Path(first).exists()
            )
            if looks_like_input:
                args = ["transcribe", *args]
        return super().resolve_command(ctx, args)


@click.group(cls=_BareURLGroup)
@click.version_option()
def cli() -> None:
    """youtube-transcribe — transcribe YouTube and local media via 8 backends.

    Use `transcribe <URL_or_path>` for one input.
    Use `batch <inputs...>` for multiple URLs / a channel / a playlist.
    """
    pass


@cli.command(name="transcribe")
@click.argument("audio_or_url")
@click.option("--backend", type=click.Choice(BACKEND_CHOICES), default=None,
              help="Backend to use (overrides config default).")
@click.option("--whisper-model", type=click.Choice(["turbo", "large", "medium", "small", "distil"]),
              default=None, help="Whisper model (only with --backend whisper-local).")
@click.option("--gemini-model", default=None)
@click.option("--groq-model", default=None)
@click.option("--deepgram-model", default=None)
@click.option("--assemblyai-model", default=None)
@click.option("--language", default=None, help="Language code (ru/en/...) or 'auto'.")
@click.option("--output-dir", default=None, help="Output directory.")
@click.option("--timestamps/--no-timestamps", default=None)
@click.option("--srt/--no-srt", default=None)
@click.option("--keep-audio/--delete-audio", default=None)
@click.option("--cookies-from-browser", "cookies_browser", default=None,
              type=click.Choice(["", "chrome", "firefox", "edge", "safari"]))
@click.option("--no-fast-path", is_flag=True, help="Disable subtitles fast-path in smart mode.")
@click.option("--device", default=None)
@click.option("--compute-type", default=None)
@click.option("--beam-size", type=int, default=None)
@click.option("--vad/--no-vad", default=None)
@click.option("--verbose", is_flag=True)
def transcribe_cmd(audio_or_url: str, **opts) -> None:
    """Transcribe a YouTube URL, supported video URL, or local audio/video file."""
    if not CONFIG_PATH.exists():
        run_wizard()

    cfg = load_config(CONFIG_PATH)
    cfg = _override_config(cfg, opts)
    if opts.get("no_fast_path"):
        cfg.fast_path_enabled = False

    targets = resolve([audio_or_url], None, ResolverFilters())
    if len(targets) != 1:
        # Bare URL/file should always resolve to exactly one target.
        # If user passed a channel here, they should use `batch` instead.
        console.print("[red]Этот URL развернулся в несколько видео.[/red] "
                      "Для каналов/плейлистов используй: youtube-transcribe batch <URL> --limit N")
        sys.exit(2)
    target = targets[0]

    output_dir = Path(opts.get("output_dir") or cfg.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = run_pipeline(target, cfg, backend_override=opts.get("backend"))
    except BackendNotConfigured as e:
        console.print(f"[red]Бэкенд не настроен:[/red] {e}")
        sys.exit(3)
    except BackendError as e:
        console.print(f"[red]Ошибка транскрипции:[/red] {e}")
        sys.exit(4)

    base_name = sanitize_filename(_derive_basename(target))
    txt_path = output_dir / f"{base_name}.txt"
    srt_path = output_dir / f"{base_name}.srt"

    timestamps = cfg.timestamps if opts.get("timestamps") is None else opts["timestamps"]
    write_srt_flag = cfg.srt if opts.get("srt") is None else opts["srt"]

    if timestamps:
        write_txt_with_timestamps(result.segments, txt_path)
    else:
        write_txt_plain(result.segments, txt_path)
    if write_srt_flag:
        write_srt(result.segments, srt_path)

    console.print(f"[green]✓[/green] {result.backend_name} | "
                  f"язык={result.language_detected or 'auto'} | "
                  f"длительность={result.duration_seconds:.1f}s")
    console.print(f"  [bold]{txt_path}[/bold]")
    if write_srt_flag:
        console.print(f"  [bold]{srt_path}[/bold]")


def _derive_basename(target: ResolvedTarget) -> str:
    if is_youtube_url(target.url):
        vid = extract_youtube_video_id(target.url)
        return f"yt_{vid}" if vid else "url_transcript"
    if is_url(target.url):
        return "url_transcript"
    return Path(target.url).stem


def _override_config(cfg: Config, opts: dict) -> Config:
    """Apply CLI overrides to a Config copy."""
    if opts.get("whisper_model"): cfg.whisper_model = opts["whisper_model"]
    if opts.get("gemini_model"): cfg.gemini_model = opts["gemini_model"]
    if opts.get("groq_model"): cfg.groq_model = opts["groq_model"]
    if opts.get("deepgram_model"): cfg.deepgram_model = opts["deepgram_model"]
    if opts.get("assemblyai_model"): cfg.assemblyai_model = opts["assemblyai_model"]
    if opts.get("device"): cfg.whisper_device = opts["device"]
    if opts.get("compute_type"): cfg.whisper_compute_type = opts["compute_type"]
    if opts.get("beam_size"): cfg.beam_size = opts["beam_size"]
    if opts.get("vad") is not None: cfg.vad = opts["vad"]
    if opts.get("cookies_browser") is not None: cfg.cookies_browser = opts["cookies_browser"]
    if opts.get("keep_audio") is not None: cfg.keep_audio = opts["keep_audio"]
    return cfg


# ---------------------------------------------------------------------------
# Task 20B — batch sub-command helpers
# ---------------------------------------------------------------------------

def _slugify(s: str, max_len: int = 60) -> str:
    """Kebab-case-ish slug from arbitrary string, max 60 chars."""
    s = re.sub(r"[^\w\-]+", "-", s, flags=re.UNICODE).strip("-")
    return (s[:max_len] or "batch").rstrip("-")


def _auto_batch_name(targets: list[ResolvedTarget], from_file: Path | None) -> str:
    """Generate a batch folder name: batch_<timestamp>_<auto-slug>."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if from_file is not None and not any(t.source != "file" for t in targets):
        return f"batch_{ts}_{_slugify(from_file.stem)}"
    sources = {t.source for t in targets}
    channels = {t.channel for t in targets if t.channel}
    if sources == {"channel"} and len(channels) == 1:
        return f"batch_{ts}_{_slugify(next(iter(channels)))}"
    return f"batch_{ts}_mixed_{len(targets)}"


def _build_video_status(
    idx: int, target: ResolvedTarget, result, files: dict
) -> BatchVideoStatus:
    """Convert a successful pipeline result into a BatchVideoStatus manifest entry."""
    return BatchVideoStatus(
        index=idx,
        url=target.url,
        video_id=target.video_id,
        title=target.title,
        upload_date=target.upload_date,
        duration_sec=target.duration_sec,
        channel=target.channel,
        language_detected=getattr(result, "language_detected", None),
        text=(
            "\n".join(s.text for s in result.segments)
            if result.segments
            else getattr(result, "text", "")
        ),
        files=files,
        status="ok",
        error=None,
    )


def _diagnose_failure_hint(stage: str, error_text: str) -> str | None:
    """Map common errors to actionable user hints."""
    s = error_text.lower()
    if stage == "download" and ("403" in s or "bot" in s or "sign in" in s):
        return "try --cookies-from-browser chrome"
    if stage == "backend" and "api_key" in s.replace(" ", ""):
        return "youtube-transcribe config set-key <backend>"
    return None


def _infer_source_type(targets: list[ResolvedTarget], from_file: Path | None) -> str:
    """Pick BatchMeta.source_type from the resolved targets."""
    if from_file is not None and all(t.source == "file" for t in targets):
        return "file"
    sources = {t.source for t in targets}
    if sources == {"channel"} or sources == {"playlist"}:
        return next(iter(sources))
    if sources == {"inline"}:
        return "inline"
    return "mixed"


# ---------------------------------------------------------------------------
# Task 20B — batch sub-command
# ---------------------------------------------------------------------------

@cli.command(name="batch")
@click.argument("inputs", nargs=-1)
@click.option("--from-file", "from_file", type=click.Path(path_type=Path),
              default=None, help="Файл со списком URL (1 на строку, # — комментарий).")
@click.option("--limit", type=int, default=10, show_default=True,
              help="Сколько видео взять из канала/плейлиста.")
@click.option("--batch-name", default=None,
              help="Имя batch-папки (default: batch_<ts>_<auto-slug>).")
@click.option("--no-combined", is_flag=True, help="Не создавать combined.md.")
@click.option("--fail-fast", is_flag=True,
              help="Остановиться на первой ошибке (default: continue-on-error).")
@click.option("--backend", type=click.Choice(BACKEND_CHOICES), default=None)
@click.option("--whisper-model",
              type=click.Choice(["turbo", "large", "medium", "small", "distil"]),
              default=None)
@click.option("--gemini-model", default=None)
@click.option("--groq-model", default=None)
@click.option("--deepgram-model", default=None)
@click.option("--assemblyai-model", default=None)
@click.option("--language", default=None)
@click.option("--output-dir", default=None)
@click.option("--timestamps/--no-timestamps", default=None)
@click.option("--srt/--no-srt", default=None)
@click.option("--keep-audio/--delete-audio", default=None)
@click.option("--cookies-from-browser", "cookies_browser", default=None,
              type=click.Choice(["", "chrome", "firefox", "edge", "safari"]))
@click.option("--no-fast-path", is_flag=True)
@click.option("--device", default=None)
@click.option("--compute-type", default=None)
@click.option("--beam-size", type=int, default=None)
@click.option("--vad/--no-vad", default=None)
@click.option("--verbose", is_flag=True)
def batch_cmd(
    inputs: tuple[str, ...],
    from_file: Path | None,
    limit: int,
    batch_name: str | None,
    no_combined: bool,
    fail_fast: bool,
    **opts,
) -> None:
    """Batch-транскрибация: пачка URL, канал/плейлист, или --from-file.

    KNOWN DEVIATION: `resolve()` raises UnresolvableInput on the *first*
    probe failure instead of collect-and-continue (spec §5). For batch we
    wrap each resolve call in a try/except and record the failure, but only
    the first unresolvable URL per `resolve()` call will be caught; subsequent
    ones will still abort. True per-URL collect-and-continue requires refactoring
    resolve() internals — deferred to v0.3.
    """
    if not CONFIG_PATH.exists():
        run_wizard()

    cfg = load_config(CONFIG_PATH)
    cfg = _override_config(cfg, opts)
    if opts.get("no_fast_path"):
        cfg.fast_path_enabled = False

    targets = resolve(list(inputs), from_file, ResolverFilters(limit=limit))
    if not targets:
        console.print("[yellow]Нет ни одного видео по этому входу.[/yellow]")
        sys.exit(0)

    output_root = Path(opts.get("output_dir") or cfg.output_dir).expanduser()
    name = batch_name or _auto_batch_name(targets, from_file)
    batch_dir = output_root / name
    videos_dir = batch_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    timestamps = cfg.timestamps if opts.get("timestamps") is None else opts["timestamps"]
    write_srt_flag = cfg.srt if opts.get("srt") is None else opts["srt"]

    backend_name = opts.get("backend") or cfg.default_backend
    statuses: list[BatchVideoStatus] = []
    failures: list[BatchFailure] = []

    started = datetime.now()
    for i, target in enumerate(targets, start=1):
        try:
            result = run_pipeline(
                target, cfg,
                backend_override=opts.get("backend"),
                keep_audio_to=(batch_dir / "audio") if cfg.keep_audio else None,
            )
        except BackendNotConfigured as e:
            failures.append(BatchFailure(
                index=i, url=target.url, stage="backend",
                error_text=str(e),
                hint=_diagnose_failure_hint("backend", str(e)),
            ))
            if fail_fast:
                console.print(f"[red]Бэкенд не настроен:[/red] {e}")
                sys.exit(3)
            continue
        except BackendError as e:
            stage = (
                "download"
                if "yt-dlp" in str(e).lower() or "403" in str(e)
                else "backend"
            )
            failures.append(BatchFailure(
                index=i, url=target.url, stage=stage,
                error_text=str(e),
                hint=_diagnose_failure_hint(stage, str(e)),
            ))
            if fail_fast:
                console.print(f"[red]Ошибка транскрипции:[/red] {e}")
                sys.exit(4)
            continue

        # success → write per-video files
        prefix = f"{i:02d}"
        slug = _slugify(target.title or f"video-{i}")
        vid = target.video_id or "local"
        base = f"{prefix}_{slug}_{vid}"
        txt_path = videos_dir / f"{base}.txt"
        srt_path = videos_dir / f"{base}.srt"
        if timestamps:
            write_txt_with_timestamps(result.segments, txt_path)
        else:
            write_txt_plain(result.segments, txt_path)
        if write_srt_flag:
            write_srt(result.segments, srt_path)
        statuses.append(_build_video_status(
            i, target, result,
            files={
                "txt": str(txt_path.relative_to(batch_dir)),
                "srt": str(srt_path.relative_to(batch_dir)) if write_srt_flag else None,
            },
        ))

    meta = BatchMeta(
        batch_name=name,
        created_at=started,
        source_type=_infer_source_type(targets, from_file),
        source_url=(
            targets[0].url if all(t.source == "channel" for t in targets) else None
        ),
        backend=backend_name,
        backend_options={
            k: v for k, v in {
                "whisper_model": opts.get("whisper_model"),
                "gemini_model": opts.get("gemini_model"),
                "groq_model": opts.get("groq_model"),
                "deepgram_model": opts.get("deepgram_model"),
                "assemblyai_model": opts.get("assemblyai_model"),
            }.items() if v
        },
        language=cfg.language,
    )

    if not no_combined:
        write_combined_md(statuses, meta, batch_dir)
    write_manifest_json(statuses, failures, meta, batch_dir)
    write_errors_log(failures, batch_dir)

    elapsed = (datetime.now() - started).total_seconds()
    console.print(
        f"\n[green]✓[/green] {len(statuses)} ok   "
        f"[red]✗[/red] {len(failures)} failed   "
        f"Total: {len(statuses) + len(failures)}   Elapsed: {elapsed:.0f}s"
    )
    console.print(f"\n  [bold]{batch_dir}/[/bold]")
    if not no_combined:
        console.print("  ├── combined.md")
    console.print("  ├── manifest.json")
    console.print(f"  └── videos/  ({len(statuses)} transcripts)")
    if failures:
        console.print(f"  └── errors.log  ({len(failures)} failures)")
    console.print(
        '\n  [dim]Next:[/dim] ask Claude → '
        '"прочти combined.md и сделай заметку по теме"\n'
    )


# Task 21 will register `config` sub-group.
# Keeping that explicit in __all__ to make the module-level extension contract obvious.
__all__ = ["cli", "transcribe_cmd", "batch_cmd"]


if __name__ == "__main__":
    cli()
