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
from skills.youtube_transcribe.backends.factory import build_backend
from skills.youtube_transcribe.config import (
    CONFIG_PATH,
    ENV_PATH,
    Config,
    get_api_key,
    load_config,
    mask_key,
    save_config,
    set_api_key,
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
    write_visual_md,
)
from skills.youtube_transcribe.utils.resolver import (
    ResolvedTarget,
    ResolveFailure,
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
@click.option("--with-visuals", is_flag=True, help="Shortcut for --vision-backend=gemini.")
@click.option("--vision-backend", "vision_backend_opt", type=click.Choice(["off", "gemini"]), default=None,
              help="Visual mode backend. off = audio only.")
@click.option("--detect-method", "detect_method_opt",
              type=click.Choice(["keywords_only", "semantic", "hybrid", "llm_full_pass"]),
              default=None, help="How to find visual moments.")
@click.option("--frames-per-window", "frames_per_window_opt", type=int, default=None)
@click.option("--max-windows", "max_windows_opt", type=int, default=None)
@click.option("--ocr", "ocr_opt", is_flag=True, default=None, help="Run OCR on keyframes (--ocr opt-in).")
@click.option("--check-quality", is_flag=True, default=None,
              help="Force quality check + write to manifest.")
@click.option("--no-quality-check", is_flag=True, default=None,
              help="Skip quality check even in smart preset.")
@click.option("--preset", default=None,
              help="Preset name (eco/smart/standard/premium).")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="External config TOML (alternative to ~/.youtube-transcribe/config.toml).")
@click.option("--triggers", "triggers_path", type=click.Path(exists=True), default=None,
              help="External triggers TOML.")
@click.option("--no-default-triggers", is_flag=True, default=False,
              help="Disable built-in triggers, use only user file.")
@click.option("--correct-asr", "correct_asr_opt", is_flag=True, default=None,
              help="Run LLM-based correction on low-quality transcripts (opt-in).")
@click.option("--correct-asr-backend", "correct_asr_backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]), default=None,
              help="LLM provider for ASR correction (default: gemini; "
                   "ollama=local llama via `ollama serve`).")
@click.option("--diarize", "diarize_opt", is_flag=True, default=None,
              help="Run speaker diarization via pyannote.audio "
                   "(needs HF_TOKEN + `[diarization]` extra).")
@click.option("--translate-to", "translate_to_opt", default=None,
              help="Translate transcript to language (ISO code or name).")
@click.option("--translate-backend", "translate_backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]), default=None,
              help="LLM provider for translation (default: gemini).")
@click.option("--output-format", "output_format_opt",
              type=click.Choice(["all", "txt", "srt", "json"]),
              default=None, multiple=True,
              help="Output format(s). Repeat for multiple. Default: txt+srt.")
@click.option("--vision-prompt", "vision_prompt_path_opt",
              type=click.Path(exists=True), default=None,
              help="Custom vision prompt template (placeholders {language}, "
                   "{transcript_snippet}, {start_sec}, {end_sec}).")
