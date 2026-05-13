"""Tests for subscribes.cookies_onboarding — IG/TikTok cookies prompt."""
from pathlib import Path
from unittest.mock import patch

import tomllib


def _read_cookies(p: Path, platform: str) -> str | None:
    if not p.exists():
        return None
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    return raw.get(platform, {}).get("cookies_browser") or None


def test_youtube_short_circuits_to_empty(tmp_path: Path):
    """YouTube channels use public RSS — no cookies needed, no prompt."""
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        resolve_cookies_browser,
    )
    cfg = tmp_path / "config.toml"

    with patch("click.prompt", side_effect=AssertionError("must not prompt")):
        result = resolve_cookies_browser(
            "youtube", config_path=cfg, is_tty=True,
        )
    assert result == ""


def test_saved_preference_short_circuits(tmp_path: Path):
    """Once user picks a browser, no more prompts."""
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        resolve_cookies_browser,
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'default_preset = "smart"\n\n'
        '[instagram]\ncookies_browser = "firefox"\n',
        encoding="utf-8",
    )
    with patch("click.prompt", side_effect=AssertionError("must not prompt")):
        result = resolve_cookies_browser(
            "instagram", config_path=cfg, is_tty=True,
        )
    assert result == "firefox"


def test_non_tty_returns_empty_no_prompt(tmp_path: Path):
    """Non-TTY (Claude Code subprocess, CI) → silent anon, no prompt."""
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        resolve_cookies_browser,
    )
    cfg = tmp_path / "config.toml"
    with patch("click.prompt", side_effect=AssertionError("must not prompt")):
        result = resolve_cookies_browser(
            "instagram", config_path=cfg, is_tty=False,
        )
    assert result == ""
    # Config left untouched — no half-baked persistence.
    assert not cfg.exists()


def test_tty_prompt_chrome_saves_and_returns(tmp_path: Path):
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        resolve_cookies_browser,
    )
    cfg = tmp_path / "config.toml"

    with patch("click.prompt", return_value="1"):
        result = resolve_cookies_browser(
            "instagram", config_path=cfg, is_tty=True,
        )
    assert result == "chrome"
    assert _read_cookies(cfg, "instagram") == "chrome"


def test_tty_prompt_none_persists_empty_string(tmp_path: Path):
    """Picking 'none' (5) returns "" and persists "" — so the next run
    treats this as a deliberate anonymous choice, not a pending prompt."""
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        resolve_cookies_browser,
    )
    cfg = tmp_path / "config.toml"

    with patch("click.prompt", return_value="5"):
        result = resolve_cookies_browser(
            "tiktok", config_path=cfg, is_tty=True,
        )
    assert result == ""
    # File exists, value persisted as empty string (intentional).
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert raw["tiktok"]["cookies_browser"] == ""


def test_each_browser_choice_maps_correctly(tmp_path: Path):
    from skills.youtube_transcribe.subscribes.cookies_onboarding import (
        resolve_cookies_browser,
    )
    table = {"1": "chrome", "2": "firefox", "3": "edge", "4": "safari"}
    for num, expected in table.items():
        cfg = tmp_path / f"cfg-{num}.toml"
        with patch("click.prompt", return_value=num):
            result = resolve_cookies_browser(
                "instagram", config_path=cfg, is_tty=True,
            )
        assert result == expected, f"choice {num} → expected {expected}"
