"""CLI for `neurolearn subscribes` group:
add / remove / list / edit / update / schedule install|uninstall.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from skills.neurolearn.subscribes.store import (
    Channel, add_channel, load_subscribes, remove_channel,
)
from skills.neurolearn.subscribes.group import filter_by_group
from skills.neurolearn.subscribes.channel_resolver import (
    resolve_channel,
)
from skills.neurolearn.subscribes.schedule import (
    detect_platform, parse_interval,
    generate_cron_line, generate_launchd_plist,
    generate_systemd_units, generate_taskscheduler_xml,
)

SUBSCRIBES_PATH = Path.home() / ".neurolearn" / "subscribes.toml"

_console = Console()


@click.group(name="subscribes")
def subscribes_group() -> None:
    """Manage and run subscribes (channel list + incremental update)."""


@subscribes_group.command(name="add")
@click.argument("channel_url", required=False)
@click.option("--group", default=None,
              help="Optional group tag (e.g. 'ai-research').")
def add_cmd(channel_url: str | None, group: str | None) -> None:
    """Add a channel by URL. Platform is auto-detected from the URL."""
    if not channel_url:
        from skills.neurolearn.shared.prompts import prompt_url_or_die
        channel_url = prompt_url_or_die("Paste channel URL:")
    try:
        resolved = resolve_channel(channel_url)
    except ValueError as e:
        _console.print(f"[red]Could not resolve channel:[/red] {e}")
        sys.exit(3)

    # On first IG / TikTok add: if cookies aren't set up yet AND we're in
    # a TTY, offer the interactive wizard. In non-TTY (Claude Code, CI)
    # we silently print a one-liner hint — no blocking prompts.
    if resolved.platform in ("instagram", "tiktok"):
        from skills.neurolearn.subscribes.cookies_onboarding import (
            resolve_cookies_file, wizard,
        )
        if not resolve_cookies_file(resolved.platform):
            if sys.stdin.isatty() and click.confirm(
                f"Cookies for {resolved.platform} are not configured yet. "
                "Set them up now?",
                default=False,
            ):
                wizard(resolved.platform)
            else:
                _console.print(
                    f"[dim]⚠ {resolved.platform} needs cookies. "
                    f"Set them up later: "
                    f"neurolearn subscribes cookies set "
                    f"{resolved.platform}[/dim]"
                )

    channel = Channel(
        url=resolved.url,
        handle=resolved.handle,
        channel_id=resolved.channel_id,
        group=group,
        added=date.today().isoformat(),
        platform=resolved.platform,
    )
    add_channel(SUBSCRIBES_PATH, channel)
    _console.print(
        f"[green]✓[/green] Added {resolved.handle or resolved.url} "
        f"([cyan]{resolved.platform}[/cyan], "
        f"id={resolved.channel_id}, group={group or '—'})"
    )


@subscribes_group.command(name="remove")
@click.argument("identifier")
def remove_cmd(identifier: str) -> None:
    """Remove a channel by handle, URL, or channel_id."""
    if not remove_channel(SUBSCRIBES_PATH, identifier):
        _console.print(f"[red]Channel not found: {identifier}[/red]")
        sys.exit(3)
    _console.print(f"[green]✓[/green] Removed {identifier}")


@subscribes_group.command(name="list")
@click.option("--group", default=None, help="Filter by group.")
@click.option("--platform",
              type=click.Choice(["youtube", "instagram", "tiktok"]),
              default=None,
              help="Show only one platform.")
def list_cmd(group: str | None, platform: str | None) -> None:
    """List subscribed channels grouped by platform."""
    from skills.neurolearn.subscribes.store import PLATFORMS
    channels = load_subscribes(SUBSCRIBES_PATH)
    channels = filter_by_group(channels, group)
    if platform:
        channels = [c for c in channels if c.platform == platform]
    if not channels:
        _console.print("[yellow]No channels.[/yellow]")
        return

    # Partition by platform, render one table per group with non-empty rows.
    by_platform: dict[str, list] = {p: [] for p in PLATFORMS}
    for c in channels:
        # Defensive: silently skip any platform we don't know how to render.
        if c.platform in by_platform:
            by_platform[c.platform].append(c)

    printed_any = False
    for plat in PLATFORMS:
        rows = by_platform[plat]
        if not rows:
            continue
        if printed_any:
            _console.print()
        printed_any = True
        title = {
            "youtube": "YouTube",
            "instagram": "Instagram",
            "tiktok": "TikTok",
        }[plat]
        table = Table(
            title=f"[bold]{title}[/bold]",
            show_header=True, header_style="bold",
        )
        table.add_column("Handle")
        table.add_column("Group")
        table.add_column("Channel ID / Username")
        table.add_column("Last seen")
        for c in rows:
            table.add_row(
                c.handle or "—",
                c.group or "—",
                c.channel_id or "—",
                c.last_seen_published or "—",
            )
        _console.print(table)


@subscribes_group.command(name="edit")
def edit_cmd() -> None:
    """Open subscribes.toml in $EDITOR (vi/notepad fallback)."""
    SUBSCRIBES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SUBSCRIBES_PATH.exists():
        SUBSCRIBES_PATH.write_text("# subscribes — neurolearn v0.7\n",
                                   encoding="utf-8")

    editor = os.environ.get("EDITOR") or _default_editor()
    try:
        subprocess.run([editor, str(SUBSCRIBES_PATH)], check=True)
    except FileNotFoundError:
        _console.print(f"[red]Editor not found: {editor}. Set $EDITOR.[/red]")
        sys.exit(4)
    except subprocess.CalledProcessError as e:
        if e.returncode != 0:
            _console.print(f"[yellow]Editor exited with {e.returncode}[/yellow]")


def _default_editor() -> str:
    """Cross-OS fallback editor."""
    if sys.platform == "win32":
        return "notepad"
    return "vi"


@subscribes_group.command(name="update")
@click.option("--group", default=None)
@click.option("--platform",
              type=click.Choice(["youtube", "instagram", "tiktok"]),
              default=None,
              help="Update only channels from this platform. Combines with "
                   "--group: --platform tiktok --group ai-research → only "
                   "TikTok channels in that group.")
@click.option("--days", type=int, default=None,
              help="Override stateful window: last N days (state NOT updated).")
@click.option("--since", default=None)
@click.option("--until", default=None)
@click.option("--match", default=None)
@click.option("--filter", "filter_text", default=None)
@click.option("--no-rss", is_flag=True, default=False)
@click.option("--yes", is_flag=True, default=False)
@click.option("--no-analyze", is_flag=True, default=False)
@click.option("--prompt", "prompt_inline", default=None)
@click.option("--prompt-file", "prompt_file", default=None,
              type=click.Path(exists=True, path_type=Path))
@click.option("--analyze-backend", "analyze_backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]),
              default=None,
              help="LLM backend for analyze. Default: ask once and remember "
                   "in config.toml (non-TTY → skip silently).")
@click.option("--filter-backend", "filter_backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]),
              default="gemini")
@click.option("--ollama-model", "ollama_model_opt", default=None)
@click.option("--ollama-host", "ollama_host_opt", default=None)
@click.option("--no-stdout", "no_stdout_opt", is_flag=True, default=False)
@click.option("--output-dir", "output_dir_opt", default=None)
@click.option("--backend",
              type=click.Choice([
                  "subtitles", "whisper-local", "gemini", "groq",
                  "openai", "deepgram", "assemblyai", "custom", "smart",
              ]), default=None)
@click.option("--whisper-model",
              type=click.Choice(["turbo", "large", "medium", "small", "distil"]),
              default=None)
@click.option("--language", default=None)
@click.option("--workers", "workers_opt", type=int, default=1)
def update_cmd(
    group, platform, days, since, until, match, filter_text, no_rss, yes,
    no_analyze, prompt_inline, prompt_file, analyze_backend_opt,
    filter_backend_opt, ollama_model_opt, ollama_host_opt, no_stdout_opt,
    output_dir_opt, **batch_passthrough,
) -> None:
    """Run subscribes update — fetch latest, filter, transcribe, analyze."""
    from datetime import date as _date
    from skills.neurolearn.analyze.backend_resolver import (
        resolve_analyze_backend,
    )

    # Resolve analyze backend first (flag > config > onboarding > skip).
    # `None` here means "don't analyze".
    resolved_analyze_backend = resolve_analyze_backend(
        cli_flag=analyze_backend_opt, no_analyze=no_analyze,
    )
    effective_no_analyze = no_analyze or resolved_analyze_backend is None

    if not effective_no_analyze:
        if bool(prompt_inline) == bool(prompt_file):
            _console.print(
                "[red]With analyze enabled — pass exactly one of[/red] "
                "--prompt / --prompt-file."
            )
            sys.exit(2)

    since_d = _date.fromisoformat(since) if since else None
    until_d = _date.fromisoformat(until) if until else None

    from skills.neurolearn.config import (
        get_api_key, load_config, CONFIG_PATH,
    )
    api_keys = {
        "gemini": get_api_key("gemini"),
        "anthropic": get_api_key("anthropic"),
        "openai": get_api_key("openai"),
        "ollama": None,
    }

    cfg = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else None
    output_dir = output_dir_opt or (cfg.output_dir if cfg else "./transcripts")
    batch_opts = {k: v for k, v in batch_passthrough.items() if v is not None}

    # Mid-flow safety net: if --platform targets IG/TT and we're in a TTY
    # but cookies aren't set, give the user one chance to set them via the
    # wizard before yt-dlp gets the "Unable to extract data" error.
    if platform in ("instagram", "tiktok") and sys.stdin.isatty() and cfg is not None:
        cookies_path = (
            cfg.instagram_cookies_file if platform == "instagram"
            else cfg.tiktok_cookies_file
        )
        if not cookies_path:
            if click.confirm(
                f"Cookies for {platform} are not configured — yt-dlp will "
                f"likely fail. Set them up now?",
                default=False,
            ):
                from skills.neurolearn.subscribes.cookies_onboarding import (
                    wizard,
                )
                wizard(platform)
                # Reload config so the just-saved file is picked up below.
                cfg = load_config(CONFIG_PATH)

    from skills.neurolearn.subscribes.pipeline import (
        run_subscribes_update, SubscribesError,
    )
    try:
        run_subscribes_update(
            subscribes_path=SUBSCRIBES_PATH,
            group=group, platform=platform,
            days=days, since=since_d, until=until_d,
            match=match, filter_text=filter_text,
            no_rss=no_rss, yes=yes, no_analyze=effective_no_analyze,
            prompt=prompt_inline, prompt_file=prompt_file,
            analyze_backend=resolved_analyze_backend or "gemini",
            filter_backend=filter_backend_opt,
            ollama_model=ollama_model_opt or "llama3.2:3b",
            ollama_host=ollama_host_opt or "http://localhost:11434",
            no_stdout=no_stdout_opt,
            output_dir=output_dir,
            api_keys=api_keys,
            batch_opts=batch_opts,
            instagram_cookies_file=(
                cfg.instagram_cookies_file if cfg else ""
            ),
            tiktok_cookies_file=(
                cfg.tiktok_cookies_file if cfg else ""
            ),
        )
    except SubscribesError as e:
        _console.print(f"[red]{e}[/red]")
        sys.exit(2)
    except ValueError as e:
        _console.print(f"[red]{e}[/red]")
        sys.exit(2)


@subscribes_group.group(name="cookies")
def cookies_group() -> None:
    """Manage Instagram / TikTok cookies file (Netscape cookies.txt).

    Step-by-step setup:

      1. Install the open-source "Get cookies.txt LOCALLY" extension
         (Chrome / Firefox) — it does NOT phone home.
      2. Open instagram.com (logged in) → click the extension → Export.
         Same for tiktok.com if you need TikTok cookies.
      3. Run:  neurolearn subscribes cookies set instagram ~/Downloads/instagram_com_cookies.txt
              neurolearn subscribes cookies set tiktok    ~/Downloads/tiktok_com_cookies.txt

    The file is copied to `~/.neurolearn/<platform>-cookies.txt`
    with mode 0600. To revoke, just delete that file or run
    `neurolearn subscribes cookies clear <platform>`.
    """


@cookies_group.command(name="set")
@click.argument("platform",
                type=click.Choice(["instagram", "tiktok"]),
                required=False)
@click.argument("path",
                type=click.Path(exists=True, dir_okay=False),
                required=False)
def cookies_set_cmd(platform: str | None, path: str | None) -> None:
    """Register a cookies.txt for PLATFORM.

    Run without arguments to enter the interactive wizard (TTY only):
      neurolearn subscribes cookies set
    Scripted invocation works as before:
      neurolearn subscribes cookies set instagram ~/Downloads/ig.txt
    """
    from skills.neurolearn.subscribes.cookies_onboarding import (
        set_cookies_file, wizard,
    )

    if path is None:
        # Either missing platform too (full wizard) or only path missing
        # (still walk the wizard — it'll re-prompt for the path).
        if not wizard(platform):
            sys.exit(2)
        return

    try:
        dest = set_cookies_file(platform, path)
    except ValueError as e:
        _console.print(f"[red]{e}[/red]")
        sys.exit(2)
    _console.print(
        f"[green]✓[/green] {platform} cookies saved to "
        f"[bold]{dest}[/bold] (mode 0600)\n"
        f"[dim]When yt-dlp returns login-required / empty response — that's "
        f"the signal cookies expired. Re-export and run `cookies set` again.[/dim]"
    )


@cookies_group.command(name="clear")
@click.argument("platform", type=click.Choice(["instagram", "tiktok"]))
def cookies_clear_cmd(platform: str) -> None:
    """Remove the registered cookies file for PLATFORM."""
    from skills.neurolearn.config import (
        CONFIG_PATH, load_config, save_config, Config,
    )
    cfg = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else Config()
    current = (
        cfg.instagram_cookies_file if platform == "instagram"
        else cfg.tiktok_cookies_file
    )
    if not current:
        _console.print(
            f"[yellow]No cookies file configured for {platform}.[/yellow]"
        )
        return
    p = Path(current).expanduser()
    if p.exists():
        try:
            p.unlink()
        except OSError as e:
            _console.print(f"[yellow]Could not remove {p}: {e}[/yellow]")
    if platform == "instagram":
        cfg.instagram_cookies_file = ""
    else:
        cfg.tiktok_cookies_file = ""
    save_config(cfg, CONFIG_PATH)
    _console.print(
        f"[green]✓[/green] {platform} cookies cleared. "
        f"Next `subscribes update` will run anonymously "
        f"(Instagram will likely fail — that's expected)."
    )


@cookies_group.command(name="show")
def cookies_show_cmd() -> None:
    """Show currently configured cookies files."""
    from skills.neurolearn.config import CONFIG_PATH, load_config
    cfg = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else None
    if cfg is None:
        _console.print("[dim]config.toml does not exist.[/dim]")
        return
    rows = [
        ("instagram", cfg.instagram_cookies_file),
        ("tiktok", cfg.tiktok_cookies_file),
    ]
    table = Table(show_header=True, header_style="bold")
    table.add_column("Platform")
    table.add_column("Cookies file")
    table.add_column("Status")
    for plat, p in rows:
        if not p:
            status = "[dim]not set[/dim]"
        elif Path(p).expanduser().exists():
            status = "[green]ok[/green]"
        else:
            status = "[red]missing[/red]"
        table.add_row(plat, p or "—", status)
    _console.print(table)


@subscribes_group.group(name="schedule")
def schedule_group() -> None:
    """Generate scheduler snippets (cron/launchd/systemd/Task Scheduler)."""


@schedule_group.command(name="install")
@click.option("--every", default="1h", show_default=True,
              help="Interval: 15m, 1h, 6h, 1d.")
@click.option("--platform", "platform_opt",
              type=click.Choice(["auto", "cron", "launchd",
                                  "systemd", "taskscheduler"]),
              default="auto", show_default=True)
@click.option("--prompt", default=None,
              help="Embedded prompt for the scheduled subscribes update.")
@click.option("--prompt-file", default=None,
              type=click.Path(exists=True, path_type=Path))
@click.option("--group", "group_opt", default=None)
def schedule_install_cmd(every, platform_opt, prompt, prompt_file, group_opt):
    """Print a schedule snippet + install instructions for the current OS."""
    try:
        seconds = parse_interval(every)
    except ValueError as e:
        _console.print(f"[red]{e}[/red]")
        sys.exit(2)

    plat = detect_platform() if platform_opt == "auto" else platform_opt

    argv = ["neurolearn", "subscribes", "update"]
    if prompt:
        argv.extend(["--prompt", prompt])
    if prompt_file:
        argv.extend(["--prompt-file", str(prompt_file)])
    if group_opt:
        argv.extend(["--group", group_opt])

    if plat == "launchd":
        label = "com.user.neurolearn-subscribes"
        plist = generate_launchd_plist(
            command_argv=argv, every_seconds=seconds, label=label,
        )
        path = f"~/Library/LaunchAgents/{label}.plist"
        _console.print(f"\n[bold]# Save to {path}[/bold]\n")
        click.echo(plist)
        _console.print(
            f"\n[bold]# Then run:[/bold]\n"
            f"  launchctl load {path}\n"
            f"\n[dim]# To remove later:[/dim]\n"
            f"  launchctl unload {path} && rm {path}\n"
        )
    elif plat == "cron":
        line = generate_cron_line(command_argv=argv, every_seconds=seconds)
        _console.print("\n[bold]# Add to crontab via `crontab -e`:[/bold]\n")
        click.echo(line)
        _console.print(
            "\n[dim]# To remove: `crontab -e` and delete the line above.[/dim]\n"
        )
    elif plat == "systemd":
        timer, service = generate_systemd_units(
            command_argv=argv, every_seconds=seconds, label="neurolearn-subscribes",
        )
        _console.print(
            "\n[bold]# Save timer to ~/.config/systemd/user/"
            "neurolearn-subscribes.timer:[/bold]\n"
        )
        click.echo(timer)
        _console.print(
            "\n[bold]# Save service to ~/.config/systemd/user/"
            "neurolearn-subscribes.service:[/bold]\n"
        )
        click.echo(service)
        _console.print(
            "\n[bold]# Then enable + start:[/bold]\n"
            "  systemctl --user daemon-reload\n"
            "  systemctl --user enable --now neurolearn-subscribes.timer\n"
        )
    elif plat == "taskscheduler":
        xml = generate_taskscheduler_xml(
            command_argv=argv, every_seconds=seconds,
            task_name="neurolearn-subscribes",
        )
        _console.print(
            "\n[bold]# Save XML to %TEMP%\\neurolearn-subscribes.xml:[/bold]\n"
        )
        click.echo(xml)
        _console.print(
            "\n[bold]# Then import via schtasks:[/bold]\n"
            "  schtasks /create /tn neurolearn-subscribes /xml "
            "%TEMP%\\neurolearn-subscribes.xml\n"
        )


@schedule_group.command(name="uninstall")
def schedule_uninstall_cmd():
    """Print uninstall instructions for all supported platforms."""
    _console.print(
        "[bold]# macOS (launchd):[/bold]\n"
        "  launchctl unload ~/Library/LaunchAgents/com.user.neurolearn-subscribes.plist\n"
        "  rm ~/Library/LaunchAgents/com.user.neurolearn-subscribes.plist\n\n"
        "[bold]# Linux (cron):[/bold]\n"
        "  crontab -e   # delete the neurolearn-subscribes line\n\n"
        "[bold]# Linux (systemd):[/bold]\n"
        "  systemctl --user disable --now neurolearn-subscribes.timer\n"
        "  rm ~/.config/systemd/user/neurolearn-subscribes.{timer,service}\n\n"
        "[bold]# Windows (Task Scheduler):[/bold]\n"
        "  schtasks /delete /tn neurolearn-subscribes /f\n"
    )