def transcribe_cmd(audio_or_url: str, **opts) -> None:
    """Transcribe a YouTube URL, supported video URL, or local audio/video file."""
    if not CONFIG_PATH.exists():
        run_wizard()

    cfg = load_config(CONFIG_PATH)
    cfg = _override_config(cfg, opts)
    if opts.get("no_fast_path"):
        cfg.fast_path_enabled = False

    targets, failures = resolve([audio_or_url], None, ResolverFilters())
    if failures:
        f = failures[0]
        console.print(f"[red]Не удалось разобрать URL:[/red] {f.url}\n  {f.error}")
        sys.exit(2)
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

    # === v0.2 stage application ===
    from skills.youtube_transcribe.pipeline_v02 import apply_v02_stages
    from skills.youtube_transcribe.presets.loader import (
        list_preset_names,
        resolve_with_env_checks,
    )

    cli_overrides: dict = {}
    if opts.get("vision_backend_opt") is not None:
        cli_overrides["vision_backend"] = opts["vision_backend_opt"]
    if opts.get("with_visuals"):
        cli_overrides["vision_backend"] = "gemini"
    if opts.get("detect_method_opt") is not None:
        cli_overrides["detect_method"] = opts["detect_method_opt"]
    if opts.get("frames_per_window_opt") is not None:
        cli_overrides["frames_per_window"] = opts["frames_per_window_opt"]
    if opts.get("max_windows_opt") is not None:
        cli_overrides["max_windows_per_video"] = opts["max_windows_opt"]
    if opts.get("ocr_opt") is True:
        cli_overrides["ocr"] = True
    if opts.get("check_quality") is True:
        cli_overrides["quality_check"] = True
    if opts.get("no_quality_check") is True:
        cli_overrides["quality_check"] = False
    if opts.get("correct_asr_opt") is True:
        cli_overrides["correct_asr"] = True
        # ASR correction requires quality check (it triggers off the
        # report's recommendation). Auto-enable so the flag works alone.
        cli_overrides.setdefault("quality_check", True)
    if opts.get("correct_asr_backend_opt"):
        cli_overrides["correct_asr_backend"] = opts["correct_asr_backend_opt"]
    if opts.get("diarize_opt") is True:
        cli_overrides["diarize"] = True
    if opts.get("translate_to_opt"):
        cli_overrides["translate_to"] = opts["translate_to_opt"]
    if opts.get("translate_backend_opt"):
        cli_overrides["translate_backend"] = opts["translate_backend_opt"]
    if opts.get("vision_prompt_path_opt"):
        cli_overrides["vision_prompt_path"] = opts["vision_prompt_path_opt"]

    preset_name = opts.get("preset") or "smart"
    if preset_name not in list_preset_names():
        console.print(f"[red]Unknown preset: {preset_name}[/red]. "
                      f"Known: {list_preset_names()}")
        sys.exit(2)

    config_path_opt = opts.get("config_path")
    cfg_v02, info_msgs = resolve_with_env_checks(
        preset_name,
        external_config_path=Path(config_path_opt) if config_path_opt else None,
        cli_overrides=cli_overrides,
    )
    for msg in info_msgs:
        console.print(msg, style="dim")

    # Map backend_name to source for quality check
    bn = (result.backend_name or "").lower()
    if "subtitles_manual" in bn:
        source = "youtube_manual"
    elif "subtitles" in bn:
        source = "youtube_auto"
    elif "whisper" in bn:
        source = "whisper"
    else:
        source = "external_asr"

    video_id = target.video_id or "unknown"
    triggers_path_opt = opts.get("triggers_path")

    # === Download mp4 if visual mode is active ===
    needs_video = (
        cfg_v02.get("vision_backend") == "gemini"
        and is_url(target.url)
    )

    if needs_video:
        import tempfile
        from skills.youtube_transcribe.utils.downloader import download_video
        with tempfile.TemporaryDirectory(prefix="yt-visual-") as visual_tmp:
            try:
                video_path = download_video(
                    target.url, Path(visual_tmp),
                    cookies_browser=cfg.cookies_browser,
                )
            except Exception as e:
                console.print(f"[yellow]⚠ Визуал отключён — не удалось скачать mp4:[/yellow] {e}",
                              style="dim")
                video_path = None
            result = apply_v02_stages(
                result=result,
                cfg=cfg_v02,
                video_path=video_path,
                video_id=video_id,
                out_dir=output_dir,
                source=source,
                triggers_path=Path(triggers_path_opt) if triggers_path_opt else None,
                no_default_triggers=bool(opts.get("no_default_triggers")),
            )
    else:
        # Local file path — use directly (already on disk).
        local_video_path = (
            Path(target.url).expanduser().resolve()
            if not is_url(target.url) and cfg_v02.get("vision_backend") == "gemini"
            else None
        )
        result = apply_v02_stages(
            result=result,
            cfg=cfg_v02,
            video_path=local_video_path,
            video_id=video_id,
            out_dir=output_dir,
            source=source,
            triggers_path=Path(triggers_path_opt) if triggers_path_opt else None,
            no_default_triggers=bool(opts.get("no_default_triggers")),
        )

    base_name = sanitize_filename(_derive_basename(target))
    txt_path = output_dir / f"{base_name}.txt"
    srt_path = output_dir / f"{base_name}.srt"
    json_path = output_dir / f"{base_name}.json"

    timestamps = cfg.timestamps if opts.get("timestamps") is None else opts["timestamps"]
    write_srt_flag = cfg.srt if opts.get("srt") is None else opts["srt"]

    formats: tuple[str, ...] = tuple(opts.get("output_format_opt") or ())
    # If no --output-format given, fall back to legacy txt+srt behavior.
    write_txt = (not formats) or ("all" in formats) or ("txt" in formats)
    write_srt_pick = (not formats and write_srt_flag) or ("all" in formats) or ("srt" in formats)
    write_json_pick = ("all" in formats) or ("json" in formats)

    if write_txt:
        if timestamps:
            write_txt_with_timestamps(result.segments, txt_path)
        else:
            write_txt_plain(result.segments, txt_path)
    if write_srt_pick:
        write_srt(result.segments, srt_path)
    if write_json_pick:
        from skills.youtube_transcribe.utils.output_writer import write_json
        write_json(
            result.segments, json_path,
            language=getattr(result, "language_detected", None),
            backend=getattr(result, "backend_name", None),
            duration_sec=getattr(result, "duration_seconds", None),
            quality=getattr(result, "quality", None),
            visual_segments=list(getattr(result, "visual_segments", []) or []),
        )

    # === v0.2: write .visual.md if visual stage produced any segments ===
    visual_path: Path | None = None
    visual_segments = list(getattr(result, "visual_segments", []) or [])
    if visual_segments or getattr(result, "quality", None) is not None:
        visual_path = output_dir / f"{base_name}.visual.md"
        write_visual_md(
            visual_segments,
            visual_path,
            title=target.title,
            url=target.url,
            quality=getattr(result, "quality", None),
        )

    console.print(f"[green]✓[/green] {result.backend_name} | "
                  f"язык={result.language_detected or 'auto'} | "
                  f"длительность={result.duration_seconds:.1f}s")
    if write_txt:
        console.print(f"  [bold]{txt_path}[/bold]")
    if write_srt_pick:
        console.print(f"  [bold]{srt_path}[/bold]")
    if write_json_pick:
        console.print(f"  [bold]{json_path}[/bold]")
    if visual_path is not None:
        console.print(f"  [bold]{visual_path}[/bold] "
                      f"({len(visual_segments)} visual moments)")


