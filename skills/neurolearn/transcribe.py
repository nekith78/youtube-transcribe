"""CLI root + `transcribe` sub-command. Bare-URL form routes to `transcribe`.
The `batch` sub-command is added in Task 20B (registered into the same `cli` group)."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console

from skills.neurolearn import __version__
from skills.neurolearn.backends.base import BackendError, BackendNotConfigured
from skills.neurolearn.backends.factory import build_backend
from skills.neurolearn.config import (
    CONFIG_PATH,
    ENV_PATH,
    Config,
    get_api_key,
    load_config,
    mask_key,
    save_config,
    set_api_key,
)
from skills.neurolearn.pipeline import run_pipeline
from skills.neurolearn.utils.downloader import (
    DownloadError,
    extract_youtube_video_id,
    is_url,
    is_youtube_url,
)
from skills.neurolearn.utils.output_writer import (
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
from skills.neurolearn.utils.resolver import (
    ResolvedTarget,
    ResolveFailure,
    ResolverFilters,
    resolve,
)
from skills.neurolearn.wizard import run_wizard

console = Console()


def _stdin_is_tty() -> bool:
    """Return True if stdin is an interactive terminal.

    Extracted as a standalone function so tests can patch it without
    fighting CliRunner's stdin replacement.
    """
    return sys.stdin.isatty()


BACKEND_CHOICES = [
    "smart", "subtitles", "whisper-local",
    "gemini", "groq", "openai", "deepgram", "assemblyai", "custom",
]


class _BareURLGroup(click.Group):
    """If the first positional looks like a URL or existing file path,
    inject the implicit `transcribe` sub-command in front of it.

    Required to keep base spec §8 UX (`neurolearn <URL>`)
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
@click.version_option(version=__version__, prog_name="neurolearn")
def cli() -> None:
    """neurolearn — transcribe YouTube and local media via 8 backends.

    Use `transcribe <URL_or_path>` for one input.
    Use `batch <inputs...>` for multiple URLs / a channel / a playlist.
    """
    pass


@cli.command(name="transcribe")
@click.argument("audio_or_url", required=False)
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
@click.option("--cookies-file", "cookies_file", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Netscape cookies.txt for sign-in-required videos. "
                   "Export via 'Get cookies.txt LOCALLY' extension (any browser). "
                   "We deliberately do NOT support --cookies-from-browser.")
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
              help="External config TOML (alternative to ~/.neurolearn/config.toml).")
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
@click.option("--video-type", "video_type_opt",
              default=None,
              help="Force a specific video type for vision analysis: "
                   "tutorial | lecture | code | demo | interview | vlog | "
                   "review | talking_head | generic. Default: auto-detect "
                   "from transcript.")
@click.option("--no-global-prefix", "no_global_prefix_opt",
              is_flag=True, default=False,
              help="With --vision-prompt: do NOT prepend the built-in "
                   "global prefix. Use only the user-supplied template.")
