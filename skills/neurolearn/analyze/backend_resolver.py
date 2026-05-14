"""Resolve which LLM backend should run the post-transcribe `analyze` step.

Decision order (first hit wins):
  1. caller passed `--no-analyze`  →  None (skip)
  2. caller passed `--analyze-backend X` flag explicitly  →  X
  3. config has `analyze_backend = "skip"`  →  None
  4. config has `analyze_backend = X`  →  X
  5. TTY + no preference saved  →  interactive onboarding,
     save choice to config, return it
  6. non-TTY (Claude Code, pipe, CI)  →  None (silent skip)

The point: the chat-side Claude (or any harness driving the CLI without a
TTY) gets transcripts only, by default. A standalone CLI user gets one
prompt on first run, then their choice is remembered.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from skills.neurolearn.config import (
    CONFIG_PATH, Config, load_config, save_config,
)

_VALID_BACKENDS = ("skip", "gemini", "claude", "openai", "ollama")
_console = Console()


def resolve_analyze_backend(
    *,
    cli_flag: str | None,
    no_analyze: bool,
    config_path: Path = CONFIG_PATH,
    is_tty: bool | None = None,
) -> str | None:
    """Return the analyze backend to use, or None to skip the step.

    The `is_tty` parameter exists for tests; production callers leave it
    None and `sys.stdin.isatty()` is consulted.
    """
    if no_analyze:
        return None
    if cli_flag:
        return cli_flag

    cfg = load_config(config_path) if config_path.exists() else None
    saved = cfg.analyze_backend if cfg else None
    if saved == "skip":
        return None
    if saved in _VALID_BACKENDS and saved != "skip":
        return saved

    # No saved preference. In a TTY ask once and persist; otherwise skip.
    tty = is_tty if is_tty is not None else sys.stdin.isatty()
    if not tty:
        return None

    choice = _prompt_for_default()
    _persist_choice(choice, config_path)
    return None if choice == "skip" else choice


def _prompt_for_default() -> str:
    """One-shot interactive prompt. Returns one of _VALID_BACKENDS."""
    _console.print(
        "\n[bold]Which LLM should analyze transcripts by default?[/bold]"
    )
    _console.print(
        "  [cyan]1[/cyan]) skip   — don't analyze; emit combined.md only "
        "(use Claude in chat to read it)\n"
        "  [cyan]2[/cyan]) gemini — Google Gemini API "
        "[dim](needs GEMINI_API_KEY)[/dim]\n"
        "  [cyan]3[/cyan]) claude — Anthropic Claude API "
        "[dim](needs ANTHROPIC_API_KEY)[/dim]\n"
        "  [cyan]4[/cyan]) openai — OpenAI API "
        "[dim](needs OPENAI_API_KEY)[/dim]\n"
        "  [cyan]5[/cyan]) ollama — local via `ollama serve`\n"
    )
    choice = click.prompt(
        "Choice",
        type=click.Choice(["1", "2", "3", "4", "5"]),
        default="1",
        show_choices=False,
        show_default=True,
    )
    return _VALID_BACKENDS[int(choice) - 1]


def _persist_choice(choice: str, config_path: Path) -> None:
    cfg = (
        load_config(config_path)
        if config_path.exists()
        else Config()
    )
    cfg.analyze_backend = choice
    save_config(cfg, config_path)
    _console.print(
        f"[dim]→ saved to {config_path}: analyze.backend = "
        f"{choice!r}.[/dim]\n"
        f"[dim]To change later: edit the TOML or pass --analyze-backend.[/dim]"
    )
