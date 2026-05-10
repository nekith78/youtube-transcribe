"""Tests for v0.3 channel filter CLI flags wiring."""
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from skills.youtube_transcribe.transcribe import cli


def test_batch_help_shows_v03_filters():
    runner = CliRunner()
    res = runner.invoke(cli, ["batch", "--help"])
    assert res.exit_code == 0
    assert "--since" in res.output
    assert "--until" in res.output
    assert "--min-duration" in res.output
    assert "--max-duration" in res.output
    assert "--no-shorts" in res.output


def test_invalid_since_format_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "skills.youtube_transcribe.transcribe.CONFIG_PATH",
        tmp_path / "config.toml",
    )
    (tmp_path / "config.toml").write_text(
        'default_preset = "smart"\n', encoding="utf-8"
    )
    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["batch", "https://youtu.be/x", "--since", "not-a-date"],
        catch_exceptions=False,
    )
    assert res.exit_code != 0
    assert "yyyy-mm-dd" in res.output.lower() or "since" in res.output.lower()


def test_filters_passed_to_resolver(tmp_path, monkeypatch):
    """When --since 2026-01-01 --no-shorts are passed, resolve() should
    receive a ResolverFilters with matching values."""
    captured_filters = {}

    def fake_resolve(inputs, from_file, filters):
        captured_filters["filters"] = filters
        return [], []

    monkeypatch.setattr(
        "skills.youtube_transcribe.transcribe.resolve",
        fake_resolve,
    )
    monkeypatch.setattr(
        "skills.youtube_transcribe.transcribe.CONFIG_PATH",
        tmp_path / "config.toml",
    )
    (tmp_path / "config.toml").write_text(
        'default_preset = "smart"\n', encoding="utf-8"
    )

    runner = CliRunner()
    runner.invoke(
        cli,
        ["batch", "https://youtu.be/x",
         "--since", "2026-01-01",
         "--until", "2026-12-31",
         "--min-duration", "120",
         "--max-duration", "3600",
         "--no-shorts",
         "--output-dir", str(tmp_path / "out")],
        catch_exceptions=False,
    )

    f = captured_filters.get("filters")
    assert f is not None
    assert f.since.isoformat() == "2026-01-01"
    assert f.until.isoformat() == "2026-12-31"
    assert f.min_duration_sec == 120
    assert f.max_duration_sec == 3600
    assert f.include_shorts is False


def test_default_filters_are_permissive(tmp_path, monkeypatch):
    """Without flags, ResolverFilters should pass everything (limit only)."""
    captured = {}

    def fake_resolve(inputs, from_file, filters):
        captured["filters"] = filters
        return [], []

    monkeypatch.setattr(
        "skills.youtube_transcribe.transcribe.resolve",
        fake_resolve,
    )
    monkeypatch.setattr(
        "skills.youtube_transcribe.transcribe.CONFIG_PATH",
        tmp_path / "config.toml",
    )
    (tmp_path / "config.toml").write_text(
        'default_preset = "smart"\n', encoding="utf-8"
    )

    runner = CliRunner()
    runner.invoke(
        cli,
        ["batch", "https://youtu.be/x", "--output-dir", str(tmp_path / "out")],
        catch_exceptions=False,
    )

    f = captured["filters"]
    assert f.since is None
    assert f.until is None
    assert f.min_duration_sec is None
    assert f.max_duration_sec is None
    assert f.include_shorts is True