def _derive_basename(target: ResolvedTarget) -> str:
    """Pick a human-readable filename for a single transcript.

    Prefer the video title (sanitized) and append the video_id suffix to
    keep filenames unique across re-runs and same-titled videos. Falls back
    to `yt_<id>` / `url_transcript` / local stem when no title is available.
    """
    if target.title:
        # Title-based: "<sanitized-title>_<video_id-or-suffix>"
        if target.video_id:
            return f"{target.title}_{target.video_id}"
        return target.title
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
        # === v0.2 carry-through ===
        visual_segments=list(getattr(result, "visual_segments", []) or []),
        quality=getattr(result, "quality", None),
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
@click.option("--with-visuals", is_flag=True, help="Shortcut for --vision-backend=gemini.")
@click.option("--vision-backend", "vision_backend_opt",
              type=click.Choice(["off", "gemini"]), default=None,
              help="Visual mode backend. off = audio only.")
@click.option("--detect-method", "detect_method_opt",
              type=click.Choice(["keywords_only", "semantic", "hybrid", "llm_full_pass"]),
              default=None, help="How to find visual moments.")
@click.option("--frames-per-window", "frames_per_window_opt", type=int, default=None)
@click.option("--max-windows", "max_windows_opt", type=int, default=None)
@click.option("--ocr", "ocr_opt", is_flag=True, default=None,
              help="Run OCR on keyframes (--ocr opt-in).")
@click.option("--check-quality", is_flag=True, default=None,
              help="Force quality check + write to manifest.")
@click.option("--no-quality-check", is_flag=True, default=None,
              help="Skip quality check even in smart preset.")
@click.option("--preset", default=None,
              help="Preset name (eco/smart/standard/premium).")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="External config TOML.")
@click.option("--triggers", "triggers_path", type=click.Path(exists=True), default=None,
              help="External triggers TOML.")
@click.option("--no-default-triggers", is_flag=True, default=False,
              help="Disable built-in triggers.")
# === v0.3 channel filters ===
@click.option("--since", "since_opt", default=None,
              help="Filter videos uploaded on or after YYYY-MM-DD.")
@click.option("--until", "until_opt", default=None,
              help="Filter videos uploaded on or before YYYY-MM-DD.")
@click.option("--min-duration", "min_duration_opt", type=int, default=None,
              help="Minimum video duration in seconds.")
@click.option("--max-duration", "max_duration_opt", type=int, default=None,
              help="Maximum video duration in seconds.")
@click.option("--no-shorts", "no_shorts_opt", is_flag=True, default=False,
              help="Skip YouTube Shorts (videos <= 60s).")
@click.option("--skip-existing", "skip_existing_opt", is_flag=True, default=False,
              help="Skip videos already transcribed (any *_<video_id>.txt under output-dir).")
@click.option("--workers", "workers_opt", type=int, default=1, show_default=True,
              help="Parallel workers for batch (cloud backends only — whisper-local "
                   "and rate-limited APIs may not benefit).")
@click.option("--search", "search_opt", default=None,
              help="YouTube search query — fetch top --limit results via yt-dlp "
                   "(no API key needed).")
@click.option("--correct-asr", "correct_asr_opt", is_flag=True, default=None,
              help="Run LLM-based correction on low-quality transcripts (opt-in).")
@click.option("--correct-asr-backend", "correct_asr_backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]), default=None,
              help="LLM provider for ASR correction (default: gemini; "
                   "ollama=local llama via `ollama serve`).")
@click.option("--diarize", "diarize_opt", is_flag=True, default=None,
              help="Run speaker diarization via pyannote.audio "
                   "(needs HF_TOKEN + `[diarization]` extra).")
@click.option("--translate-to", "translate_to_opt", default=None,
              help="Translate transcript to language (ISO code or name).")
@click.option("--translate-backend", "translate_backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]), default=None,
              help="LLM provider for translation (default: gemini).")
@click.option("--output-format", "output_format_opt",
              type=click.Choice(["all", "txt", "srt", "json"]),
              default=None, multiple=True,
              help="Output format(s). Repeat for multiple. Default: txt+srt.")
@click.option("--vision-prompt", "vision_prompt_path_opt",
              type=click.Path(exists=True), default=None,
              help="Custom vision prompt template (placeholders {language}, "
                   "{transcript_snippet}, {start_sec}, {end_sec}).")
