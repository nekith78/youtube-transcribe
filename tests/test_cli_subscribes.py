"""Tests for `youtube-transcribe subscribes` CLI."""
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from skills.youtube_transcribe.transcribe import cli


def _resolved(url, channel_id="UC_abc"):
    from skills.youtube_transcribe.subscribes.channel_resolver import (
        ResolvedChannel,
    )
    return ResolvedChannel(
        url=url.rstrip("/"), handle="@A", channel_id=channel_id, title="A",
    )


def test_subscribes_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["subscribes", "--help"])
    assert res.exit_code == 0
    for sub in ["add", "remove", "list", "edit", "update", "schedule"]:
        assert sub in res.output


def test_add_persists_channel(tmp_path: Path):
    sub_path = tmp_path / "subscribes.toml"
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ), patch(
        "skills.youtube_transcribe.subscribes.cli.resolve_channel",
        return_value=_resolved("https://www.youtube.com/@A"),
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "subscribes", "add", "https://www.youtube.com/@A",
            "--group", "ai-research",
        ], catch_exceptions=False)
    assert res.exit_code == 0
    text = sub_path.read_text()
    assert "@A" in text
    assert "ai-research" in text


def test_add_resolution_failure_exits_3(tmp_path: Path):
    sub_path = tmp_path / "subscribes.toml"
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ), patch(
        "skills.youtube_transcribe.subscribes.cli.resolve_channel",
        side_effect=ValueError("not a channel"),
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "subscribes", "add", "https://www.youtube.com/notchannel",
        ], catch_exceptions=False)
    assert res.exit_code == 3


def test_list_shows_channels(tmp_path: Path):
    from skills.youtube_transcribe.subscribes.store import (
        Channel, add_channel,
    )
    sub_path = tmp_path / "subscribes.toml"
    add_channel(sub_path, Channel(
        url="u1", handle="@A", channel_id="UC_a", group="ai",
        added="2026-05-12",
    ))
    add_channel(sub_path, Channel(
        url="u2", handle="@B", channel_id="UC_b", group=None,
        added="2026-05-12",
    ))
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["subscribes", "list"])
    assert res.exit_code == 0
    assert "@A" in res.output
    assert "@B" in res.output


def test_list_filter_by_group(tmp_path: Path):
    from skills.youtube_transcribe.subscribes.store import (
        Channel, add_channel,
    )
    sub_path = tmp_path / "subscribes.toml"
    add_channel(sub_path, Channel(
        url="u1", handle="@A", channel_id="UC_a", group="ai", added="x",
    ))
    add_channel(sub_path, Channel(
        url="u2", handle="@B", channel_id="UC_b", group="philosophy", added="x",
    ))
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["subscribes", "list", "--group", "ai"])
    assert res.exit_code == 0
    assert "@A" in res.output
    assert "@B" not in res.output


def test_remove_existing(tmp_path: Path):
    from skills.youtube_transcribe.subscribes.store import (
        Channel, add_channel,
    )
    sub_path = tmp_path / "subscribes.toml"
    add_channel(sub_path, Channel(
        url="u", handle="@A", channel_id="UC_a", group=None, added="x",
    ))
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["subscribes", "remove", "@A"])
    assert res.exit_code == 0
    assert "@A" not in sub_path.read_text()


def test_remove_missing_exits_3(tmp_path: Path):
    sub_path = tmp_path / "subscribes.toml"
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["subscribes", "remove", "@MISSING"])
    assert res.exit_code == 3


def test_edit_uses_env_editor(tmp_path: Path, monkeypatch):
    """`subscribes edit` invokes $EDITOR on the TOML file."""
    sub_path = tmp_path / "subscribes.toml"
    sub_path.write_text("# empty\n", encoding="utf-8")
    monkeypatch.setenv("EDITOR", "true")  # Unix /usr/bin/true exits 0
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["subscribes", "edit"])
    assert res.exit_code == 0


def test_update_delegates_to_pipeline(tmp_path: Path):
    sub_path = tmp_path / "subscribes.toml"
    sub_path.write_text("# empty\n", encoding="utf-8")
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.run_subscribes_update",
        return_value=tmp_path / "fake",
    ) as mock_pipe:
        runner = CliRunner()
        res = runner.invoke(cli, [
            "subscribes", "update",
            "--days", "7",
            "--no-analyze",
            "--yes",
            "--backend", "subtitles",
        ], catch_exceptions=False)
    assert res.exit_code == 0
    kwargs = mock_pipe.call_args.kwargs
    assert kwargs["days"] == 7
    assert kwargs["no_analyze"] is True
    assert kwargs["yes"] is True
    # --backend subtitles must land in batch_opts under the canonical "backend"
    # key so _run_batch_pipeline.opts.get("backend") sees it. Bug v0.7: the
    # dest was renamed to "backend_opt", silently routing transcribes to
    # cfg.default_backend.
    assert kwargs["batch_opts"].get("backend") == "subtitles"


