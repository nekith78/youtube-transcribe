"""Tests for `youtube-transcribe research` CLI."""
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from skills.youtube_transcribe.transcribe import cli


def test_research_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["research", "--help"])
    assert res.exit_code == 0
    for opt in ["--prompt", "--prompt-file", "--days", "--since", "--until",
                "--languages", "--limit", "--match", "--filter",
                "--in-subscribes", "--group", "--yes", "--no-analyze",
                "--analyze-backend", "--filter-backend",
                "--translate-backend", "--no-stdout"]:
        assert opt in res.output


def test_research_requires_query_or_in_subscribes():
    """No query and no --in-subscribes → exit 2."""
    runner = CliRunner()
    res = runner.invoke(cli, [
        "research",
        "--prompt", "test", "--analyze-backend", "ollama",
    ], catch_exceptions=False)
    assert res.exit_code == 2


def test_research_calls_pipeline(tmp_path: Path):
    with patch(
        "skills.youtube_transcribe.research.pipeline.run_research",
        return_value=tmp_path / "fake_batch",
    ) as mock_pipe:
        runner = CliRunner()
        res = runner.invoke(cli, [
            "research", "Claude features",
            "--days", "7",
            "--languages", "en",
            "--limit", "5",
            "--no-analyze",
            "--yes",
            "--backend", "subtitles",
            "--analyze-backend", "ollama",
        ], catch_exceptions=False)
    assert res.exit_code == 0
    mock_pipe.assert_called_once()
    kwargs = mock_pipe.call_args.kwargs
    assert kwargs["query"] == "Claude features"
    assert kwargs["days"] == 7
    assert kwargs["languages"] == ["en"]
    assert kwargs["limit"] == 5
    assert kwargs["no_analyze"] is True
    assert kwargs["yes"] is True


def test_research_mutex_prompt_and_prompt_file_when_analyze(tmp_path: Path):
    pf = tmp_path / "p.md"
    pf.write_text("x", encoding="utf-8")
    runner = CliRunner()
    res = runner.invoke(cli, [
        "research", "topic",
        "--prompt", "x", "--prompt-file", str(pf),
        "--backend", "subtitles",
    ], catch_exceptions=False)
    assert res.exit_code == 2


def test_research_languages_default_ru_en():
    with patch(
        "skills.youtube_transcribe.research.pipeline.run_research",
        return_value=None,
    ) as mock_pipe:
        runner = CliRunner()
        runner.invoke(cli, [
            "research", "topic", "--no-analyze", "--yes",
            "--backend", "subtitles",
        ], catch_exceptions=False)
    kwargs = mock_pipe.call_args.kwargs
    assert kwargs["languages"] == ["ru", "en"]


def test_research_days_default_30():
    with patch(
        "skills.youtube_transcribe.research.pipeline.run_research",
        return_value=None,
    ) as mock_pipe:
        runner = CliRunner()
        runner.invoke(cli, [
            "research", "topic", "--no-analyze", "--yes",
            "--backend", "subtitles",
        ], catch_exceptions=False)
    assert mock_pipe.call_args.kwargs["days"] == 30


def test_research_limit_default_20():
    with patch(
        "skills.youtube_transcribe.research.pipeline.run_research",
        return_value=None,
    ) as mock_pipe:
        runner = CliRunner()
        runner.invoke(cli, [
            "research", "topic", "--no-analyze", "--yes",
            "--backend", "subtitles",
        ], catch_exceptions=False)
    assert mock_pipe.call_args.kwargs["limit"] == 20


def test_research_in_subscribes_calls_pipeline_with_flag(tmp_path: Path):
    with patch(
        "skills.youtube_transcribe.research.pipeline.run_research",
        return_value=None,
    ) as mock_pipe:
        runner = CliRunner()
        res = runner.invoke(cli, [
            "research", "Claude features",
            "--in-subscribes",
            "--group", "ai-research",
            "--no-analyze", "--yes",
            "--backend", "subtitles",
        ], catch_exceptions=False)
    assert res.exit_code == 0
    kwargs = mock_pipe.call_args.kwargs
    assert kwargs["in_subscribes"] is True
    assert kwargs["group"] == "ai-research"


def test_research_in_subscribes_without_query_works(tmp_path: Path):
    with patch(
        "skills.youtube_transcribe.research.pipeline.run_research",
        return_value=None,
    ) as mock_pipe:
        runner = CliRunner()
        res = runner.invoke(cli, [
            "research",
            "--in-subscribes",
            "--no-analyze", "--yes",
            "--backend", "subtitles",
        ], catch_exceptions=False)
    assert res.exit_code == 0
    kwargs = mock_pipe.call_args.kwargs
    assert kwargs["query"] is None
    assert kwargs["in_subscribes"] is True
