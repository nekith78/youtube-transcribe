"""Cookies-file onboarding for Instagram / TikTok.

Strict policy (see project memory file feedback_cookies_strict_file_only.md):
the skill NEVER reads cookies directly from a browser at runtime. Users
must export their session cookies to a Netscape-format `cookies.txt`
file (e.g. via the open-source "Get cookies.txt LOCALLY" Chrome extension)
and we read that file when invoking yt-dlp.

This module provides two functions:

  resolve_cookies_file(platform, ...)
      Used by `subscribes update` and any other downloader. Returns the
      configured file path or "" — never prompts during a normal run
      (non-blocking; the run continues without cookies, which fails on
      Instagram and may fail on private TikTok).

  set_cookies_file(platform, path)
      Used by the user-facing `subscribes cookies set` command.
      Validates the file looks like a Netscape cookies.txt and
      saves the path to config.toml.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from skills.youtube_transcribe.config import (
    CONFIG_PATH, Config, load_config, save_config,
)


_console = Console()
_NETSCAPE_HEADER_LINES = (
    "# Netscape HTTP Cookie File",
    "# HTTP Cookie File",
)


def _prompt_for_path(label: str) -> str | None:
    """Ask the user for a filesystem path. Cross-platform UX:

      • questionary.path → Tab-autocomplete works on macOS / Linux
        (GNOME Terminal, Konsole, Alacritty, Kitty, WezTerm) / Windows
        Terminal. Internally uses prompt_toolkit which abstracts the
        readline / libedit / pyreadline split.
      • Drag-and-drop из файлового менеджера тоже работает — это
        feature терминала на уровне OS, любой prompt-input её
        получает как обычный текст.

    Returns the (possibly tilde-/escape-cleaned) path, or None on
    cancellation (Ctrl-C). Existence is validated by the CALLER via
    `set_cookies_file` — we don't reject here so users see a clear
    "файл не найден" message rather than `questionary`'s generic one.
    """
    try:
        import questionary
    except ImportError:
        # Hard-dep — shouldn't fire. If it does, fall back to plain click.
        import click as _click
        result = _click.prompt(label, default="")
        return result.strip() or None

    raw = questionary.path(label + ":").ask()
    if raw is None:
        return None
    # macOS Terminal escapes spaces with backslash on drag-and-drop:
    # "/Users/me/My\ Folder/cookies.txt" → strip the escaping.
    return raw.replace("\\ ", " ").strip()


def wizard(
    platform: str | None = None,
    *,
    config_path: Path = CONFIG_PATH,
    is_tty: bool | None = None,
) -> bool:
    """Interactive cookies setup. Returns True if a file was registered.

    Asks for `platform` (instagram / tiktok) if not given, then for a path
    to a Netscape cookies.txt file the user has exported. Validates and
    persists via `set_cookies_file`.

    Non-TTY callers (Claude Code subprocess / CI) get False immediately —
    we do NOT block scripted runs on missing input.
    """
    tty = is_tty if is_tty is not None else sys.stdin.isatty()
    if not tty:
        return False

    if platform is None:
        _console.print(
            "\n[bold]Какой платформы cookies?[/bold]\n"
            "  [cyan]1[/cyan]) Instagram\n"
            "  [cyan]2[/cyan]) TikTok\n"
        )
        choice = click.prompt(
            "Выбор",
            type=click.Choice(["1", "2"]),
            default="1",
            show_choices=False,
        )
        platform = "instagram" if choice == "1" else "tiktok"

    _console.print(
        f"\n[bold]Настройка {platform} cookies[/bold]\n"
        "[dim]Шаги:[/dim]\n"
        "[dim]  1. Поставь расширение 'Get cookies.txt LOCALLY' (open-source) "
        "в любом[/dim]\n"
        "[dim]     браузере (Chrome / Firefox / Edge / Brave).[/dim]\n"
        f"[dim]  2. Открой {platform}.com (залогиненный) → расширение → "
        "Export.[/dim]\n"
        "[dim]  3. Введи путь к скачанному файлу ниже.[/dim]\n"
        "[dim]     Можно перетащить файл в терминал, либо набрать с "
        "Tab-автодополнением[/dim]\n"
        "[dim]     (работает на macOS / Linux GNOME Terminal/Konsole / "
        "Windows Terminal).[/dim]\n"
    )
    path = _prompt_for_path("Путь к cookies.txt")
    if not path:
        _console.print("[yellow]Отменено.[/yellow]")
        return False

    try:
        dest = set_cookies_file(platform, path, config_path=config_path)
    except ValueError as e:
        _console.print(f"[red]✗ {e}[/red]")
        return False

    _console.print(
        f"[green]✓[/green] {platform} cookies сохранены: "
        f"[bold]{dest}[/bold] (mode 0600)\n"
        f"[dim]Сменить позже: yt-tr subscribes cookies set {platform} "
        f"<new-path>.[/dim]"
    )
    return True


def resolve_cookies_file(
    platform: str,
    *,
    config_path: Path = CONFIG_PATH,
) -> str:
    """Return the configured cookies-file path for `platform`, or "".

    Non-blocking: never prompts. If the user hasn't configured a file,
    we return "" and the caller proceeds without cookies (which fails
    on Instagram — that's the user's signal to run `subscribes cookies
    set instagram <path>`).
    """
    if platform not in ("instagram", "tiktok"):
        return ""

    if not config_path.exists():
        return ""

    cfg = load_config(config_path)
    path = (
        cfg.instagram_cookies_file if platform == "instagram"
        else cfg.tiktok_cookies_file
    )

    if not path:
        return ""
    if not Path(path).expanduser().exists():
        _console.print(
            f"[yellow]⚠ {platform} cookies file не найден: {path}[/yellow]\n"
            f"[dim]Перевыгрузи и обнови:[/dim]\n"
            f"[dim]  yt-tr subscribes cookies set {platform} <new-path>[/dim]"
        )
        return ""
    return str(Path(path).expanduser())


def set_cookies_file(
    platform: str,
    path: str,
    *,
    config_path: Path = CONFIG_PATH,
) -> Path:
    """Validate the file, copy it to a canonical location, save to config.

    Returns the final stored path. Raises ValueError on validation failure.
    """
    if platform not in ("instagram", "tiktok"):
        raise ValueError(
            f"unsupported platform: {platform!r}. Expected 'instagram' or 'tiktok'."
        )

    src = Path(path).expanduser().resolve()
    if not src.exists():
        raise ValueError(f"файл не найден: {src}")
    if not src.is_file():
        raise ValueError(f"не файл: {src}")

    # Basic Netscape format sniff: first non-empty line should be a header
    # or a tab-separated row with 7 fields.
    try:
        first = ""
        with src.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    first = line.strip()
                    break
        looks_netscape = (
            any(first.startswith(h) for h in _NETSCAPE_HEADER_LINES)
            or len(first.split("\t")) == 7
        )
        if not looks_netscape:
            raise ValueError(
                f"файл не похож на Netscape cookies.txt "
                f"(первая строка: {first[:60]!r}). "
                "Экспортируй через расширение 'Get cookies.txt LOCALLY'."
            )
    except OSError as e:
        raise ValueError(f"не могу прочесть файл: {e}") from e

    # Copy to a canonical location under ~/.youtube-transcribe/ with 0600
    # permissions. Keeps user's source file untouched; if they want to
    # revoke, deleting either copy is enough (we re-validate path on
    # every read).
    dest_dir = config_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{platform}-cookies.txt"
    dest.write_bytes(src.read_bytes())
    if sys.platform != "win32":
        try:
            dest.chmod(0o600)
        except OSError:
            pass

    cfg = load_config(config_path) if config_path.exists() else Config()
    if platform == "instagram":
        cfg.instagram_cookies_file = str(dest)
    else:
        cfg.tiktok_cookies_file = str(dest)
    save_config(cfg, config_path)
    return dest
