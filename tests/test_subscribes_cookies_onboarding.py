"""Tests for subscribes.cookies_onboarding — file-based cookies workflow.

Strict rule (see project memory: feedback_cookies_strict_file_only.md):
cookies for Instagram / TikTok come from a user-supplied Netscape
cookies.txt file, never from `--cookies-from-browser`.
"""
from pathlib import Path

import pytest
import tomllib


_NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n"
_FAKE_COOKIE_ROW = (
    ".instagram.com\tTRUE\t/\tTRUE\t9999999999\tsessionid\tfaketokenvalue\n"
)


def _make_cookies_file(p: Path, *, with_header: bool = True) -> Path:
    content = _NETSCAPE_HEADER if with_header else ""
    content += _FAKE_COOKIE_ROW
    p.write_text(content, encoding="utf-8")
    return p


def test_set_cookies_file_persists_to_config(tmp_path: Path):
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        set_cookies_file,
    )
    cfg = tmp_path / "config.toml"
    src = _make_cookies_file(tmp_path / "ig.txt")

    # Patch CONFIG_PATH so set_cookies_file writes alongside it.
    import skills.youtube_transcribe.subscribes.cookies_onboarding as mod
    dest = set_cookies_file("instagram", str(src), config_path=cfg)

    assert dest.exists()
    assert dest.name == "instagram-cookies.txt"
    # Config now points at the canonical location.
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert raw["instagram"]["cookies_file"] == str(dest)


def test_set_cookies_file_rejects_missing(tmp_path: Path):
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        set_cookies_file,
    )
    cfg = tmp_path / "config.toml"
    with pytest.raises(ValueError, match="не найден"):
        set_cookies_file(
            "instagram", str(tmp_path / "missing.txt"), config_path=cfg,
        )


def test_set_cookies_file_rejects_non_netscape(tmp_path: Path):
    """Refuse anything that doesn't look like Netscape cookies.txt — saves the
    user from accidentally pointing at a random text file."""
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        set_cookies_file,
    )
    cfg = tmp_path / "config.toml"
    bad = tmp_path / "not-cookies.txt"
    bad.write_text("This is just a plain text file.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Netscape"):
        set_cookies_file("instagram", str(bad), config_path=cfg)


def test_set_cookies_file_accepts_no_header(tmp_path: Path):
    """7-tab rows without an explicit `# Netscape` header should still pass —
    some extensions omit the header."""
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        set_cookies_file,
    )
    cfg = tmp_path / "config.toml"
    src = _make_cookies_file(tmp_path / "tt.txt", with_header=False)
    dest = set_cookies_file("tiktok", str(src), config_path=cfg)
    assert dest.exists()


def test_set_cookies_file_unknown_platform_raises(tmp_path: Path):
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        set_cookies_file,
    )
    cfg = tmp_path / "config.toml"
    src = _make_cookies_file(tmp_path / "x.txt")
    with pytest.raises(ValueError, match="unsupported platform"):
        set_cookies_file("youtube", str(src), config_path=cfg)


def test_resolve_cookies_file_returns_path_when_set(tmp_path: Path):
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        resolve_cookies_file, set_cookies_file,
    )
    cfg = tmp_path / "config.toml"
    src = _make_cookies_file(tmp_path / "ig.txt")
    set_cookies_file("instagram", str(src), config_path=cfg)

    result = resolve_cookies_file("instagram", config_path=cfg)
    assert result.endswith("instagram-cookies.txt")
    assert Path(result).exists()


def test_resolve_cookies_file_returns_empty_when_unset(tmp_path: Path):
    """No prompt, no interaction — just '' so the caller proceeds anon."""
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        resolve_cookies_file,
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text('default_preset = "smart"\n', encoding="utf-8")
    assert resolve_cookies_file("instagram", config_path=cfg) == ""


def test_resolve_cookies_file_handles_missing_destination(tmp_path: Path):
    """Path in config but file got deleted → warn + return ''. Caller
    treats as 'no cookies'."""
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        resolve_cookies_file,
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'default_preset = "smart"\n\n'
        f'[instagram]\ncookies_file = "{tmp_path / "ghost.txt"}"\n',
        encoding="utf-8",
    )
    assert resolve_cookies_file("instagram", config_path=cfg) == ""


def test_resolve_cookies_file_youtube_always_empty(tmp_path: Path):
    """YouTube channels use public RSS — never use cookies. Even if a
    `[youtube] cookies_file` were somehow set, we'd ignore it."""
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        resolve_cookies_file,
    )
    cfg = tmp_path / "config.toml"
    assert resolve_cookies_file("youtube", config_path=cfg) == ""