def transcribe_cmd(audio_or_url: str | None, **opts) -> None:
    """Transcribe a YouTube URL, supported video URL, or local audio/video file."""
    if not audio_or_url:
        from skills.neurolearn.shared.prompts import prompt_url_or_die
        audio_or_url = prompt_url_or_die("Paste URL or file path:")
    if not CONFIG_PATH.exists():
        run_wizard()

    cfg = load_config(CONFIG_PATH)
    cfg = _override_config(cfg, opts)
    if opts.get("no_fast_path"):
        cfg.fast_path_enabled = False

    targets, failures = resolve([audio_or_url], None, ResolverFilters())
    if failures:
        f = failures[0]
        console.print(f"[red]Failed to resolve URL:[/red] {f.url}\n  {f.error}")
        sys.exit(2)
    if len(targets) != 1:
        # Bare URL/file should always resolve to exactly one target.
        # If user passed a channel here, they should use `batch` instead.
        console.print("[red]This URL expanded to multiple videos.[/red] "
                      "For channels/playlists use: neurolearn batch <URL> --limit N")
        sys.exit(2)
    target = targets[0]

    output_dir = Path(opts.get("output_dir") or cfg.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    from skills.neurolearn.shared.progress import stage_progress
    try:
        with stage_progress(
            console,
            verbose=bool(opts.get("verbose")),
            initial="Preparing...",
        ) as stage:
            result = run_pipeline(
                target, cfg,
                backend_override=opts.get("backend"),
                on_stage=stage.update,
            )
    except BackendNotConfigured as e:
        console.print(f"[red]Backend not configured:[/red] {e}")
        sys.exit(3)
    except BackendError as e:
        console.print(f"[red]Transcription error:[/red] {e}")
        sys.exit(4)

    # === v0.2 stage application ===
    from skills.neurolearn.pipeline_v02 import apply_v02_stages
    from skills.neurolearn.presets.loader import (
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

    # Default preset = smart, OR the user's explicit --preset flag.
    user_passed_preset = opts.get("preset") is not None
    preset_name = opts.get("preset") or "smart"
    if preset_name not in list_preset_names():
        console.print(f"[red]Unknown preset: {preset_name}[/red]. "
                      f"Known: {list_preset_names()}")
        sys.exit(2)

    # Tutorial auto-detect: when running smart preset without explicit
    # user override, check the transcript for tutorial-action density. If
    # the video looks like a UI tutorial, promote to the tutorial preset
    # so frame extraction uses asymmetric offsets + Claude fallback fires.
    # Disabled if the user passed --preset explicitly (respect their choice).
    if not user_passed_preset and preset_name == "smart":
        from skills.neurolearn.detection.tutorial_detect import detect_tutorial
        signals = detect_tutorial(result.segments)
        if signals.is_tutorial:
            preset_name = "tutorial"
            console.print(
                f"[dim]· Auto-detected tutorial "
                f"({signals.action_count} action mentions, "
                f"{signals.density_per_min}/min) — using tutorial preset[/dim]"
            )

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

    with stage_progress(
        console,
        verbose=bool(opts.get("verbose")),
        initial="Post-processing...",
    ) as post_stage:
        if needs_video:
            import tempfile
            from skills.neurolearn.utils.downloader import download_video
            with tempfile.TemporaryDirectory(prefix="yt-visual-") as visual_tmp:
                post_stage.update("Downloading video for visual analysis...")
                try:
                    video_path = download_video(
                        target.url, Path(visual_tmp),
                        cookies_file=cfg.cookies_file,
                    )
                except Exception as e:
                    console.print(f"[yellow]⚠ Visual mode disabled — mp4 download failed:[/yellow] {e}",
                                  style="dim")
                    video_path = None
                post_stage.update("Analyzing visuals...")
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
            post_stage.update("Running quality / detection passes...")
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
        from skills.neurolearn.utils.output_writer import write_json
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
                  f"language={result.language_detected or 'auto'} | "
                  f"duration={result.duration_seconds:.1f}s")
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
    if opts.get("cookies_file") is not None: cfg.cookies_file = opts["cookies_file"]
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
        # === v0.7: multi-lang attribution from research/source ===
        source_language=getattr(target, "source_language", None),
        # === v0.10: forward the budget tracker into manifest.json ===
        budget=getattr(result, "budget", None),
    )


def _diagnose_failure_hint(stage: str, error_text: str) -> str | None:
    """Map common errors to actionable user hints."""
    s = error_text.lower()
    if stage == "download" and ("403" in s or "bot" in s or "sign in" in s):
        return "register a cookies.txt: neurolearn config set-cookies <path>"
    if stage == "backend" and "api_key" in s.replace(" ", ""):
        return "neurolearn config set-key <backend>"
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
# Task 13 (v0.6) — post-batch analyze hook
# ---------------------------------------------------------------------------

