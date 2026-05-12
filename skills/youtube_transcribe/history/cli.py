"""CLI for `youtube-transcribe history` — list and show past runs."""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from skills.youtube_transcribe.history.store import (
    list_runs, get_run,
)

HISTORY_PATH = Path.home() / ".youtube-transcribe" / "history.toml"

_console = Console()


@click.group(name="history")
def history_group() -> None:
    """View past research / subscribes runs."""


@history_group.command(name="list")
@click.option("--last", "limit", type=int, default=10, show_default=True,
              help="How many runs to show (newest first).")
@click.option("--type", "type_filter",
              type=click.Choice(["research", "subscribes"]),
              default=None,
              help="Filter by run type.")
def list_cmd(limit: int, type_filter: str | None) -> None:
    """List recent runs."""
    runs = list_runs(HISTORY_PATH, limit=limit, type_filter=type_filter)
    if not runs:
        _console.print("[yellow]История пуста (no runs yet).[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("When")
    table.add_column("Query / Group")
    table.add_column("Videos")
    table.add_column("Status")
    for r in runs:
        target = r.query or r.group or "—"
        table.add_row(
            r.id, r.type, r.timestamp,
            (target[:40] + "…") if target and len(target) > 40 else target,
            str(r.videos_found),
            r.status,
        )
    _console.print(table)


@history_group.command(name="show")
@click.argument("run_id")
def show_cmd(run_id: str) -> None:
    """Show full details for one run."""
    r = get_run(HISTORY_PATH, run_id)
    if r is None:
        _console.print(f"[red]Run not found: {run_id}[/red]")
        raise SystemExit(2)
    _console.print(f"[bold]ID:[/bold] {r.id}")
    _console.print(f"[bold]Type:[/bold] {r.type}")
    _console.print(f"[bold]Timestamp:[/bold] {r.timestamp}")
    if r.query:
        _console.print(f"[bold]Query:[/bold] {r.query}")
    if r.group:
        _console.print(f"[bold]Group:[/bold] {r.group}")
    if r.languages:
        _console.print(f"[bold]Languages:[/bold] {', '.join(r.languages)}")
    _console.print(f"[bold]Output:[/bold] {r.output}")
    _console.print(f"[bold]Videos found:[/bold] {r.videos_found}")
    _console.print(f"[bold]Status:[/bold] {r.status}")
    if r.analyze_backend:
        _console.print(f"[bold]Analyze backend:[/bold] {r.analyze_backend}")
    if r.analyze_prompt_preview:
        _console.print(f"[bold]Prompt:[/bold] {r.analyze_prompt_preview}")