# === v0.8.1: interactive wizard ===


def test_wizard_non_tty_returns_false(tmp_path: Path):
    """Non-TTY (CI / Claude Code / pipe) → wizard never blocks; returns False."""
    from skills.youtube_transcribe.subscribes.cookies_onboarding import wizard
    cfg = tmp_path / "config.toml"
    assert wizard("instagram", config_path=cfg, is_tty=False) is False


def test_wizard_full_flow_persists_to_config(tmp_path: Path):
    """TTY path: platform prompt (click) + path prompt (questionary)."""
    from unittest.mock import patch
    from skills.youtube_transcribe.subscribes import cookies_onboarding as mod
    cfg = tmp_path / "config.toml"
    src = _make_cookies_file(tmp_path / "ig.txt")

    # Platform → click.prompt returns "1" (instagram).
    # Path → our _prompt_for_path helper (questionary internally) returns the file.
    with patch("click.prompt", return_value="1"), patch.object(
        mod, "_prompt_for_path", return_value=str(src),
    ):
        ok = mod.wizard(None, config_path=cfg, is_tty=True)

    assert ok is True
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert raw["instagram"]["cookies_file"].endswith("instagram-cookies.txt")


def test_wizard_with_platform_skips_first_prompt(tmp_path: Path):
    """If platform already known (called from `add` or `update`), wizard
    skips the click.Choice prompt and asks only for the path."""
    from unittest.mock import patch
    from skills.youtube_transcribe.subscribes import cookies_onboarding as mod
    cfg = tmp_path / "config.toml"
    src = _make_cookies_file(tmp_path / "tt.txt")

    with patch("click.prompt") as mock_click, patch.object(
        mod, "_prompt_for_path", return_value=str(src),
    ) as mock_path:
        ok = mod.wizard("tiktok", config_path=cfg, is_tty=True)

    assert ok is True
    # No click.prompt — platform was passed in.
    mock_click.assert_not_called()
    # Single path prompt fired.
    mock_path.assert_called_once()


def test_wizard_invalid_file_returns_false(tmp_path: Path):
    """Wizard surfaces validation errors and returns False without crashing."""
    from unittest.mock import patch
    from skills.youtube_transcribe.subscribes import cookies_onboarding as mod
    cfg = tmp_path / "config.toml"
    bad = tmp_path / "garbage.txt"
    bad.write_text("not cookies", encoding="utf-8")

    with patch.object(mod, "_prompt_for_path", return_value=str(bad)):
        ok = mod.wizard("instagram", config_path=cfg, is_tty=True)

    assert ok is False
    # Config left clean — no half-saved state.
    if cfg.exists():
        raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
        assert not raw.get("instagram", {}).get("cookies_file")


def test_wizard_cancel_returns_false(tmp_path: Path):
    """Ctrl-C at the path prompt (questionary returns None) → wizard
    returns False without crashing and without partially-saving state."""
    from unittest.mock import patch
    from skills.youtube_transcribe.subscribes import cookies_onboarding as mod
    cfg = tmp_path / "config.toml"

    with patch.object(mod, "_prompt_for_path", return_value=None):
        ok = mod.wizard("instagram", config_path=cfg, is_tty=True)
    assert ok is False


def test_prompt_for_path_strips_backslash_escaped_spaces(tmp_path: Path):
    """macOS Terminal escapes spaces with backslash on drag-and-drop;
    helper should strip that so the path resolves correctly."""
    from unittest.mock import patch
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        _prompt_for_path,
    )

    # Simulate questionary returning an escaped path.
    with patch("questionary.path") as mock_qpath:
        mock_qpath.return_value.ask.return_value = (
            "/Users/me/My\\ Folder/cookies.txt"
        )
        result = _prompt_for_path("Test")
    assert result == "/Users/me/My Folder/cookies.txt"


def test_cookies_set_cmd_no_args_invokes_wizard(tmp_path: Path):
    """`subscribes cookies set` without args → triggers wizard in TTY."""
    from unittest.mock import patch
    from click.testing import CliRunner
    from skills.youtube_transcribe.transcribe import cli

    src = _make_cookies_file(tmp_path / "ig.txt")

    # Replace wizard with a stub that just verifies it got called.
    with patch(
        "skills.youtube_transcribe.subscribes.cookies_onboarding.wizard",
        return_value=True,
    ) as mock_wizard:
        runner = CliRunner()
        res = runner.invoke(cli, ["subscribes", "cookies", "set"])
    assert res.exit_code == 0
    mock_wizard.assert_called_once_with(None)