def _run_then_analyze(
    *,
    batch_folder: Path,
    prompt_inline: str | None,
    prompt_file: Path | None,
    backend: str,
) -> None:
    """Post-batch hook for `batch --then-analyze`.

    Resolves transcripts from `batch_folder/manifest.json`, builds a prompt
    from `prompt_inline` or `prompt_file`, calls the LLM, writes
    `analysis-*.md` inside `batch_folder`. In TTY mode an interactive
    picker is shown; in non-TTY all videos are used. No-op (with a warning)
    on missing transcripts or empty LLM response. Calls `sys.exit(4)` only
    on missing API key — other failures degrade gracefully so the batch
    itself stays reported as successful.
    """
    from datetime import datetime
    from skills.neurolearn.analyze.source_resolver import resolve_source
    from skills.neurolearn.analyze.prompt_builder import build_prompt
    from skills.neurolearn.analyze import runner as analyze_runner
    from skills.neurolearn.analyze.output_writer import (
        analysis_filename, write_analysis,
    )

    user_prompt = (
        prompt_inline if prompt_inline is not None
        else prompt_file.read_text(encoding="utf-8")
    )

    # Build fallback chain: user's choice first, then the remaining configured
    # backends (any with an API key — `ollama` is included by default since
    # it doesn't need a key, only a local server). When the primary backend
    # returns "" (quota / 429 / network), each next backend gets a turn.
    # See _select_analyze_backends for the exact ordering.
    backends_to_try = _select_analyze_backends(backend)
    if not backends_to_try:
        console.print(
            f"[red]--then-analyze: no API key for backend={backend}[/red]."
        )
        sys.exit(4)

    try:
        videos = resolve_source(
            batch_folder, outputs_dir=batch_folder.parent, latest=False,
        )
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        return
    if not videos:
        console.print(
            "[yellow]Batch contains no transcripts — analyze skipped.[/yellow]"
        )
        return

    if sys.stdin.isatty():
        from skills.neurolearn.analyze.picker import (
            pick_videos, PickerCancelled,
        )
        try:
            chosen = pick_videos(videos)
        except PickerCancelled:
            console.print("[yellow]analyze cancelled.[/yellow]")
            return
    else:
        chosen = videos
    if not chosen:
        console.print("[yellow]Empty selection — analyze skipped.[/yellow]")
        return

    full_prompt = build_prompt(user_prompt, chosen)
    response = ""
    used_backend = backends_to_try[0]
    for i, candidate in enumerate(backends_to_try):
        candidate_key = _api_key_for_backend(candidate)
        if i > 0:
            console.print(
                f"[yellow]{backends_to_try[i-1]} returned no response — "
                f"trying {candidate}[/yellow]"
            )
        response = analyze_runner.run_analysis(
            full_prompt, backend=candidate, api_key=candidate_key,
        )
        if response.strip():
            used_backend = candidate
            break

    if not response.strip():
        tried = ", ".join(backends_to_try)
        console.print(
            f"[red]LLM returned no response (then-analyze). "
            f"Tried: {tried}.[/red]"
        )
        return

    now = datetime.now()
    out_path = batch_folder / analysis_filename(now)
    target = write_analysis(
        out_path=out_path, body=response, user_prompt=user_prompt,
        backend_label=used_backend, videos=chosen, total_videos=len(videos),
        now=now,
    )
    click.echo(response)
    console.print(f"[green]✓[/green] then-analyze via {used_backend}")
    console.print(f"  [bold]{target}[/bold]")


def _select_analyze_backends(primary: str) -> list[str]:
    """Return ordered fallback chain for analyze.

    Primary backend first (the one the user requested). If the primary is
    misconfigured (no API key for a cloud backend), return [] so the caller
    exits with code 4 — user asked for that backend explicitly, don't
    silently substitute. Otherwise append every other backend that has a
    key or doesn't need one (ollama is local), in the standard preference
    order gemini → claude → openai → ollama.
    """
    if _api_key_for_backend(primary) is None and primary != "ollama":
        return []
    default_order = ["gemini", "claude", "openai", "ollama"]
    chain: list[str] = [primary]
    seen: set[str] = {primary}
    for b in default_order:
        if b in seen:
            continue
        if _api_key_for_backend(b) is None and b != "ollama":
            continue
        chain.append(b)
        seen.add(b)
    return chain


def _api_key_for_backend(backend: str) -> str | None:
    """None for missing keys, "" for ollama (no key needed)."""
    if backend == "ollama":
        return ""
    key_name = {
        "gemini": "gemini", "claude": "anthropic", "openai": "openai",
    }.get(backend)
    if not key_name:
        return None
    return get_api_key(key_name)


# ---------------------------------------------------------------------------
# Task 13 (v0.7) — core batch pipeline, extracted from batch_cmd
# ---------------------------------------------------------------------------

