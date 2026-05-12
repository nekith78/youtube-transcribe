"""CLI for `youtube-transcribe subscribes` group:
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

from skills.youtube_transcribe.subscribes.store import (
    Channel, add_channel, load_subscribes, remove_channel,
)
from skills.youtube_transcribe.subscribes.group import filter_by_group
from skills.youtube_transcribe.subscribes.channel_resolver import (
    resolve_channel,
)
from skills.youtube_transcribe.subscribes.schedule import (
    detect_platform, parse_interval,
    generate_cron_line, generate_launchd_plist,
    generate_systemd_units, generate_taskscheduler_xml,
)

SUBSCRIBES_PATH = Path.home() / ".youtube-transcribe" / "subscribes.toml"

_console = Console()


@click.group(name="subscribes")
def subscribes_group() -> None:
    """Manage and run subscribes (channel list + incremental update)."""


@subscribes_group.command(name="add")
@click.argument("channel_url")
@click.option("--group", default=None,
              help="Optional group tag (e.g. 'ai-research').")
def add_cmd(channel_url: str, group: str | None) -> None:
    """Add a channel by URL or @handle."""
    try:
        resolved = resolve_channel(channel_url)
    except ValueError as e:
        _console.print(f"[red]Не удалось распознать канал:[/red] {e}")
        sys.exit(3)

    channel = Channel(
        url=resolved.url,
        handle=resolved.handle,
        channel_id=resolved.channel_id,
        group=group,
        added=date.today().isoformat(),
    )
    add_channel(SUBSCRIBES_PATH, channel)
    _console.print(
        f"[green]✓[/green] Добавлен {resolved.handle or resolved.url} "
        f"(channel_id={resolved.channel_id}, group={group or '—'})"
    )


@subscribes_group.command(name="remove")
@click.argument("identifier")
def remove_cmd(identifier: str) -> None:
    """Remove a channel by handle, URL, or channel_id."""
    if not remove_channel(SUBSCRIBES_PATH, identifier):
        _console.print(f"[red]Канал не найден: {identifier}[/red]")
        sys.exit(3)
    _console.print(f"[green]✓[/green] Удалён {identifier}")


@subscribes_group.command(name="list")
@click.option("--group", default=None, help="Filter by group.")
def list_cmd(group: str | None) -> None:
    """List subscribed channels."""
    channels = load_subscribes(SUBSCRIBES_PATH)
    channels = filter_by_group(channels, group)
    if not channels:
        _console.print("[yellow]Нет каналов.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Handle")
    table.add_column("Group")
    table.add_column("Channel ID")
    table.add_column("Last seen")
    for c in channels:
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
        SUBSCRIBES_PATH.write_text("# subscribes — youtube-transcribe v0.7\n",
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
              default="gemini")
@click.option("--filter-backend", "filter_backend_opt",
              type=click.Choice(["gemini", "claude", "openai", "ollama"]),
              default="gemini")
@click.option("--ollama-model", "ollama_model_opt", default=None)
@click.option("--ollama-host", "ollama_host_opt", default=None)
@click.option("--no-stdout", "no_stdout_opt", is_flag=True, default=False)
@click.option("--output-dir", "output_dir_opt", default=None)
@click.option("--backend", "backend_opt",
              type=click.Choice([
                  "subtitles", "whisper-local", "gemini", "groq",
                  "openai", "deepgram", "assemblyai", "custom", "smart",
              ]), default=None)
@click.option("--whisper-model",
              type=click.Choice(["turbo", "large", "medium", "small", "distil"]),
              default=None)
@click.option("--language", "language_opt", default=None)
@click.option("--workers", "workers_opt", type=int, default=1)
def update_cmd(
    group, days, since, until, match, filter_text, no_rss, yes, no_analyze,
    prompt_inline, prompt_file, analyze_backend_opt, filter_backend_opt,
    ollama_model_opt, ollama_host_opt, no_stdout_opt, output_dir_opt,
    **batch_passthrough,
) -> None:
    """Run subscribes update — fetch latest, filter, transcribe, analyze."""
    from datetime import date as _date

    if not no_analyze:
        if bool(prompt_inline) == bool(prompt_file):
            _console.print(
                "[red]При analyze on — нужен ровно один из[/red] "
                "--prompt / --prompt-file."
            )
            sys.exit(2)

    since_d = _date.fromisoformat(since) if since else None
    until_d = _date.fromisoformat(until) if until else None

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
    output_dir = output_dir_opt or (cfg.output_dir if cfg else "./transcripts")
    batch_opts = {k: v for k, v in batch_passthrough.items() if v is not None}

    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update, SubscribesError,
    )
    try:
        run_subscribes_update(
            subscribes_path=SUBSCRIBES_PATH,
            group=group,
            days=days, since=since_d, until=until_d,
            match=match, filter_text=filter_text,
            no_rss=no_rss, yes=yes, no_analyze=no_analyze,
            prompt=prompt_inline, prompt_file=prompt_file,
            analyze_backend=analyze_backend_opt,
            filter_backend=filter_backend_opt,
            ollama_model=ollama_model_opt or "llama3.2:3b",
            ollama_host=ollama_host_opt or "http://localhost:11434",
            no_stdout=no_stdout_opt,
            output_dir=output_dir,
            api_keys=api_keys,
            batch_opts=batch_opts,
        )
    except SubscribesError as e:
        _console.print(f"[red]{e}[/red]")
        sys.exit(2)
    except ValueError as e:
        _console.print(f"[red]{e}[/red]")
        sys.exit(2)


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

    argv = ["youtube-transcribe", "subscribes", "update"]
    if prompt:
        argv.extend(["--prompt", prompt])
    if prompt_file:
        argv.extend(["--prompt-file", str(prompt_file)])
    if group_opt:
        argv.extend(["--group", group_opt])

    if plat == "launchd":
        label = "com.user.yt-tr-subscribes"
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
            command_argv=argv, every_seconds=seconds, label="yt-tr-subscribes",
        )
        _console.print(
            "\n[bold]# Save timer to ~/.config/systemd/user/"
            "yt-tr-subscribes.timer:[/bold]\n"
        )
        click.echo(timer)
        _console.print(
            "\n[bold]# Save service to ~/.config/systemd/user/"
            "yt-tr-subscribes.service:[/bold]\n"
        )
        click.echo(service)
        _console.print(
            "\n[bold]# Then enable + start:[/bold]\n"
            "  systemctl --user daemon-reload\n"
            "  systemctl --user enable --now yt-tr-subscribes.timer\n"
        )
    elif plat == "taskscheduler":
        xml = generate_taskscheduler_xml(
            command_argv=argv, every_seconds=seconds,
            task_name="yt-tr-subscribes",
        )
        _console.print(
            "\n[bold]# Save XML to %TEMP%\\yt-tr-subscribes.xml:[/bold]\n"
        )
        click.echo(xml)
        _console.print(
            "\n[bold]# Then import via schtasks:[/bold]\n"
            "  schtasks /create /tn yt-tr-subscribes /xml "
            "%TEMP%\\yt-tr-subscribes.xml\n"
        )


@schedule_group.command(name="uninstall")
def schedule_uninstall_cmd():
    """Print uninstall instructions for all supported platforms."""
    _console.print(
        "[bold]# macOS (launchd):[/bold]\n"
        "  launchctl unload ~/Library/LaunchAgents/com.user.yt-tr-subscribes.plist\n"
        "  rm ~/Library/LaunchAgents/com.user.yt-tr-subscribes.plist\n\n"
        "[bold]# Linux (cron):[/bold]\n"
        "  crontab -e   # delete the yt-tr-subscribes line\n\n"
        "[bold]# Linux (systemd):[/bold]\n"
        "  systemctl --user disable --now yt-tr-subscribes.timer\n"
        "  rm ~/.config/systemd/user/yt-tr-subscribes.{timer,service}\n\n"
        "[bold]# Windows (Task Scheduler):[/bold]\n"
        "  schtasks /delete /tn yt-tr-subscribes /f\n"
    )
