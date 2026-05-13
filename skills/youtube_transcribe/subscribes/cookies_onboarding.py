"""One-shot cookies prompt for Instagram / TikTok on first `subscribes add`.

Decision order (returns the browser name to use, or "" for anonymous):
  1. config has `<platform>.cookies_browser` set non-empty  → use it
  2. non-TTY                                                 → "" (silent anon)
  3. TTY + no preference                                     → prompt, persist,
                                                              return choice

Instagram on `""` will almost always fail with 401 — we still try, since the
user explicitly picked "none". TikTok on `""` usually works.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from skills.youtube_transcribe.config import (
    CONFIG_PATH, Config, load_config, save_config,
)


_BROWSERS = ("chrome", "firefox", "edge", "safari", "")  # "" = anonymous
_CHOICES_DISPLAY = ("chrome", "firefox", "edge", "safari", "none")
_console = Console()


def resolve_cookies_browser(
    platform: str,
    *,
    config_path: Path = CONFIG_PATH,
    is_tty: bool | None = None,
) -> str:
    """Return the cookies browser to use for `platform` (or "" for anon).

    Promises NOT to prompt the user more than once per platform per machine —
    the choice is persisted to config.toml under `[<platform>] cookies_browser`.
    """
    if platform not in ("instagram", "tiktok"):
        return ""  # YouTube doesn't need cookies for public RSS feeds

    cfg = load_config(config_path) if config_path.exists() else None
    saved = (
        cfg.instagram_cookies_browser if platform == "instagram"
        else cfg.tiktok_cookies_browser
    ) if cfg else ""

    if saved:
        return saved

    tty = is_tty if is_tty is not None else sys.stdin.isatty()
    if not tty:
        # Persist explicit "" so the next non-TTY run doesn't keep treating
        # this as "not chosen". A standalone CLI user can still override
        # later via `config set <platform>.cookies_browser <browser>`.
        return ""

    choice = _prompt(platform)
    _persist(platform, choice, config_path)
    return choice


def _prompt(platform: str) -> str:
    title = "Instagram" if platform == "instagram" else "TikTok"
    hint = (
        "обычно требует залогиненную сессию"
        if platform == "instagram"
        else "иногда работает анонимно, но если канал приватный — нужен залогин"
    )
    _console.print(
        f"\n[bold]{title} {hint}.[/bold]\n"
        "Из какого браузера брать cookies?"
    )
    _console.print(
        "  [cyan]1[/cyan]) chrome\n"
        "  [cyan]2[/cyan]) firefox\n"
        "  [cyan]3[/cyan]) edge\n"
        "  [cyan]4[/cyan]) safari\n"
        "  [cyan]5[/cyan]) none [dim](попробую анонимно — Instagram скорее всего "
        "вернёт 401)[/dim]"
    )
    choice = click.prompt(
        "Выбор",
        type=click.Choice(["1", "2", "3", "4", "5"]),
        default="1",
        show_choices=False,
        show_default=True,
    )
    return _BROWSERS[int(choice) - 1]


def _persist(platform: str, choice: str, config_path: Path) -> None:
    cfg = load_config(config_path) if config_path.exists() else Config()
    if platform == "instagram":
        cfg.instagram_cookies_browser = choice
    else:
        cfg.tiktok_cookies_browser = choice
    save_config(cfg, config_path)
    display = choice if choice else "none (anonymous)"
    _console.print(
        f"[dim]→ сохранено: [{platform}] cookies_browser = "
        f"{display!r}.[/dim]\n"
        f"[dim]Сменить позже: правка ~/.youtube-transcribe/config.toml.[/dim]"
    )