def _run_batch_pipeline(
    *,
    targets,           # list[ResolvedTarget] — already resolved
    cfg,               # Config from load_config()
    opts,              # dict — flat dict of all options (replaces opts.get(...))
) -> Path | None:
    """Core batch pipeline. Returns Path to batch folder or None.

    All v0.6 batch_cmd side-effects (combined.md, manifest.json,
    errors.log, videos/, final console summary) preserved byte-for-byte.
    """
    if not targets:
        return None

    from skills.neurolearn.pipeline_v02 import apply_v02_stages

    from_file = opts.get("from_file")
    batch_name = opts.get("batch_name")
    no_combined = bool(opts.get("no_combined", False))
    fail_fast = bool(opts.get("fail_fast", False))
    initial_failures: list[BatchFailure] = list(opts.get("initial_failures") or [])
    cfg_v02 = opts.get("cfg_v02") or {}

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
        except DownloadError as e:
            # yt-dlp / ffmpeg / network errors during the download stage.
            # Convert to BatchFailure so the batch keeps going through the
            # remaining videos. Common case: TikTok's anti-bot returning a
            # weird response on a specific video while the rest succeed.
            return ("failed", BatchFailure(
                index=i, url=target.url, stage="download",
                error_text=str(e),
                hint=_diagnose_failure_hint("download", str(e)),
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
            from skills.neurolearn.utils.downloader import download_video
            with tempfile.TemporaryDirectory(prefix=f"yt-visual-{i}-") as v_tmp:
                try:
                    v_path = download_video(
                        target.url, Path(v_tmp),
                        cookies_file=cfg.cookies_file,
                    )
                except Exception as e:
                    console.print(
                        f"[yellow]⚠ Video {i}: visual mode disabled — {e}[/yellow]",
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
                        console.print(f"[red]Error #{i}: {payload.error_text}[/red]")
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
                            console.print(f"[red]Error #{i}: {payload.error_text}[/red]")
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
        '"read combined.md and write a note on the topic"\n'
    )

    return batch_dir


# ---------------------------------------------------------------------------
# Task 20B — batch sub-command
# ---------------------------------------------------------------------------

@cli.command(name="batch")
@click.argument("inputs", nargs=-1)
@click.option("--from-file", "from_file", type=click.Path(path_type=Path),
              default=None, help="File with a list of URLs (1 per line, # — comment).")
@click.option("--limit", type=int, default=10, show_default=True,
              help="How many videos to take from a channel/playlist.")
@click.option("--batch-name", default=None,
              help="Batch directory name (default: batch_<ts>_<auto-slug>).")
@click.option("--no-combined", is_flag=True, help="Skip combined.md generation.")
@click.option("--fail-fast", is_flag=True,
              help="Stop on first failure (default: continue-on-error).")
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
@click.option("--cookies-file", "cookies_file", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Netscape cookies.txt for sign-in-required videos. "
                   "Export via 'Get cookies.txt LOCALLY' (any browser). "
                   "We deliberately do NOT support --cookies-from-browser.")
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
@click.option("--video-type", "video_type_opt",
              default=None,
              help="Force vision-prompt type: tutorial|lecture|code|demo|"
                   "interview|vlog|review|talking_head|generic. "
                   "Default: auto-detect from transcript.")
@click.option("--no-global-prefix", "no_global_prefix_opt",
              is_flag=True, default=False,
              help="With --vision-prompt: skip the built-in global prefix.")
@click.option("--then-analyze", "then_analyze", is_flag=True, default=False,
              help="After batch completes, run `analyze` on the produced folder.")
@click.option("--prompt", "analyze_prompt", default=None,
              help="Prompt for --then-analyze (verbatim).")
@click.option("--prompt-file", "analyze_prompt_file",
              type=click.Path(exists=True, path_type=Path), default=None,
              help="Read --then-analyze prompt from file.")
@click.option("--analyze-backend", "analyze_backend",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]),
              default=None,
              help="LLM backend for --then-analyze. "
                   "Default: ask once and remember in config.toml.")
