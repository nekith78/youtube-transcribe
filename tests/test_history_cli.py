"""Tests for `youtube-transcribe history` CLI."""
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from skills.youtube_transcribe.transcribe import cli


def _make_history(tmp_path: Path):
    """Create a synthetic history.toml with 3 runs."""
    from skills.youtube_transcribe.history.store import RunEntry, append_run
    p = tmp_path / "history.toml"
    for i, t in enumerate(("research", "subscribes", "research"), start=1):
        append_run(p, RunEntry(
            id=f"run_{i}", type=t,
            timestamp=f"2026-05-1{i}T14:00:00Z",
            query=f"q{i}" if t == "research" else None,
            group=None, output=f"/tmp/o{i}",
            videos_found=i * 2,
            analyze_backend="gemini",
            analyze_prompt_preview="prompt preview",
        ))
    return p


def test_history_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["history", "--help"])
    assert res.exit_code == 0
    assert "list" in res.output
    assert "show" in res.output


def test_history_list(tmp_path: Path):
    p = _make_history(tmp_path)
    with patch(
        "skills.youtube_transcribe.history.cli.HISTORY_PATH",
        new=p,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["history", "list"])
    assert res.exit_code == 0
    # Either id or query shows up
    assert "run_1" in res.output or "q1" in res.output
    assert "run_2" in res.output or "subscribes" in res.output.lower()


def test_history_list_limit(tmp_path: Path):
    p = _make_history(tmp_path)
    with patch(
        "skills.youtube_transcribe.history.cli.HISTORY_PATH",
        new=p,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["history", "list", "--last", "1"])
    assert res.exit_code == 0
    # Only one entry shown
    occurrences = sum(res.output.count(f"run_{i}") for i in (1, 2, 3))
    assert occurrences == 1


def test_history_list_filter_by_type(tmp_path: Path):
    p = _make_history(tmp_path)
    with patch(
        "skills.youtube_transcribe.history.cli.HISTORY_PATH",
        new=p,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["history", "list", "--type", "research"])
    assert res.exit_code == 0
    research_count = sum(res.output.count(f"run_{i}") for i in (1, 3))
    assert research_count >= 2 or "q1" in res.output


def test_history_show_by_id(tmp_path: Path):
    p = _make_history(tmp_path)
    with patch(
        "skills.youtube_transcribe.history.cli.HISTORY_PATH",
        new=p,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["history", "show", "run_2"])
    assert res.exit_code == 0
    assert "run_2" in res.output
    assert "subscribes" in res.output.lower()
    assert "/tmp/o2" in res.output


def test_history_show_missing_id(tmp_path: Path):
    p = _make_history(tmp_path)
    with patch(
        "skills.youtube_transcribe.history.cli.HISTORY_PATH",
        new=p,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["history", "show", "missing"])
    assert res.exit_code != 0
    assert "not found" in res.output.lower()


def test_history_list_empty(tmp_path: Path):
    """No history.toml yet → friendly empty output."""
    p = tmp_path / "empty.toml"
    with patch(
        "skills.youtube_transcribe.history.cli.HISTORY_PATH",
        new=p,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, ["history", "list"])
    assert res.exit_code == 0
    assert "пуст" in res.output.lower() or "empty" in res.output.lower() or "no runs" in res.output.lower()