def batch_cmd(
    inputs: tuple[str, ...],
    from_file: Path | None,
    limit: int,
    batch_name: str | None,
    no_combined: bool,
    fail_fast: bool,
    **opts,
) -> None:
    """Batch-транскрибация: пачка URL, канал/плейлист, или --from-file."""
    if not CONFIG_PATH.exists():
        run_wizard()

    cfg = load_config(CONFIG_PATH)
    cfg = _override_config(cfg, opts)
    if opts.get("no_fast_path"):
        cfg.fast_path_enabled = False

    # === v0.2 preset / config / overrides resolution (once per batch) ===
    from skills.youtube_transcribe.pipeline_v02 import apply_v02_stages
    from skills.youtube_transcribe.presets.loader import (
        list_preset_names,
        resolve_with_env_checks,
    )

    cli_overrides: dict = {}
    if opts.get("vision_backend_opt") is not None:
        cli_overrides["vision_backend"] = opts["vision_backend_opt"]
    if opts.get("with_visuals"):
        cli_overrides["vision_backend"] = "gemini"
    if opts.get("detect_method_opt") is not None:
        cli_overrides["detect_method"] = opts["detect_method_opt"]
    if opts.get("frames_per_window_opt") is not None:
        cli_overrides["frames_per_window"] = opts["frames_per_window_opt"]
    if opts.get("max_windows_opt") is not None:
        cli_overrides["max_windows_per_video"] = opts["max_windows_opt"]
    if opts.get("ocr_opt") is True:
        cli_overrides["ocr"] = True
    if opts.get("check_quality") is True:
        cli_overrides["quality_check"] = True
    if opts.get("no_quality_check") is True:
        cli_overrides["quality_check"] = False
    if opts.get("correct_asr_opt") is True:
        cli_overrides["correct_asr"] = True
        cli_overrides.setdefault("quality_check", True)
    if opts.get("correct_asr_backend_opt"):
        cli_overrides["correct_asr_backend"] = opts["correct_asr_backend_opt"]
    if opts.get("diarize_opt") is True:
        cli_overrides["diarize"] = True
    if opts.get("translate_to_opt"):
        cli_overrides["translate_to"] = opts["translate_to_opt"]
    if opts.get("translate_backend_opt"):
        cli_overrides["translate_backend"] = opts["translate_backend_opt"]
    if opts.get("vision_prompt_path_opt"):
        cli_overrides["vision_prompt_path"] = opts["vision_prompt_path_opt"]

    preset_name = opts.get("preset") or "smart"
    if preset_name not in list_preset_names():
        console.print(f"[red]Unknown preset: {preset_name}[/red]. Known: {list_preset_names()}")
        sys.exit(2)

    config_path_opt = opts.get("config_path")
    cfg_v02, info_msgs = resolve_with_env_checks(
        preset_name,
        external_config_path=Path(config_path_opt) if config_path_opt else None,
        cli_overrides=cli_overrides,
    )
    for msg in info_msgs:
        console.print(msg, style="dim")

    # === v0.3 channel filters ===
    from datetime import date as _date_cls

    def _parse_date(s: str | None, flag_name: str):
        if s is None:
            return None
        try:
            return _date_cls.fromisoformat(s)
        except ValueError:
            console.print(
                f"[red]--{flag_name} expects YYYY-MM-DD format, got '{s}'[/red]"
            )
            sys.exit(2)

    filters = ResolverFilters(
        limit=limit,
        since=_parse_date(opts.get("since_opt"), "since"),
        until=_parse_date(opts.get("until_opt"), "until"),
        min_duration_sec=opts.get("min_duration_opt"),
        max_duration_sec=opts.get("max_duration_opt"),
        include_shorts=not opts.get("no_shorts_opt", False),
        search_query=opts.get("search_opt"),
    )
    targets, resolve_failures = resolve(list(inputs), from_file, filters)

    # Convert resolve failures into BatchFailure entries (stage="resolve")
    initial_failures: list[BatchFailure] = []
    for rf in resolve_failures:
        initial_failures.append(BatchFailure(
            index=len(initial_failures) + 1,
            url=rf.url,
            stage="resolve",
            error_text=rf.error,
            hint=_diagnose_failure_hint("resolve", rf.error),
        ))

    if not targets and not initial_failures:
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
    failures: list[BatchFailure] = list(initial_failures)
    target_index_offset = len(initial_failures)

    # === v0.3 --skip-existing: build set of already-transcribed video_ids ===
    skip_existing = bool(opts.get("skip_existing_opt"))
    existing_ids: set[str] = set()
    if skip_existing and output_root.exists():
        for txt in output_root.rglob("*.txt"):
            stem = txt.stem
            # Filename pattern: <prefix>_<slug>_<video_id>.txt or <slug>_<video_id>.txt
            if "_" in stem:
                candidate = stem.rsplit("_", 1)[-1]
                if candidate and len(candidate) >= 8:  # YouTube ids are 11 chars
                    existing_ids.add(candidate)

    workers = max(1, int(opts.get("workers_opt") or 1))
    if workers > 1 and fail_fast:
        console.print(
            "[red]--workers > 1 is incompatible with --fail-fast[/red]: "
            "in-flight tasks can't be reliably cancelled. Use one or the other."
        )
        sys.exit(2)

    skipped_count = 0
    started = datetime.now()

    # Per-video processor — pure function (no shared mutable state besides
    # console which is thread-safe in Rich). Returns one of:
    #   ("ok", BatchVideoStatus) — transcribed and written
    #   ("failed", BatchFailure) — pipeline raised; collect for errors.log
    def _process_one(i: int, target: ResolvedTarget):
        try:
            result = run_pipeline(
                target, cfg,
                backend_override=opts.get("backend"),
                keep_audio_to=(batch_dir / "audio") if cfg.keep_audio else None,
            )
        except BackendNotConfigured as e:
            return ("failed", BatchFailure(
                index=i, url=target.url, stage="backend",
                error_text=str(e),
                hint=_diagnose_failure_hint("backend", str(e)),
            ))
        except BackendError as e:
            stage = (
                "download"
                if "yt-dlp" in str(e).lower() or "403" in str(e)
                else "backend"
            )
            return ("failed", BatchFailure(
                index=i, url=target.url, stage=stage,
                error_text=str(e),
                hint=_diagnose_failure_hint(stage, str(e)),
            ))

        # === v0.2 stages ===
        bn = (getattr(result, "backend_name", None) or "").lower()
        if "subtitles_manual" in bn:
            v02_source = "youtube_manual"
        elif "subtitles" in bn:
            v02_source = "youtube_auto"
        elif "whisper" in bn:
            v02_source = "whisper"
        else:
            v02_source = "external_asr"

        v02_video_id = target.video_id or f"video-{i}"
        triggers_path_opt = opts.get("triggers_path")
        no_default_triggers_opt = bool(opts.get("no_default_triggers"))

        needs_video = (
            cfg_v02.get("vision_backend") == "gemini"
            and is_url(target.url)
        )
        if needs_video:
            import tempfile
            from skills.youtube_transcribe.utils.downloader import download_video
            with tempfile.TemporaryDirectory(prefix=f"yt-visual-{i}-") as v_tmp:
                try:
                    v_path = download_video(
                        target.url, Path(v_tmp),
                        cookies_browser=cfg.cookies_browser,
                    )
                except Exception as e:
                    console.print(
                        f"[yellow]⚠ Видео {i}: визуал отключён — {e}[/yellow]",
                        style="dim",
                    )
                    v_path = None
                result = apply_v02_stages(
                    result=result,
                    cfg=cfg_v02,
                    video_path=v_path,
                    video_id=v02_video_id,
                    out_dir=batch_dir,
                    source=v02_source,
                    triggers_path=Path(triggers_path_opt) if triggers_path_opt else None,
                    no_default_triggers=no_default_triggers_opt,
                )
        else:
            local_video_path = (
                Path(target.url).expanduser().resolve()
                if not is_url(target.url) and cfg_v02.get("vision_backend") == "gemini"
                else None
            )
            result = apply_v02_stages(
                result=result,
                cfg=cfg_v02,
                video_path=local_video_path,
                video_id=v02_video_id,
                out_dir=batch_dir,
                source=v02_source,
                triggers_path=Path(triggers_path_opt) if triggers_path_opt else None,
                no_default_triggers=no_default_triggers_opt,
            )

        return ("ok", result)

    def _write_outputs_and_record(i: int, target: ResolvedTarget, result):
        """Write txt/srt for one transcribed target and append BatchVideoStatus."""
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

    # Filter out skip-existing targets first (so workers don't waste time on them).
    pending: list[tuple[int, ResolvedTarget]] = []
    for i, target in enumerate(targets, start=1 + target_index_offset):
        if skip_existing and target.video_id and target.video_id in existing_ids:
            skipped_count += 1
            console.print(
                f"  [dim]· skip #{i} {target.title or target.video_id} "
                f"(already transcribed)[/dim]",
            )
            continue
        pending.append((i, target))

    from rich.progress import (
        Progress, SpinnerColumn, BarColumn, TextColumn,
        TimeElapsedColumn, TaskProgressColumn,
    )
    use_progress = not opts.get("verbose") and len(pending) > 1
    progress_cm = (
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("· ok={task.fields[ok]} fail={task.fields[fail]}"),
            TimeElapsedColumn(),
            console=console, transient=False,
        )
        if use_progress
        else None
    )

    if workers == 1:
        # Serial path (default; preserves fail-fast).
        if progress_cm is None:
            for i, target in pending:
                kind, payload = _process_one(i, target)
                if kind == "failed":
                    failures.append(payload)
                    if fail_fast:
                        console.print(f"[red]Ошибка #{i}: {payload.error_text}[/red]")
                        sys.exit(4)
                else:
                    _write_outputs_and_record(i, target, payload)
        else:
            with progress_cm as progress:
                task = progress.add_task(
                    "Transcribing", total=len(pending), ok=0, fail=0,
                )
                for i, target in pending:
                    progress.update(
                        task,
                        description=f"#{i} {(target.title or 'video')[:40]}",
                    )
                    kind, payload = _process_one(i, target)
                    if kind == "failed":
                        failures.append(payload)
                        progress.update(task, advance=1, fail=len(failures))
                        if fail_fast:
                            console.print(f"[red]Ошибка #{i}: {payload.error_text}[/red]")
                            sys.exit(4)
                    else:
                        _write_outputs_and_record(i, target, payload)
                        progress.update(task, advance=1, ok=len(statuses))
    else:
        # Parallel path. fail_fast already validated incompatible above.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        console.print(
            f"[dim]Running with {workers} parallel workers — fail-fast disabled.[/dim]"
        )
        progress_obj = progress_cm.__enter__() if progress_cm else None
        task_id = (
            progress_obj.add_task(
                "Transcribing", total=len(pending), ok=0, fail=0,
            )
            if progress_obj is not None
            else None
        )
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_target = {
                pool.submit(_process_one, i, target): (i, target)
                for i, target in pending
            }
            for fut in as_completed(future_to_target):
                i, target = future_to_target[fut]
                try:
                    kind, payload = fut.result()
                except Exception as e:  # pragma: no cover — unexpected
                    failures.append(BatchFailure(
                        index=i, url=target.url, stage="backend",
                        error_text=f"unexpected: {e}", hint=None,
                    ))
                    if progress_obj is not None:
                        progress_obj.update(task_id, advance=1, fail=len(failures))
                    continue
                if kind == "failed":
                    failures.append(payload)
                    if progress_obj is not None:
                        progress_obj.update(task_id, advance=1, fail=len(failures))
                else:
                    _write_outputs_and_record(i, target, payload)
                    if progress_obj is not None:
                        progress_obj.update(task_id, advance=1, ok=len(statuses))
        if progress_cm is not None:
            progress_cm.__exit__(None, None, None)

    meta = BatchMeta(
        batch_name=name,
        created_at=started,
        source_type=_infer_source_type(targets, from_file),
        source_url=(
            targets[0].url if targets and all(t.source == "channel" for t in targets) else None
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
    skip_str = f"   [dim]· {skipped_count} skipped[/dim]" if skipped_count else ""
    console.print(
        f"\n[green]✓[/green] {len(statuses)} ok   "
        f"[red]✗[/red] {len(failures)} failed{skip_str}   "
        f"Total: {len(statuses) + len(failures) + skipped_count}   "
        f"Elapsed: {elapsed:.0f}s"
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


# ---------------------------------------------------------------------------
# Task 21 — config sub-group
# ---------------------------------------------------------------------------

@cli.group()
def config() -> None:
    """Manage configuration and API keys."""


@config.command("show")
def config_show() -> None:
    """Print current config and API-key status."""
    cfg = load_config(CONFIG_PATH)
    console.print(f"[bold]Config file:[/bold] {CONFIG_PATH}")
    console.print("\n[bold]Settings:[/bold]")
    for field_name, value in cfg.__dict__.items():
        console.print(f"  {field_name} = {value}")
    console.print("\n[bold]API keys:[/bold]")
    for backend in ["gemini", "groq", "openai", "deepgram", "assemblyai", "custom"]:
        k = get_api_key(backend)
        status = mask_key(k) if k else "[dim]not set[/dim]"
        console.print(f"  {backend}: {status}")


# Map kebab-case config keys to Config dataclass field names.
_SET_KEY_TO_FIELD: dict[str, str] = {
    "backend": "default_backend",
    "fallback": "fallback_backend",
    "whisper-model": "whisper_model",
    "gemini-model": "gemini_model",
    "groq-model": "groq_model",
    "openai-model": "openai_model",
    "deepgram-model": "deepgram_model",
    "assemblyai-model": "assemblyai_model",
    "language": "language",
    "output-dir": "output_dir",
    "cookies-browser": "cookies_browser",
    "custom.base_url": "custom_base_url",
    "custom.model": "custom_model",
}

# Keys whose values must be validated against BACKEND_CHOICES.
_BACKEND_FIELD_NAMES = {"default_backend", "fallback_backend"}


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a config field.  KEY is kebab-case (e.g. backend, whisper-model)."""
    field = _SET_KEY_TO_FIELD.get(key)
    if not field:
        console.print(f"[red]Unknown key:[/red] {key!r}")
        console.print(f"Known keys: {', '.join(_SET_KEY_TO_FIELD)}")
        sys.exit(2)
    # Validate backend-type values.
    if field in _BACKEND_FIELD_NAMES and value not in BACKEND_CHOICES:
        console.print(f"[red]Invalid value for {key!r}:[/red] {value!r}")
        console.print(f"Allowed: {', '.join(BACKEND_CHOICES)}")
        sys.exit(2)
    cfg = load_config(CONFIG_PATH)
    setattr(cfg, field, value)
    save_config(cfg, CONFIG_PATH)
    console.print(f"[green]✓[/green] {key} = {value}")


@config.command("set-key")
@click.argument("backend", type=click.Choice(
    ["gemini", "groq", "openai", "deepgram", "assemblyai", "custom"]
))
def config_set_key(backend: str) -> None:
    """Interactively set an API key for BACKEND (stored in .env, never in config)."""
    key = click.prompt(f"{backend.upper()}_API_KEY", hide_input=True, default="")
    if not key:
        console.print("[yellow]No key entered — nothing saved.[/yellow]")
        return
    set_api_key(backend, key, env_path=ENV_PATH)
    console.print(f"[green]✓[/green] {backend} key saved to {ENV_PATH} ({mask_key(key)})")


@config.command("test")
@click.argument("backend", type=click.Choice(BACKEND_CHOICES))
def config_test(backend: str) -> None:
    """Run a quick configuration sanity-check for BACKEND (no real audio)."""
    cfg = load_config(CONFIG_PATH)
    try:
        b = build_backend(backend, cfg)
    except Exception as e:
        console.print(f"[red]✗[/red] build_backend failed: {e}")
        sys.exit(2)
    ok, reason = b.is_configured()
    if ok:
        console.print(f"[green]✓[/green] {backend} is configured")
    else:
        console.print(f"[red]✗[/red] {backend}: {reason}")
        sys.exit(3)


@config.command("wizard")
def config_wizard() -> None:
    """Re-run the first-run setup wizard."""
    run_wizard()


from skills.youtube_transcribe.detection.triggers_cli import triggers_cli
cli.add_command(triggers_cli)


@cli.command(name="webui")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Bind host (use 0.0.0.0 to expose; default loopback only).")
@click.option("--port", type=int, default=7860, show_default=True)
@click.option("--share", is_flag=True, default=False,
              help="Create a Gradio share-link (public tunnel — be careful).")
def webui_cmd(host: str, port: int, share: bool) -> None:
    """Launch the Gradio Web UI (v0.4 — opt-in via [webui] extra)."""
    try:
        from skills.youtube_transcribe.webui.app import launch
    except ImportError as e:
        console.print(
            "[red]Web UI requires the `webui` extra:[/red]\n"
            "  uv sync --extra webui\n"
            "(or `pip install youtube-transcribe[webui]`)"
        )
        console.print(f"  Detail: {e}", style="dim")
        sys.exit(2)
    launch(server_name=host, server_port=port, share=share)


@cli.command(name="summarize")
@click.argument("transcript_path", type=click.Path(exists=True, path_type=Path))
@click.option("--backend", "backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]),
              default="gemini", show_default=True,
              help="LLM provider for summarization.")
@click.option("--language", "language_opt", default=None,
              help="Target language for the summary (default: same as transcript).")
@click.option("--output", "output_opt", type=click.Path(path_type=Path),
              default=None,
              help="Where to write the summary. Default: <transcript>.summary.md "
                   "next to the source.")
@click.option("--ollama-model", "ollama_model_opt", default=None,
              help="Ollama model tag (default: from config / llama3.2:3b).")
@click.option("--ollama-host", "ollama_host_opt", default=None,
              help="Ollama HTTP host (default: http://localhost:11434).")
def summarize_cmd(
    transcript_path: Path,
    backend_opt: str,
    language_opt: str | None,
    output_opt: Path | None,
    ollama_model_opt: str | None,
    ollama_host_opt: str | None,
) -> None:
    """Summarize an existing transcript (.txt / .json / .srt) via LLM.

    Single call to gemini / claude / openai / ollama. Writes a Markdown
    file with TL;DR + key points + notable quotes (with timestamps where
    available).
    """
    from skills.youtube_transcribe.quality.summarizer import summarize_transcript
    from skills.youtube_transcribe.utils.transcript_loader import (
        load_transcript_segments,
    )

    try:
        segments, detected_lang = load_transcript_segments(transcript_path)
    except Exception as e:
        console.print(f"[red]Не удалось прочитать транскрипт:[/red] {e}")
        sys.exit(2)
    if not segments:
        console.print("[yellow]Транскрипт пустой — нечего суммаризировать.[/yellow]")
        sys.exit(0)

    if backend_opt == "ollama":
        api_key = None
    else:
        key_lookup = {
            "gemini": "gemini",
            "claude": "anthropic",
            "openai": "openai",
        }[backend_opt]
        api_key = get_api_key(key_lookup)
        if not api_key:
            console.print(
                f"[red]Нет ключа для backend={backend_opt}[/red]. "
                f"Установи через `youtube-transcribe config set-key {key_lookup}` "
                f"или используй --backend ollama (локально)."
            )
            sys.exit(3)

    language = language_opt or detected_lang or "en"

    summary_md = summarize_transcript(
        segments,
        language=language,
        api_key=api_key,
        backend=backend_opt,
        ollama_model=ollama_model_opt or "llama3.2:3b",
        ollama_host=ollama_host_opt or "http://localhost:11434",
    )
    if not summary_md:
        console.print(
            f"[red]LLM не вернул ответ.[/red] Возможно, нет сети, истекла "
            f"квота, или `ollama serve` не запущен."
        )
        sys.exit(4)

    out_path = (
        output_opt
        if output_opt is not None
        else transcript_path.with_suffix(transcript_path.suffix + ".summary.md")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(summary_md, encoding="utf-8")

    console.print(f"[green]✓[/green] summary via {backend_opt}")
    console.print(f"  [bold]{out_path}[/bold]")


@cli.command(name="analyze")
@click.argument("source", required=False,
                type=click.Path(path_type=Path))
@click.option("--prompt", "prompt_inline", default=None,
              help="User query passed verbatim to the LLM.")
@click.option("--prompt-file", "prompt_file", default=None,
              type=click.Path(exists=True, path_type=Path),
              help="Read prompt text from this file (.md/.txt).")
@click.option("--backend", "backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]),
              default="gemini", show_default=True,
              help="LLM provider.")
@click.option("--latest", is_flag=True, default=False,
              help="Use the most recently modified batch under output-dir.")
@click.option("--all", "all_opt", is_flag=True, default=False,
              help="Analyze every video in the batch — skip the picker.")
@click.option("--select", "select_opt", default=None,
              help='1-based selection like "1,3,5-7" — skips the picker.')
@click.option("--append-to", "append_to", default=None,
              type=click.Path(path_type=Path),
              help="Append the block to this markdown file instead of "
                   "creating a new one.")
@click.option("--output", "output_opt", default=None,
              type=click.Path(path_type=Path),
              help="Override output file path.")
@click.option("--ollama-model", "ollama_model_opt", default=None,
              help="Ollama model tag (default: llama3.2:3b).")
@click.option("--ollama-host", "ollama_host_opt", default=None,
              help="Ollama HTTP host (default: http://localhost:11434).")
@click.option("--no-stdout", "no_stdout", is_flag=True, default=False,
              help="Don't print the LLM response to stdout (file only).")
@click.option("--max-chars", "max_chars", type=int, default=60_000,
              show_default=True,
              help="Per-transcript soft truncation in characters.")
def analyze_cmd(
    source: Path | None,
    prompt_inline: str | None,
    prompt_file: Path | None,
    backend_opt: str,
    latest: bool,
    all_opt: bool,
    select_opt: str | None,
    append_to: Path | None,
    output_opt: Path | None,
    ollama_model_opt: str | None,
    ollama_host_opt: str | None,
    no_stdout: bool,
    max_chars: int,
) -> None:
    """Analyze one or more transcripts via an external LLM."""
    from datetime import datetime
    from skills.youtube_transcribe.analyze.source_resolver import (
        resolve_source,
    )
    from skills.youtube_transcribe.analyze.prompt_builder import build_prompt
    from skills.youtube_transcribe.analyze import runner as analyze_runner
    from skills.youtube_transcribe.analyze.output_writer import (
        analysis_filename, write_analysis, append_analysis,
    )

    # 1. Validate prompt args (exactly one required).
    if bool(prompt_inline) == bool(prompt_file):
        console.print(
            "[red]Нужен ровно один из[/red] --prompt / --prompt-file."
        )
        sys.exit(2)
    if prompt_inline is not None:
        user_prompt = prompt_inline
    else:
        user_prompt = prompt_file.read_text(encoding="utf-8")

    # 2. API-key check (ollama is local, no key).
    if backend_opt == "ollama":
        api_key: str | None = None
    else:
        key_lookup = {
            "gemini": "gemini", "claude": "anthropic", "openai": "openai",
        }[backend_opt]
        api_key = get_api_key(key_lookup)
        if not api_key:
            console.print(
                f"[red]Нет ключа для backend={backend_opt}[/red]. "
                f"Установи через `youtube-transcribe config set-key {key_lookup}` "
                f"или используй --backend ollama (локально)."
            )
            sys.exit(4)

    # 3. Resolve SOURCE → list[VideoSource].
    cfg = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else None
    outputs_dir = Path(
        (cfg.output_dir if cfg else "./transcripts")
    ).expanduser()
    try:
        videos = resolve_source(source, outputs_dir=outputs_dir, latest=latest)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(3)
    if not videos:
        console.print("[red]Не найдено ни одного транскрипта в источнике.[/red]")
        sys.exit(3)

    total_videos = len(videos)
    # 4. Subset selection (--all / --select / picker — task 10 wires picker).
    if all_opt:
        chosen = videos
    elif select_opt:
        from skills.youtube_transcribe.analyze.select_parser import parse_select
        try:
            indices = parse_select(select_opt, total=total_videos)
        except ValueError as e:
            console.print(f"[red]--select: {e}[/red]")
            sys.exit(2)
        chosen = [videos[i] for i in indices]
    elif source is not None and source.is_file():
        # Single-file SOURCE: no picker, just use it.
        chosen = videos
    else:
        # Interactive picker — added in Task 10.
        console.print(
            "[red]Не указано --all / --select / --latest, а интерактив пока выключен.[/red]"
        )
        sys.exit(3)

    if not chosen:
        console.print("[red]Пустой выбор — нечего отправлять.[/red]")
        sys.exit(3)

    # 5. Build the full prompt.
    full_prompt = build_prompt(user_prompt, chosen, max_chars=max_chars)

    # 6. Call LLM.
    response = analyze_runner.run_analysis(
        full_prompt,
        backend=backend_opt,
        api_key=api_key,
        ollama_model=ollama_model_opt or "llama3.2:3b",
        ollama_host=ollama_host_opt or "http://localhost:11434",
    )
    if not response.strip():
        console.print(
            "[red]LLM не вернул ответ.[/red] Возможно, нет сети, "
            "истекла квота, или `ollama serve` не запущен."
        )
        sys.exit(4)

    # 7. Write file (append vs new).
    now = datetime.now()
    backend_label = backend_opt
    if append_to is not None:
        target = append_analysis(
            target=append_to,
            body=response,
            user_prompt=user_prompt,
            backend_label=backend_label,
            videos=chosen,
            total_videos=total_videos,
            now=now,
        )
    else:
        if output_opt is not None:
            out_path = output_opt
        elif source is not None and source.is_file():
            out_path = source.with_name(
                f"{source.stem}.{analysis_filename(now)}"
            )
        else:
            base_dir = source if source is not None else videos[0].transcript_path.parent
            out_path = base_dir / analysis_filename(now)
        target = write_analysis(
            out_path=out_path,
            body=response,
            user_prompt=user_prompt,
            backend_label=backend_label,
            videos=chosen,
            total_videos=total_videos,
            now=now,
        )

    # 8. stdout dump (unless --no-stdout).
    if not no_stdout:
        click.echo(response)
    console.print(f"[green]✓[/green] analysis via {backend_opt}")
    console.print(f"  [bold]{target}[/bold]")


__all__ = [
    "cli", "transcribe_cmd", "batch_cmd", "config",
    "webui_cmd", "summarize_cmd", "analyze_cmd",
]


if __name__ == "__main__":
    cli()