def batch_cmd(
    inputs: tuple[str, ...],
    from_file: Path | None,
    limit: int,
    batch_name: str | None,
    no_combined: bool,
    fail_fast: bool,
    **opts,
) -> None:
    """Batch transcription: list of URLs, a channel/playlist, or --from-file."""
    # If no inputs were provided AND no alternative source (--from-file / --search),
    # prompt for URLs interactively. Lets users paste long URLs without baking them
    # into the shell command line.
    if not inputs and not from_file and not opts.get("search_opt"):
        from skills.neurolearn.shared.prompts import prompt_urls_or_die
        inputs = tuple(prompt_urls_or_die(
            "Paste URLs (one per line, empty line to finish):"
        ))

    # === v0.6: extract analyze-related options before anything else ===
    then_analyze = opts.pop("then_analyze", False)
    analyze_prompt = opts.pop("analyze_prompt", None)
    analyze_prompt_file = opts.pop("analyze_prompt_file", None)
    analyze_backend_cli = opts.pop("analyze_backend", None)

    if then_analyze and not (analyze_prompt or analyze_prompt_file):
        console.print(
            "[red]--then-analyze requires --prompt or --prompt-file.[/red]"
        )
        sys.exit(2)

    # Resolve the analyze backend now (single source of truth — flag >
    # config > onboarding prompt > silent skip on non-TTY). `None` here
    # means "don't analyze". `_run_then_analyze` will refuse to run if
    # then_analyze is on but resolved backend is None.
    from skills.neurolearn.analyze.backend_resolver import (
        resolve_analyze_backend,
    )
    analyze_backend = resolve_analyze_backend(
        cli_flag=analyze_backend_cli, no_analyze=not then_analyze,
    )

    if not CONFIG_PATH.exists():
        run_wizard()

    cfg = load_config(CONFIG_PATH)
    cfg = _override_config(cfg, opts)
    if opts.get("no_fast_path"):
        cfg.fast_path_enabled = False

    # === v0.2 preset / config / overrides resolution (once per batch) ===
    from skills.neurolearn.presets.loader import (
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
    if opts.get("video_type_opt"):
        cli_overrides["video_type"] = opts["video_type_opt"]
    if opts.get("no_global_prefix_opt"):
        cli_overrides["no_global_prefix"] = True

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
        console.print("[yellow]No videos to process from this input.[/yellow]")
        sys.exit(0)

    # Delegate the post-resolution pipeline (download → transcribe → write outputs
    # → final summary) to the reusable module-level function. v0.7 callers
    # (research, subscribes) drive the same function directly without Click.
    pipeline_opts = {
        **opts,
        "from_file": from_file,
        "batch_name": batch_name,
        "no_combined": no_combined,
        "fail_fast": fail_fast,
        "initial_failures": initial_failures,
        "cfg_v02": cfg_v02,
    }
    batch_dir = _run_batch_pipeline(targets=targets, cfg=cfg, opts=pipeline_opts)

    # === v0.6: post-batch analyze hook ===
    # analyze_backend is None when the user chose "skip" in onboarding or
    # we're non-TTY without a stored preference — pipe / Claude Code case.
    if (
        then_analyze
        and analyze_backend is not None
        and batch_dir is not None
        and batch_dir.exists()
    ):
        _run_then_analyze(
            batch_folder=batch_dir,
            prompt_inline=analyze_prompt,
            prompt_file=analyze_prompt_file,
            backend=analyze_backend,
        )
    elif then_analyze and analyze_backend is None and batch_dir is not None:
        console.print(
            "[dim]→ --then-analyze skipped: no backend selected "
            "(skip / non-TTY).[/dim]\n"
            f"[dim]  combined.md is ready: {batch_dir / 'combined.md'}[/dim]"
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
    "cookies-file": "cookies_file",
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


@config.command("set-cookies")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def config_set_cookies(path: str) -> None:
    """Register a Netscape cookies.txt for YouTube sign-in-required downloads.

    Use this when YouTube rejects anonymous requests for a video (age
    restriction, "sign in to confirm you're not a bot", members-only, etc.).
    Export your cookies via the "Get cookies.txt LOCALLY" extension and
    pass the file PATH here. The file is copied to
    `~/.neurolearn/youtube-cookies.txt` with mode 0600 and the path
    is saved in config.toml.

    For Instagram / TikTok cookies use `neurolearn subscribes cookies set <platform> <path>`.
    """
    from pathlib import Path as _P
    src = _P(path).expanduser().resolve()
    dest = ENV_PATH.parent / "youtube-cookies.txt"
    dest.write_bytes(src.read_bytes())
    if os.name != "nt":
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
    cfg = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else Config()
    cfg.cookies_file = str(dest)
    save_config(cfg, CONFIG_PATH)
    console.print(
        f"[green]✓[/green] cookies registered: [bold]{dest}[/bold] (mode 0600)\n"
        f"[dim]Override per-call with --cookies-file <other-path>. "
        f"If yt-dlp later says 'sign in required', re-export and run set-cookies again.[/dim]"
    )


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


from skills.neurolearn.detection.triggers_cli import triggers_cli
cli.add_command(triggers_cli)

# === v0.7: history command group ===
from skills.neurolearn.history.cli import history_group
cli.add_command(history_group)


@cli.command(name="webui", hidden=True)
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Bind host (use 0.0.0.0 to expose; default loopback only).")
@click.option("--port", type=int, default=7860, show_default=True)
@click.option("--share", is_flag=True, default=False,
              help="Create a Gradio share-link (public tunnel — be careful).")
def webui_cmd(host: str, port: int, share: bool) -> None:
    """[EXPERIMENTAL] Launch the Gradio Web UI.

    Hidden from --help while we focus on the CLI / Claude-skill surface.
    Code is preserved so we can return to it later, but it's not
    production-quality: tab wiring is incomplete and behavior on edge
    cases is unspecified. Prefer the CLI (`research`, `subscribes`,
    `transcribe`, `batch`, `analyze`) for real work.
    """
    console.print(
        "[yellow]⚠ WebUI is experimental and not actively maintained.[/yellow]\n"
        "[dim]Use the CLI commands instead. Press Ctrl+C to abort, "
        "or wait 3s to continue anyway.[/dim]"
    )
    import time
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        console.print("[dim]Aborted.[/dim]")
        sys.exit(0)

    _ensure_gradio_installed()
    from skills.neurolearn.webui.app import launch
    launch(server_name=host, server_port=port, share=share)


def _ensure_gradio_installed() -> None:
    """Verify `gradio` is importable; offer auto-install on missing/broken.

    Variant B (explicit prompt) — gradio pulls ~100 MB across ~30 transitive
    deps, so we never install silently. In a TTY we ask y/N; in a non-TTY
    (CI, piped) we print copy-pasteable instructions and exit.

    Catches both pure ImportError (package not installed) AND AttributeError
    (broken / partial install where `import gradio` succeeds but `gr.Blocks`
    fails — seen in the wild when an aborted install leaves an empty
    `gradio/` directory in site-packages).
    """
    try:
        from gradio import Blocks  # noqa: F401
        return
    except (ImportError, AttributeError):
        pass

    if not sys.stdin.isatty():
        console.print(
            "[red]Web UI requires gradio (~100 MB), not installed.[/red]\n"
            "Install and run again:\n\n"
            "  uv pip install 'gradio>=4'\n"
            "  # or: pip install 'neurolearn[webui]'"
        )
        sys.exit(4)

    console.print(
        "[yellow]Web UI requires gradio (~100 MB) — not installed yet.[/yellow]"
    )
    if not click.confirm("Install now?", default=False):
        console.print(
            "[red]Cancelled.[/red] Install manually:\n"
            "  uv pip install 'gradio>=4'"
        )
        sys.exit(4)

    import subprocess
    console.print("[dim]→ python -m pip install 'gradio>=4'[/dim]")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "gradio>=4"],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(
            f"[red]pip install failed (exit {e.returncode}).[/red]\n"
            "Try manually:\n"
            "  uv pip install 'gradio>=4'"
        )
        sys.exit(4)
    except FileNotFoundError:
        console.print(
            "[red]`python -m pip` not available in this environment.[/red]\n"
            "Install via uv:\n"
            "  uv pip install 'gradio>=4'"
        )
        sys.exit(4)

    try:
        from gradio import Blocks  # noqa: F401
    except (ImportError, AttributeError) as e:
        console.print(
            f"[red]gradio installed but cannot be imported: {e}[/red]"
        )
        sys.exit(4)
    console.print("[green]✓ gradio installed.[/green]")


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
    from skills.neurolearn.quality.summarizer import summarize_transcript
    from skills.neurolearn.utils.transcript_loader import (
        load_transcript_segments,
    )

    try:
        segments, detected_lang = load_transcript_segments(transcript_path)
    except Exception as e:
        console.print(f"[red]Failed to read transcript:[/red] {e}")
        sys.exit(2)
    if not segments:
        console.print("[yellow]Transcript is empty — nothing to summarize.[/yellow]")
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
                f"[red]No API key for backend={backend_opt}[/red]. "
                f"Set it via `neurolearn config set-key {key_lookup}` "
                f"or use --backend ollama (runs locally)."
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
            f"[red]LLM returned no response.[/red] Possible causes: no "
            f"network, quota exceeded, or `ollama serve` is not running."
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
    from skills.neurolearn.analyze.source_resolver import (
        resolve_source,
    )
    from skills.neurolearn.analyze.prompt_builder import build_prompt
    from skills.neurolearn.analyze import runner as analyze_runner
    from skills.neurolearn.analyze.output_writer import (
        analysis_filename, write_analysis, append_analysis,
    )

    # 1. Validate prompt args (exactly one required).
    if bool(prompt_inline) == bool(prompt_file):
        console.print(
            "[red]Pass exactly one of[/red] --prompt / --prompt-file."
        )
        sys.exit(2)
    if prompt_inline is not None:
        user_prompt = prompt_inline
    else:
        user_prompt = prompt_file.read_text(encoding="utf-8")

    # --latest / --all / --select are pairwise mutually exclusive.
    sel_flags = sum(1 for x in (latest, all_opt, bool(select_opt)) if x)
    if sel_flags > 1:
        console.print(
            "[red]--latest / --all / --select are mutually exclusive.[/red]"
        )
        sys.exit(2)

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
                f"[red]No API key for backend={backend_opt}[/red]. "
                f"Set it via `neurolearn config set-key {key_lookup}` "
                f"or use --backend ollama (runs locally)."
            )
            sys.exit(4)

    # 3. Resolve SOURCE → list[VideoSource].
    cfg = load_config(CONFIG_PATH)
    outputs_dir = Path(cfg.output_dir).expanduser()

    # If SOURCE is omitted and --latest is not set, offer batch picker in TTY.
    if source is None and not latest:
        if not _stdin_is_tty():
            console.print(
                "[red]SOURCE not specified and --latest not set, "
                "but stdin is not a TTY — picker unavailable.[/red]"
            )
            sys.exit(3)
        from skills.neurolearn.analyze.picker import (
            pick_batch, PickerCancelled,
        )
        try:
            source = pick_batch(outputs_dir)
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(3)
        except PickerCancelled:
            console.print("[yellow]Cancelled.[/yellow]")
            sys.exit(5)

    try:
        videos = resolve_source(source, outputs_dir=outputs_dir, latest=latest)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(3)
    if not videos:
        console.print("[red]No transcripts found in the source.[/red]")
        sys.exit(3)

    total_videos = len(videos)

    # 4. Subset selection: --all / --select / single-file / picker.
    if all_opt or latest:
        chosen = videos
    elif select_opt:
        from skills.neurolearn.analyze.select_parser import parse_select
        try:
            indices = parse_select(select_opt, total=total_videos)
        except ValueError as e:
            console.print(f"[red]--select: {e}[/red]")
            sys.exit(2)
        chosen = [videos[i] for i in indices]
    elif source is not None and source.is_file():
        chosen = videos
    else:
        if not _stdin_is_tty():
            console.print(
                "[red]Need one of --all / --select / --latest; "
                "stdin is not a TTY so the interactive picker can't run.[/red]"
            )
            sys.exit(3)
        from skills.neurolearn.analyze.picker import (
            pick_videos, PickerCancelled,
        )
        try:
            chosen = pick_videos(videos)
        except PickerCancelled:
            console.print("[yellow]Cancelled.[/yellow]")
            sys.exit(5)

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
            "[red]LLM returned no response.[/red] Possible causes: no "
            "network, quota exceeded, or `ollama serve` is not running."
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


