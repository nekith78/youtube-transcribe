"""Interactive URL/query prompts for CLI commands.

When the user invokes `transcribe`, `batch`, `subscribes add`, or `research`
without a positional argument, we prompt for the value instead of failing.
Keeps long URLs out of shell command lines (and out of shell history).

Non-TTY callers (CI, pipes) must pass the argument explicitly — we exit 2
instead of hanging on stdin so scripts fail fast.
"""
from __future__ import annotations

import sys

import click


_NON_TTY_HINT = (
    "Argument required: pass as positional argument, "
    "or run from a TTY for interactive prompt."
)


def _is_tty() -> bool:
    return sys.stdin.isatty()


def prompt_url_or_die(label: str = "Paste URL or file path:") -> str:
    """Prompt for a single URL or path; exit 2 in non-TTY or on empty input.

    Uses questionary.text() so the user gets readline-like editing. Returns
    the trimmed string (validation of URL vs path is the caller's job —
    same flow as if the value had been passed as a positional argument).
    """
    if not _is_tty():
        click.echo(_NON_TTY_HINT, err=True)
        sys.exit(2)
    import questionary
    result = questionary.text(label).ask()
    if result is None:  # Ctrl+C / Esc
        sys.exit(130)
    result = result.strip()
    if not result:
        click.echo("Empty input — aborted.", err=True)
        sys.exit(2)
    return result


def prompt_urls_or_die(
    label: str = "Paste URLs (one per line, empty line to finish):",
) -> list[str]:
    """Prompt for a list of URLs/paths; one per line, empty line ends input.

    Uses stdlib `input()` so terminal paste-of-multiple-lines just works —
    each newline becomes its own entry. Ctrl+D also ends input cleanly.
    Exits 2 if non-TTY or no entries collected.
    """
    if not _is_tty():
        click.echo(_NON_TTY_HINT, err=True)
        sys.exit(2)
    click.echo(label)
    lines: list[str] = []
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            break
        lines.append(line)
    if not lines:
        click.echo("No inputs provided — aborted.", err=True)
        sys.exit(2)
    return lines
