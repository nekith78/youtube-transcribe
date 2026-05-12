"""Gradio MVP for youtube-transcribe.

Wraps run_pipeline + apply_v02_stages with a web form. Launches locally
on 127.0.0.1 by default — no external network exposure unless user
explicitly passes server_name='0.0.0.0'.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any


def _run_one(
    url_or_path: str,
    preset_name: str,
    backend_override: str,
    with_visuals: bool,
    detect_method: str,
    max_windows: int,
    correct_asr: bool,
) -> tuple[str, str, str, str | None]:
    """Run pipeline once. Returns (transcript_txt, visual_md, quality_summary, base_dir).

    Errors are caught and reported via the transcript field.
    """
    from skills.youtube_transcribe.config import load_config
    from skills.youtube_transcribe.pipeline import run_pipeline
    from skills.youtube_transcribe.pipeline_v02 import apply_v02_stages
    from skills.youtube_transcribe.presets.loader import resolve_with_env_checks
    from skills.youtube_transcribe.utils.downloader import (
        download_video, is_url,
    )
    from skills.youtube_transcribe.utils.resolver import ResolverFilters, resolve
    from skills.youtube_transcribe.utils.output_writer import (
        write_srt, write_txt_with_timestamps, write_visual_md,
    )

    if not url_or_path.strip():
        return ("Введи URL или путь к файлу.", "", "", None)

    cli_overrides: dict[str, Any] = {}
    if backend_override and backend_override != "(default)":
        # transcribe_backend isn't currently honored by run_pipeline, but
        # passing it here makes intent visible in the resolved cfg_v02.
        cli_overrides["transcribe_backend"] = backend_override
    if with_visuals:
        cli_overrides["vision_backend"] = "gemini"
    if detect_method and detect_method != "(preset default)":
        cli_overrides["detect_method"] = detect_method
    if max_windows:
        cli_overrides["max_windows_per_video"] = int(max_windows)
    if correct_asr:
        cli_overrides["correct_asr"] = True
        cli_overrides["quality_check"] = True

    cfg_v02, info_msgs = resolve_with_env_checks(
        preset_name, cli_overrides=cli_overrides,
    )

    cfg = load_config()
    try:
        targets, failures = resolve([url_or_path], None, ResolverFilters())
    except Exception as e:
        return (f"[resolve error] {e}", "", "", None)

    if failures:
        return (f"[probe error] {failures[0].error}", "", "", None)
    if not targets:
        return ("Не удалось разобрать вход.", "", "", None)

    target = targets[0]

    try:
        result = run_pipeline(
            target, cfg,
            backend_override=(
                backend_override
                if backend_override and backend_override != "(default)"
                else None
            ),
        )
    except Exception as e:
        return (f"[pipeline error] {e}", "", "", None)

    # v0.2 stages
    out_dir = Path(tempfile.mkdtemp(prefix="yt-webui-"))
    bn = (getattr(result, "backend_name", None) or "").lower()
    source = (
        "youtube_manual" if "subtitles_manual" in bn
        else "youtube_auto" if "subtitles" in bn
        else "whisper" if "whisper" in bn
        else "external_asr"
    )

    video_id = target.video_id or "webui"

    if cfg_v02.get("vision_backend") in ("gemini", "claude", "openai") and is_url(target.url):
        try:
            with tempfile.TemporaryDirectory(prefix="yt-webui-mp4-") as v_tmp:
                v_path = download_video(target.url, Path(v_tmp))
                result = apply_v02_stages(
                    result=result, cfg=cfg_v02, video_path=v_path,
                    video_id=video_id, out_dir=out_dir, source=source,
                )
        except Exception as e:
            result = apply_v02_stages(
                result=result, cfg=cfg_v02, video_path=None,
                video_id=video_id, out_dir=out_dir, source=source,
            )
    else:
        local_video_path = (
            Path(target.url).expanduser().resolve()
            if not is_url(target.url) and cfg_v02.get("vision_backend") != "off"
            else None
        )
        result = apply_v02_stages(
            result=result, cfg=cfg_v02, video_path=local_video_path,
            video_id=video_id, out_dir=out_dir, source=source,
        )

    # Render outputs
    txt_path = out_dir / "transcript.txt"
    write_txt_with_timestamps(result.segments, txt_path)
    transcript = txt_path.read_text(encoding="utf-8")

    visual_md = ""
    if getattr(result, "visual_segments", None) or getattr(result, "quality", None):
        vmd_path = out_dir / "transcript.visual.md"
        write_visual_md(
            list(getattr(result, "visual_segments", []) or []),
            vmd_path,
            title=target.title,
            url=target.url,
            quality=getattr(result, "quality", None),
        )
        visual_md = vmd_path.read_text(encoding="utf-8")

    quality_summary = ""
    q = getattr(result, "quality", None)
    if q is not None:
        quality_summary = (
            f"Quality score: **{q.score:.2f}** · recommendation: `{q.recommendation}`\n\n"
            f"Breakdown: {q.breakdown}\n\nFlags: {q.flags}"
        )

    info_str = "\n".join(info_msgs) if info_msgs else ""
    if info_str:
        transcript = f"_{info_str}_\n\n{transcript}"
    return (transcript, visual_md, quality_summary, str(out_dir))


def build_ui():
    """Construct the Gradio Blocks UI. Caller invokes .launch()."""
    import gradio as gr
    from skills.youtube_transcribe.presets.loader import list_preset_names

    BACKEND_CHOICES = [
        "(default)", "smart", "subtitles", "whisper-local",
        "gemini", "groq", "openai", "deepgram", "assemblyai", "custom",
    ]
    DETECT_CHOICES = [
        "(preset default)",
        "keywords_only", "semantic", "hybrid", "llm_full_pass",
    ]

    with gr.Blocks(title="youtube-transcribe") as demo:
        gr.Markdown(
            "# youtube-transcribe\n"
            "Universal audio/video transcription — YouTube, Instagram, "
            "TikTok, Vimeo, local files."
        )
        with gr.Tabs():
            # === Tab 1: Transcribe (single video / file) — v0.5 ===
            with gr.Tab("Transcribe"):
                with gr.Row():
                    with gr.Column(scale=2):
                        url = gr.Textbox(
                            label="URL or local file path",
                            placeholder="https://youtu.be/... or /path/to/audio.mp3",
                        )
                        with gr.Row():
                            preset = gr.Dropdown(
                                choices=list_preset_names(),
                                value="smart",
                                label="Preset",
                            )
                            backend = gr.Dropdown(
                                choices=BACKEND_CHOICES, value="(default)",
                                label="Transcribe backend (override)",
                            )
                        with gr.Accordion("Visual mode", open=False):
                            with_visuals = gr.Checkbox(label="Enable visuals (Gemini)")
                            detect_method = gr.Dropdown(
                                choices=DETECT_CHOICES, value="(preset default)",
                                label="Detection method",
                            )
                            max_windows = gr.Slider(
                                minimum=0, maximum=50, value=20, step=1,
                                label="Max visual windows per video",
                            )
                        with gr.Accordion("Quality", open=False):
                            correct_asr = gr.Checkbox(
                                label="Run ASR error correction on low-quality transcripts",
                            )
                        run_btn = gr.Button("Transcribe", variant="primary")
                    with gr.Column(scale=3):
                        with gr.Tabs():
                            with gr.TabItem("Transcript"):
                                transcript_out = gr.Textbox(
                                    label="Transcript", lines=18,
                                )
                            with gr.TabItem("Visual moments"):
                                visual_out = gr.Markdown(label="Visual moments")
                            with gr.TabItem("Quality"):
                                quality_out = gr.Markdown(label="Quality breakdown")
                        output_dir = gr.Textbox(
                            label="Output directory (system temp)",
                            interactive=False,
                        )

                run_btn.click(
                    _run_one,
                    inputs=[
                        url, preset, backend,
                        with_visuals, detect_method, max_windows,
                        correct_asr,
                    ],
                    outputs=[transcript_out, visual_out, quality_out, output_dir],
                )

            # === Tabs 2-3: Research + Subscribes — v0.7 ===
            build_research_tab(gr)
            build_subscribes_tab(gr)

    return demo


# === v0.7: Research + Subscribes tabs ===


def build_research_tab(gr):
    """Add a Research tab to an enclosing gr.Blocks() context."""
    with gr.Tab("Research"):
        gr.Markdown("# Research a topic\n"
                    "Search + filter + transcribe + analyze in one pass.")
        query = gr.Textbox(label="Query", placeholder="Claude новинки за неделю")
        with gr.Row():
            languages = gr.Textbox(label="Languages (CSV)", value="ru,en")
            days = gr.Number(label="Days", value=30, precision=0)
            limit = gr.Number(label="Limit", value=20, precision=0)
        match_text = gr.Textbox(label="--match (substring)", value="")
        filter_text = gr.Textbox(label="--filter (LLM)", value="")
        backend = gr.Dropdown(
            label="Transcription backend",
            choices=["smart", "subtitles", "whisper-local",
                      "gemini", "groq", "openai", "deepgram", "assemblyai"],
            value="smart",
        )
        with gr.Row():
            analyze_backend = gr.Dropdown(
                label="Analyze LLM",
                choices=["gemini", "claude", "openai", "ollama"],
                value="gemini",
            )
            filter_backend = gr.Dropdown(
                label="Filter LLM",
                choices=["gemini", "claude", "openai", "ollama"],
                value="gemini",
            )
        prompt = gr.Textbox(label="Analyze prompt", lines=4)
        no_analyze = gr.Checkbox(label="Skip analyze (just transcribe)",
                                  value=False)
        submit = gr.Button("Run research", variant="primary")
        output = gr.Textbox(label="Output path", interactive=False, lines=2)

        submit.click(
            fn=_handle_research_submit,
            inputs=[query, languages, days, limit,
                    match_text, filter_text,
                    no_analyze, gr.State(True),
                    prompt, analyze_backend, filter_backend, backend],
            outputs=[output],
        )


def _handle_research_submit(
    query, languages_csv, days, limit, match_text, filter_text,
    no_analyze, yes, prompt, analyze_backend, filter_backend, backend,
):
    """Webui callback — delegate to research.pipeline.run_research."""
    from skills.youtube_transcribe.research.pipeline import run_research
    from skills.youtube_transcribe.config import (
        get_api_key, load_config, CONFIG_PATH,
    )
    import time as _time

    cfg = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else None
    languages = [s.strip() for s in (languages_csv or "ru,en").split(",")]
    api_keys = {
        "gemini": get_api_key("gemini"),
        "anthropic": get_api_key("anthropic"),
        "openai": get_api_key("openai"),
        "ollama": None,
    }
    batch_opts = {"backend": backend} if backend else {}
    try:
        result = run_research(
            query=query or None,
            queries_by_language=None,
            languages=languages,
            days=int(days) if days else 30,
            since=None, until=None,
            limit=int(limit) if limit else 20,
            match=match_text or None,
            filter_text=filter_text or None,
            in_subscribes=False, group=None,
            yes=bool(yes), no_analyze=bool(no_analyze),
            prompt=prompt or None, prompt_file=None,
            analyze_backend=analyze_backend,
            filter_backend=filter_backend,
            translate_backend=analyze_backend,
            ollama_model="llama3.2:3b",
            ollama_host="http://localhost:11434",
            no_stdout=True,
            output_dir=cfg.output_dir if cfg else "./transcripts",
            batch_name=f"webui_research_{int(_time.time())}",
            api_keys=api_keys,
            batch_opts=batch_opts,
        )
        return f"✓ Result: {result}" if result else "Nothing produced"
    except Exception as e:
        return f"Error: {e}"


def build_subscribes_tab(gr):
    """Add a Subscribes tab to an enclosing gr.Blocks() context."""
    with gr.Tab("Subscribes"):
        gr.Markdown("# Subscribes\nManage and update your channel list.")
        with gr.Row():
            url_input = gr.Textbox(label="Channel URL or @handle",
                                    placeholder="https://www.youtube.com/@AnthropicAI")
            group_input = gr.Textbox(label="Group (optional)")
            add_btn = gr.Button("Add channel")
        list_output = gr.Textbox(label="Channels", lines=10, interactive=False)
        refresh_btn = gr.Button("Refresh list")

        gr.Markdown("---\n## Run update")
        with gr.Row():
            update_group = gr.Textbox(label="--group (filter, optional)")
            update_days = gr.Number(label="--days (override)", value=0, precision=0)
        update_prompt = gr.Textbox(label="Analyze prompt", lines=3)
        update_no_analyze = gr.Checkbox(label="--no-analyze", value=False)
        update_backend = gr.Dropdown(
            label="Transcription backend",
            choices=["smart", "subtitles", "whisper-local", "gemini"],
            value="smart",
        )
        update_analyze_backend = gr.Dropdown(
            label="Analyze LLM",
            choices=["gemini", "claude", "openai", "ollama"],
            value="gemini",
        )
        update_btn = gr.Button("Run subscribes update", variant="primary")
        update_output = gr.Textbox(label="Result", interactive=False, lines=2)

        add_btn.click(
            fn=_handle_subscribes_add,
            inputs=[url_input, group_input],
            outputs=[list_output],
        )
        refresh_btn.click(
            fn=_handle_subscribes_list,
            outputs=[list_output],
        )
        update_btn.click(
            fn=_handle_subscribes_update,
            inputs=[update_group, update_days, update_no_analyze,
                    gr.State(True),
                    update_prompt, update_analyze_backend, update_backend],
            outputs=[update_output],
        )


def _handle_subscribes_add(channel_url, group):
    from datetime import date
    from skills.youtube_transcribe.subscribes.cli import (
        SUBSCRIBES_PATH, resolve_channel, add_channel,
    )
    from skills.youtube_transcribe.subscribes.store import Channel
    if not channel_url:
        return "Empty URL"
    try:
        resolved = resolve_channel(channel_url)
    except ValueError as e:
        return f"Resolution failed: {e}"
    add_channel(SUBSCRIBES_PATH, Channel(
        url=resolved.url, handle=resolved.handle,
        channel_id=resolved.channel_id,
        group=group or None,
        added=date.today().isoformat(),
    ))
    return _handle_subscribes_list()


def _handle_subscribes_list():
    from skills.youtube_transcribe.subscribes.cli import SUBSCRIBES_PATH
    from skills.youtube_transcribe.subscribes.store import load_subscribes
    chans = load_subscribes(SUBSCRIBES_PATH)
    if not chans:
        return "(no channels)"
    lines = []
    for c in chans:
        lines.append(
            f"{c.handle or c.url}  [{c.group or '—'}]  "
            f"last_seen={c.last_seen_published or '—'}"
        )
    return "\n".join(lines)


def _handle_subscribes_update(group, days, no_analyze, yes,
                               prompt, analyze_backend, backend):
    from skills.youtube_transcribe.subscribes.cli import SUBSCRIBES_PATH
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update,
    )
    from skills.youtube_transcribe.config import (
        get_api_key, load_config, CONFIG_PATH,
    )
    api_keys = {
        "gemini": get_api_key("gemini"),
        "anthropic": get_api_key("anthropic"),
        "openai": get_api_key("openai"),
        "ollama": None,
    }
    cfg = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else None
    output_dir = cfg.output_dir if cfg else "./transcripts"
    batch_opts = {"backend": backend} if backend else {}
    try:
        result = run_subscribes_update(
            subscribes_path=SUBSCRIBES_PATH,
            group=group or None,
            days=int(days) if days else None,
            since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=bool(yes),
            no_analyze=bool(no_analyze),
            prompt=prompt or None, prompt_file=None,
            analyze_backend=analyze_backend,
            filter_backend=analyze_backend,
            ollama_model="llama3.2:3b",
            ollama_host="http://localhost:11434",
            no_stdout=True,
            output_dir=output_dir,
            api_keys=api_keys,
            batch_opts=batch_opts,
        )
        return f"✓ Result: {result}" if result else "Nothing produced"
    except Exception as e:
        return f"Error: {e}"


def launch(server_name: str = "127.0.0.1", server_port: int = 7860, share: bool = False):
    """CLI entry-point. Builds the UI and launches the Gradio server."""
    demo = build_ui()
    demo.launch(server_name=server_name, server_port=server_port, share=share)