# === v0.7: research command ===
@cli.command(name="research")
@click.argument("query", required=False)
@click.option("--prompt", "prompt_inline", default=None,
              help="Analyze prompt (required unless --no-analyze).")
@click.option("--prompt-file", "prompt_file", default=None,
              type=click.Path(exists=True, path_type=Path),
              help="Read analyze prompt from file. Mutex with --prompt.")
@click.option("--languages", "languages_csv", default="ru,en",
              show_default=True,
              help="Comma-separated language codes for search.")
@click.option("--query-lang", "query_lang_opt", default=None,
              help="Override script-based anchor detection. Tells the "
                   "translator which language in --languages your query is "
                   "written in (e.g. --query-lang sr for Serbian-latin).")
@click.option("--translate-backend", "translate_backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]),
              default=None,
              help="LLM for query translation. Defaults to --analyze-backend.")
@click.option("--days", "days_opt", type=int, default=None,
              help="Window: last N days (default 30; mutex with --since/--until).")
@click.option("--since", "since_opt", default=None,
              help="Window start YYYY-MM-DD.")
@click.option("--until", "until_opt", default=None,
              help="Window end YYYY-MM-DD.")
@click.option("--limit", "limit_opt", type=int, default=20, show_default=True,
              help="Videos to take from top YouTube results per language.")
