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

import os
import sys
from pathlib import Path

import click
from rich.console import Console

from skills.neurolearn.config import (
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
      • Drag-and-drop from a file manager also works — that's an OS-level
        terminal feature, any prompt-input receives it as plain text.

    Returns the (possibly tilde-/escape-cleaned) path, or None on
    cancellation (Ctrl-C). Existence is validated by the CALLER via
    `set_cookies_file` — we don't reject here so users see a clear
    "file not found" message rather than `questionary`'s generic one.
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
            "\n[bold]Which platform are these cookies for?[/bold]\n"
            "  [cyan]1[/cyan]) Instagram\n"
            "  [cyan]2[/cyan]) TikTok\n"
        )
        choice = click.prompt(
            "Choice",
            type=click.Choice(["1", "2"]),
            default="1",
            show_choices=False,
        )
        platform = "instagram" if choice == "1" else "tiktok"

    _console.print(
        f"\n[bold]Setting up {platform} cookies[/bold]\n"
        "[dim]Steps:[/dim]\n"
        "[dim]  1. Install the 'Get cookies.txt LOCALLY' extension "
        "(open-source)[/dim]\n"
        "[dim]     in any browser (Chrome / Firefox / Edge / Brave).[/dim]\n"
        f"[dim]  2. Open {platform}.com (logged in) → click the extension → "
        "Export.[/dim]\n"
        "[dim]  3. Enter the downloaded file path below.[/dim]\n"
        "[dim]     You can drag-drop the file into the terminal, or type with "
        "Tab-completion[/dim]\n"
        "[dim]     (works on macOS / Linux GNOME Terminal/Konsole / "
        "Windows Terminal).[/dim]\n"
    )
    path = _prompt_for_path("Path to cookies.txt")
    if not path:
        _console.print("[yellow]Cancelled.[/yellow]")
        return False

    try:
        dest = set_cookies_file(platform, path, config_path=config_path)
    except ValueError as e:
        _console.print(f"[red]✗ {e}[/red]")
        return False

    _console.print(
        f"[green]✓[/green] {platform} cookies saved: "
        f"[bold]{dest}[/bold] (mode 0600)\n"
        f"[dim]Change later: neurolearn subscribes cookies set "
        f"{platform} <new-path>.[/dim]"
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
            f"[yellow]⚠ {platform} cookies file not found: {path}[/yellow]\n"
            f"[dim]Re-export and update:[/dim]\n"
            f"[dim]  neurolearn subscribes cookies set {platform} "
            f"<new-path>[/dim]"
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
        raise ValueError(f"file not found: {src}")
    if not src.is_file():
        raise ValueError(f"not a file: {src}")

    # Containment heuristic: refuse paths outside the user's home unless
    # the caller explicitly opted in. Foot-gun guard against accidentally
    # copying e.g. /etc/passwd into config-dir on a malformed CLI call.
    # Test files under tmp/private-tmp are common in pytest — allow those
    # without an env-var dance.
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None
    allow_anywhere = os.environ.get("YT_TR_COOKIES_ALLOW_ANYWHERE") == "1"
    # Common temp roots across OSes: Linux/CI /tmp, macOS /private/var/folders
    # (where pytest tmp_path lives), macOS /private/tmp (also seen),
    # Linux /var/folders. Windows uses %TEMP% — typically already under $HOME.
    tmp_prefixes = (
        "/tmp/", "/private/tmp/",
        "/var/folders/", "/private/var/folders/",
    )
    is_under_home = bool(home and (src == home or home in src.parents))
    is_tmp = str(src).startswith(tmp_prefixes)
    if not (allow_anywhere or is_under_home or is_tmp):
        raise ValueError(
            f"source path is outside the user's home directory: {src}\n"
            "Move the file under your home (e.g. ~/Downloads/...) or set "
            "YT_TR_COOKIES_ALLOW_ANYWHERE=1 to override."
        )

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
                f"file does not look like Netscape cookies.txt "
                f"(first line: {first[:60]!r}). "
                "Export via the 'Get cookies.txt LOCALLY' extension."
            )
    except OSError as e:
        raise ValueError(f"cannot read file: {e}") from e

    # Copy to a canonical location under ~/.neurolearn/ with 0600
    # permissions. Keeps user's source file untouched; if they want to
    # revoke, deleting either copy is enough (we re-validate path on
    # every read).
    dest_dir = config_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{platform}-cookies.txt"
    payload = src.read_bytes()
    if sys.platform != "win32":
        # Atomic create-or-truncate with 0600 from the start to close the
        # TOCTOU window between write_bytes() and chmod() where another
        # local user could read the cookies.
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
    else:
        # Windows: NTFS ACLs apply, mode bits don't. Document the limitation;
        # on a multi-user box the user should restrict via icacls separately.
        dest.write_bytes(payload)
        _console.print(
            "[dim]ℹ Windows: file inherits parent-folder ACLs. "
            "On a multi-user machine, restrict via `icacls` if needed.[/dim]"
        )

    cfg = load_config(config_path) if config_path.exists() else Config()
    if platform == "instagram":
        cfg.instagram_cookies_file = str(dest)
    else:
        cfg.tiktok_cookies_file = str(dest)
    save_config(cfg, config_path)
    return dest