def test_update_backend_and_language_use_canonical_keys(tmp_path: Path):
    """Regression: --backend / --language reach the pipeline as bare keys."""
    sub_path = tmp_path / "subscribes.toml"
    sub_path.write_text("# empty\n", encoding="utf-8")
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.run_subscribes_update",
        return_value=None,
    ) as mock_pipe:
        runner = CliRunner()
        runner.invoke(cli, [
            "subscribes", "update",
            "--days", "7",
            "--no-analyze", "--yes",
            "--backend", "whisper-local",
            "--language", "ru",
        ], catch_exceptions=False)
    opts = mock_pipe.call_args.kwargs["batch_opts"]
    assert opts.get("backend") == "whisper-local"
    assert opts.get("language") == "ru"
    assert "backend_opt" not in opts
    assert "language_opt" not in opts


def test_update_subscribes_error_exits_2(tmp_path: Path):
    from skills.youtube_transcribe.subscribes.pipeline import SubscribesError
    sub_path = tmp_path / "subscribes.toml"
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.run_subscribes_update",
        side_effect=SubscribesError("--days required for: @X"),
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "subscribes", "update", "--no-analyze", "--yes",
            "--backend", "subtitles",
        ], catch_exceptions=False)
    assert res.exit_code == 2


def test_update_analyze_requires_prompt(tmp_path: Path):
    sub_path = tmp_path / "subscribes.toml"
    sub_path.write_text("# empty\n", encoding="utf-8")
    with patch(
        "skills.youtube_transcribe.subscribes.cli.SUBSCRIBES_PATH",
        new=sub_path,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "subscribes", "update",
            "--days", "7",
            "--backend", "subtitles",
        ], catch_exceptions=False)
    assert res.exit_code == 2


# Schedule tests:


def test_schedule_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["subscribes", "schedule", "--help"])
    assert res.exit_code == 0
    assert "install" in res.output
    assert "uninstall" in res.output


def test_schedule_install_prints_launchd_on_macos():
    with patch(
        "skills.youtube_transcribe.subscribes.cli.detect_platform",
        return_value="launchd",
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "subscribes", "schedule", "install",
            "--every", "1h",
            "--prompt", "summarize",
        ], catch_exceptions=False)
    assert res.exit_code == 0
    assert "<plist" in res.output


def test_schedule_install_prints_cron_on_linux():
    with patch(
        "skills.youtube_transcribe.subscribes.cli.detect_platform",
        return_value="cron",
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "subscribes", "schedule", "install", "--every", "1h",
            "--prompt", "x",
        ], catch_exceptions=False)
    assert res.exit_code == 0
    assert "crontab" in res.output.lower() or "0 *" in res.output


def test_schedule_install_prints_systemd():
    with patch(
        "skills.youtube_transcribe.subscribes.cli.detect_platform",
        return_value="systemd",
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "subscribes", "schedule", "install", "--every", "1h",
            "--prompt", "x",
        ], catch_exceptions=False)
    assert res.exit_code == 0
    assert "[Timer]" in res.output
    assert "systemctl" in res.output.lower()


def test_schedule_install_prints_taskscheduler_on_windows():
    with patch(
        "skills.youtube_transcribe.subscribes.cli.detect_platform",
        return_value="taskscheduler",
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "subscribes", "schedule", "install", "--every", "1h",
            "--prompt", "x",
        ], catch_exceptions=False)
    assert res.exit_code == 0
    assert "<Task" in res.output
    assert "schtasks" in res.output.lower()


def test_schedule_install_invalid_interval():
    runner = CliRunner()
    res = runner.invoke(cli, [
        "subscribes", "schedule", "install",
        "--every", "bogus", "--prompt", "x",
    ], catch_exceptions=False)
    assert res.exit_code == 2


def test_schedule_uninstall_prints_instructions():
    runner = CliRunner()
    res = runner.invoke(cli, [
        "subscribes", "schedule", "uninstall",
    ], catch_exceptions=False)
    assert res.exit_code == 0
    out = res.output.lower()
    assert "launchctl" in out or "crontab" in out or "schtasks" in out