@click.option("--match", "match_opt", default=None,
              help="Case-insensitive substring filter on title.")
@click.option("--filter", "filter_opt", default=None,
              help="LLM pre-screening prompt.")
@click.option("--filter-backend", "filter_backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]),
              default="gemini", show_default=True)
@click.option("--in-subscribes", is_flag=True, default=False,
              help="Source = subscribes channels (RSS) instead of YouTube search.")
@click.option("--group", "group_opt", default=None)
@click.option("--yes", is_flag=True, default=False,
              help="Skip TTY checkpoint.")
@click.option("--no-analyze", is_flag=True, default=False,
              help="Skip final analyze step (force-skip the LLM pass).")
@click.option("--analyze-backend", "analyze_backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]),
              default=None,
              help="LLM backend for analyze. Default: ask once and remember "
                   "in config.toml (non-TTY → skip silently).")
@click.option("--ollama-model", "ollama_model_opt", default=None)
@click.option("--ollama-host", "ollama_host_opt", default=None)
@click.option("--no-stdout", "no_stdout_opt", is_flag=True, default=False)
@click.option("--output-dir", "output_dir_opt", default=None)
@click.option("--batch-name", "batch_name_opt", default=None)
@click.option("--backend",
              type=click.Choice(BACKEND_CHOICES), default=None)
@click.option("--whisper-model",
              type=click.Choice(["turbo", "large", "medium", "small", "distil"]),
              default=None)
