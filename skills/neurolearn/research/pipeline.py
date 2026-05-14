"""Research command orchestration — search → filter → transcribe → analyze."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

from rich.console import Console

from skills.neurolearn.research.translator import (
    build_queries_per_language,
)
from skills.neurolearn.research.source import (
    SearchCandidate, search_multi_language,
)
from skills.neurolearn.shared.date_filter import (
    parse_window, in_window, DateWindow,
)
from skills.neurolearn.shared.match import match_titles
from skills.neurolearn.shared.llm_screen import screen_candidates
from skills.neurolearn.subscribes.store import load_subscribes
from skills.neurolearn.subscribes.group import filter_by_group
from skills.neurolearn.subscribes.rss import fetch_rss
from skills.neurolearn.history.store import (
    RunEntry, append_run,
)
from skills.neurolearn.transcribe import (
    _run_batch_pipeline, _run_then_analyze, _stdin_is_tty,
)
from skills.neurolearn.utils.resolver import ResolvedTarget

_console = Console()


def run_research(
    *,
    query: str | None,
    queries_by_language: dict[str, str] | None,
    languages: list[str],
    source_lang_hint: str | None = None,
    days: int | None,
    since: date | None,
    until: date | None,
    limit: int,
    match: str | None,
    filter_text: str | None,
    in_subscribes: bool,
    group: str | None,
    yes: bool,
    no_analyze: bool,
    prompt: str | None,
    prompt_file: Path | None,
    analyze_backend: str,
    filter_backend: str,
    translate_backend: str,
    ollama_model: str,
    ollama_host: str,
    no_stdout: bool,
    output_dir: str,
    batch_name: str,
    api_keys: dict[str, str | None],
    batch_opts: dict,
) -> Path | None:
    """Run the full research pipeline. Returns batch folder Path or None."""

    # 1. Build per-language queries (or use explicit ones).
    if queries_by_language:
        queries = queries_by_language
        languages_used = list(queries.keys())
    elif query:
        queries = build_queries_per_language(
            query, languages=languages,
            source_lang_hint=source_lang_hint,
            backend=translate_backend,
            api_key=api_keys.get(_backend_to_key(translate_backend)),
            ollama_model=ollama_model, ollama_host=ollama_host,
        )
        languages_used = list(languages)
    else:
        queries = {}
        languages_used = []

    # 2. Source: search OR cross-pollination from subscribes
    candidates: list = []
    if in_subscribes:
        candidates = _fetch_from_subscribes(group, limit)
    else:
        # Translate the date window into a "days hint" so source.py can pick
        # YouTube's built-in SP filter. `--since A` without `--until` →
        # treat as "days from A to today".
        days_hint: int | None = days
        if days_hint is None and since is not None:
            days_hint = max((date.today() - since).days, 1)
        candidates = search_multi_language(
            queries, limit=limit, days=days_hint,
        )

    if not candidates:
        _console.print("[yellow]No candidates found.[/yellow]")
        return None

    # 3. Date filter
    window = parse_window(
        days=days, since=since, until=until, now=date.today(),
    )
    if window is not None:
        candidates = _filter_by_window(candidates, window)
        if not candidates:
            _console.print(
                "[yellow]Date filter left 0 candidates.[/yellow]"
            )
            return None

    # 4. substring --match
    if match:
        candidates = match_titles(candidates, match)
        if not candidates:
            _console.print(f"[yellow]--match '{match}' left 0 candidates.[/yellow]")
            return None

    # 5. LLM --filter
    if filter_text:
        candidates = screen_candidates(
            candidates, filter_text,
            backend=filter_backend,
            api_key=api_keys.get(_backend_to_key(filter_backend)),
            ollama_model=ollama_model, ollama_host=ollama_host,
        )
        if not candidates:
            _console.print("[yellow]LLM filter left 0 candidates.[/yellow]")
            return None

    # 6. TTY checkpoint
    if not yes and _stdin_is_tty():
        candidates = _tty_checkpoint(candidates)
        if not candidates:
            _console.print("[yellow]Cancelled.[/yellow]")
            return None

    # 7. Convert to ResolvedTarget and run batch_pipeline
    targets = [_to_resolved_target(c) for c in candidates]
    cfg = _load_default_cfg()
    opts = {
        "output_dir": output_dir,
        "batch_name": batch_name,
        "no_combined": batch_opts.get("no_combined", False),
        "fail_fast": batch_opts.get("fail_fast", False),
        **batch_opts,
    }
    batch_dir = _run_batch_pipeline(targets=targets, cfg=cfg, opts=opts)

    # 8. Analyze (unless --no-analyze)
    analyze_attempted = False
    analyze_produced = False
    if not no_analyze and batch_dir is not None and batch_dir.exists():
        analyze_attempted = True
        _run_then_analyze(
            batch_folder=batch_dir,
            prompt_inline=prompt,
            prompt_file=prompt_file,
            backend=analyze_backend,
        )
        # _run_then_analyze swallows errors and returns silently.
        # Detect success by the presence of an analysis-*.md artefact.
        analyze_produced = any(batch_dir.glob("analysis-*.md"))

    # Status semantics:
    #   batch_dir is None       → "failed"  (transcription stage produced nothing)
    #   analyze attempted but no analysis-*.md → "partial"
    #   otherwise                              → "ok"
    if batch_dir is None:
        status = "failed"
    elif analyze_attempted and not analyze_produced:
        status = "partial"
    else:
        status = "ok"

    # 9. History entry
    _append_history(
        type_="research", query=query, group=group,
        languages=languages_used,
        output=str(batch_dir) if batch_dir else "",
        videos_found=len(candidates),
        prompt=prompt or (prompt_file.read_text() if prompt_file else None),
        analyze_backend=None if no_analyze else analyze_backend,
        status=status,
    )

    return batch_dir


def _fetch_from_subscribes(group: str | None, limit: int) -> list:
    """Pull latest videos from subscribes channels (via RSS)."""
    sub_path = Path.home() / ".neurolearn" / "subscribes.toml"
    channels = load_subscribes(sub_path)
    channels = filter_by_group(channels, group)
    out = []
    for ch in channels:
        if not ch.channel_id:
            continue
        entries = fetch_rss(ch.channel_id)
        for e in entries[:limit]:
            out.append(_rss_to_candidate(e, channel_title=ch.handle or ch.url))
    return out


def _rss_to_candidate(entry, *, channel_title: str):
    return SearchCandidate(
        video_id=entry.video_id, url=entry.url, title=entry.title,
        channel=channel_title, duration_sec=None,
        upload_date=entry.published.date() if entry.published else None,
        source_language="(subscribes)",
    )


def _filter_by_window(candidates: list, window: DateWindow) -> list:
    """Apply a date window. Candidates without a known date are kept.

    Source semantics:
    - Search with exact SP preset (e.g. --days 30) → YouTube guarantees
      the window server-side; candidates arrive with upload_date=None
      because we used flat extract. Keeping them here is correct — they
      ARE in the window by construction.
    - Search with non-exact days (e.g. --days 14, 90) → source.py used
      full extract, so upload_date is populated and this function drops
      candidates outside the precise window.
    - Subscribes (RSS / yt-dlp channel scrape) → upload_date is always
      present, behaves like the second case.
    """
    out = []
    for c in candidates:
        d = getattr(c, "upload_date", None)
        if d is None:
            out.append(c)
            continue
        if in_window(d, window):
            out.append(c)
    return out


def _tty_checkpoint(candidates: list) -> list:
    """Show interactive checkbox picker; return chosen subset."""
    try:
        import questionary
    except ImportError:
        return list(candidates)
    choices = []
    for i, c in enumerate(candidates, start=1):
        title = (c.title or "—")[:60]
        date_str = c.upload_date.isoformat() if getattr(c, "upload_date", None) else "—"
        label = f"{date_str}  {title}  [{getattr(c, 'channel', '?')}]"
        choices.append(questionary.Choice(title=label, value=i - 1, checked=True))
    answer = questionary.checkbox(
        "Pick videos to analyze (Space=toggle, Enter=ok):",
        choices=choices,
    ).ask()
    if answer is None:
        return []
    return [candidates[i] for i in answer]


def _to_resolved_target(c) -> ResolvedTarget:
    return ResolvedTarget(
        url=c.url, video_id=c.video_id, title=c.title,
        channel=getattr(c, "channel", None),
        duration_sec=getattr(c, "duration_sec", None),
        upload_date=getattr(c, "upload_date", None),
        source="search",
        source_language=getattr(c, "source_language", None),
    )


def _backend_to_key(backend: str) -> str:
    return {"gemini": "gemini", "claude": "anthropic",
            "openai": "openai", "ollama": "ollama"}[backend]


def _load_default_cfg():
    """Load user config, or return DEFAULT_CONFIG if no file exists.

    Fresh installs (no ~/.neurolearn/config.toml yet) must not
    crash — they should fall back to library defaults.
    """
    from skills.neurolearn.config import (
        load_config, CONFIG_PATH, DEFAULT_CONFIG,
    )
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG
    return load_config(CONFIG_PATH)


def _append_history(
    *, type_: str, query, group, languages, output,
    videos_found, prompt, analyze_backend, status: str = "ok",
) -> None:
    p = Path.home() / ".neurolearn" / "history.toml"
    # ID format: `r-MMDD-HHMMSS` / `s-MMDD-HHMMSS` — 13 chars. Conveys
    # type + when at a glance, fits a Rich table column without truncation,
    # second-precision gives collision-free uniqueness for CLI cadence.
    # Year omitted: it's already in the `timestamp` field and `When` column.
    prefix = {"research": "r", "subscribes": "s"}.get(type_, type_[:1])
    ts = datetime.now(timezone.utc).strftime("%m%d-%H%M%S")
    run_id = f"{prefix}-{ts}"
    entry = RunEntry(
        id=run_id, type=type_,
        timestamp=datetime.now(timezone.utc).isoformat(),
        query=query, group=group,
        output=output, videos_found=videos_found,
        analyze_backend=analyze_backend,
        analyze_prompt_preview=((prompt or "")[:200]) if prompt else None,
        status=status, languages=languages or [],
    )
    append_run(p, entry)