@click.option("--language", default=None)
@click.option("--no-shorts", "no_shorts_opt", is_flag=True, default=False)
@click.option("--min-duration", "min_duration_opt", type=int, default=None)
@click.option("--max-duration", "max_duration_opt", type=int, default=None)
@click.option("--workers", "workers_opt", type=int, default=1, show_default=True)
def research_cmd(
    query, prompt_inline, prompt_file, languages_csv, query_lang_opt,
    translate_backend_opt,
    days_opt, since_opt, until_opt, limit_opt, match_opt, filter_opt,
    filter_backend_opt, in_subscribes, group_opt, yes, no_analyze,
    analyze_backend_opt, ollama_model_opt, ollama_host_opt, no_stdout_opt,
    output_dir_opt, batch_name_opt, **batch_passthrough,
) -> None:
    """Research a topic — search YouTube + transcribe + analyze."""
    from datetime import date as _date
    from skills.neurolearn.research.pipeline import run_research

    if not query and not in_subscribes:
        from skills.neurolearn.shared.prompts import prompt_url_or_die
        query = prompt_url_or_die("Enter search query:")

    # Resolve analyze backend BEFORE prompt validation: if it ends up None
    # (user chose "skip" / non-TTY without preference), analyze won't run
    # and a prompt is no longer required.
    from skills.neurolearn.analyze.backend_resolver import (
        resolve_analyze_backend,
    )
    resolved_analyze_backend = resolve_analyze_backend(
        cli_flag=analyze_backend_opt, no_analyze=no_analyze,
    )
    effective_no_analyze = no_analyze or resolved_analyze_backend is None

    if not effective_no_analyze:
        if bool(prompt_inline) == bool(prompt_file):
            console.print(
                "[red]When analyze is on, pass exactly one of[/red] "
                "--prompt / --prompt-file."
            )
            sys.exit(2)

    if days_opt is not None and (since_opt or until_opt):
        console.print(
            "[red]--days and --since/--until are mutually exclusive.[/red]"
        )
        sys.exit(2)
    since_d = _date.fromisoformat(since_opt) if since_opt else None
    until_d = _date.fromisoformat(until_opt) if until_opt else None
    if since_d is None and until_d is None:
        days_arg = days_opt if days_opt is not None else 30
    else:
        days_arg = None

    languages = [s.strip() for s in languages_csv.split(",") if s.strip()]
    # Translation needs SOME backend with a key — fall back to gemini if
    # neither --translate-backend nor --analyze-backend is set. Only kicks
    # in when --languages has multiple values; single-language searches
    # never call the translator.
    translate_backend = (
        translate_backend_opt or analyze_backend_opt or "gemini"
    )

    api_keys = {
        "gemini": get_api_key("gemini"),
        "anthropic": get_api_key("anthropic"),
        "openai": get_api_key("openai"),
        "ollama": None,
    }

    cfg = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else None
    output_dir = output_dir_opt or (cfg.output_dir if cfg else "./transcripts")
    batch_name = batch_name_opt or _research_batch_name(query)
    batch_opts = {k: v for k, v in batch_passthrough.items() if v is not None}
    batch_opts.setdefault("no_combined", False)
    batch_opts.setdefault("fail_fast", False)

    try:
        run_research(
            query=query,
            queries_by_language=None,
            languages=languages,
            source_lang_hint=query_lang_opt,
            days=days_arg, since=since_d, until=until_d,
            limit=limit_opt,
            match=match_opt, filter_text=filter_opt,
            in_subscribes=in_subscribes, group=group_opt,
            yes=yes, no_analyze=effective_no_analyze,
            prompt=prompt_inline, prompt_file=prompt_file,
            analyze_backend=resolved_analyze_backend or "gemini",
            filter_backend=filter_backend_opt,
            translate_backend=translate_backend,
            ollama_model=ollama_model_opt or "llama3.2:3b",
            ollama_host=ollama_host_opt or "http://localhost:11434",
            no_stdout=no_stdout_opt,
            output_dir=output_dir,
            batch_name=batch_name,
            api_keys=api_keys,
            batch_opts=batch_opts,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(2)


def _research_batch_name(query: str | None) -> str:
    """Generate batch name: research_<ts>_<slug>."""
    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    if not query:
        return f"research_{ts}"
    slug = "".join(c if c.isalnum() else "-" for c in query.lower())
    slug = "-".join(p for p in slug.split("-") if p)[:30].rstrip("-")
    return f"research_{ts}_{slug or 'topic'}"


# === v0.7: subscribes command group ===
from skills.neurolearn.subscribes.cli import subscribes_group
cli.add_command(subscribes_group)


__all__ = [
    "cli", "transcribe_cmd", "batch_cmd", "config",
    "webui_cmd", "summarize_cmd", "analyze_cmd",
    "history_group", "research_cmd", "subscribes_group",
]


if __name__ == "__main__":
    cli()
