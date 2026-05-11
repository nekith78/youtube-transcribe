"""Tests for `youtube-transcribe analyze` CLI."""
import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from skills.youtube_transcribe.transcribe import cli


def test_analyze_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["analyze", "--help"])
    assert res.exit_code == 0
    assert "--prompt" in res.output
    assert "--prompt-file" in res.output
    assert "--backend" in res.output
    assert "--latest" in res.output
    assert "--all" in res.output
    assert "--select" in res.output


def test_analyze_requires_prompt(tmp_path: Path):
    f = tmp_path / "t.txt"
    f.write_text("[00:00:00.000 --> 00:00:01.000] hi\n", encoding="utf-8")
    runner = CliRunner()
    res = runner.invoke(cli, ["analyze", str(f), "--backend", "ollama"],
                        catch_exceptions=False)
    assert res.exit_code == 2
    assert "prompt" in res.output.lower()


def test_analyze_prompt_and_prompt_file_mutex(tmp_path: Path):
    f = tmp_path / "t.txt"
    f.write_text("hi\n", encoding="utf-8")
    pf = tmp_path / "p.md"
    pf.write_text("PROMPT", encoding="utf-8")
    runner = CliRunner()
    res = runner.invoke(cli, [
        "analyze", str(f),
        "--prompt", "x", "--prompt-file", str(pf),
        "--backend", "ollama",
    ], catch_exceptions=False)
    assert res.exit_code == 2


def test_analyze_single_file_ollama(tmp_path: Path):
    f = tmp_path / "t.txt"
    f.write_text("[00:00:00.000 --> 00:00:01.000] hello\n", encoding="utf-8")

    captured = {}

    def fake_run(full_prompt, **kw):
        captured["prompt"] = full_prompt
        captured.update(kw)
        return "## Result\nOK"

    with patch(
        "skills.youtube_transcribe.analyze.runner.run_analysis",
        side_effect=fake_run,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "analyze", str(f),
            "--prompt", "summarize",
            "--backend", "ollama",
        ], catch_exceptions=False)

    assert res.exit_code == 0
    assert captured["backend"] == "ollama"
    assert captured["api_key"] is None
    assert "summarize" in captured["prompt"]
    assert "hello" in captured["prompt"]
    # File written next to source
    out = list(tmp_path.glob("t.analysis-*.md"))
    assert len(out) == 1
    assert "## Result" in out[0].read_text(encoding="utf-8")
    # stdout dump
    assert "## Result" in res.output


def test_analyze_missing_key_exit_4(tmp_path: Path):
    f = tmp_path / "t.txt"
    f.write_text("[00:00:00.000 --> 00:00:01.000] hi\n", encoding="utf-8")
    with patch(
        "skills.youtube_transcribe.transcribe.get_api_key",
        return_value=None,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "analyze", str(f),
            "--prompt", "x", "--backend", "gemini",
        ], catch_exceptions=False)
    assert res.exit_code == 4
    assert "gemini" in res.output.lower() or "key" in res.output.lower()


def test_analyze_missing_source_exit_3(tmp_path: Path):
    runner = CliRunner()
    res = runner.invoke(cli, [
        "analyze", str(tmp_path / "nope.txt"),
        "--prompt", "x", "--backend", "ollama",
    ], catch_exceptions=False)
    assert res.exit_code == 3


def test_analyze_empty_llm_exit_4(tmp_path: Path):
    f = tmp_path / "t.txt"
    f.write_text("[00:00:00.000 --> 00:00:01.000] hi\n", encoding="utf-8")
    with patch(
        "skills.youtube_transcribe.analyze.runner.run_analysis",
        return_value="",
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "analyze", str(f),
            "--prompt", "x", "--backend", "ollama",
        ], catch_exceptions=False)
    assert res.exit_code == 4
    assert "llm" in res.output.lower() or "ответ" in res.output.lower()


def test_analyze_prompt_file_read(tmp_path: Path):
    f = tmp_path / "t.txt"
    f.write_text("[00:00:00.000 --> 00:00:01.000] hi\n", encoding="utf-8")
    pf = tmp_path / "p.md"
    pf.write_text("PROMPT FROM FILE", encoding="utf-8")

    captured = {}

    def fake_run(full_prompt, **kw):
        captured["prompt"] = full_prompt
        return "OK"

    with patch(
        "skills.youtube_transcribe.analyze.runner.run_analysis",
        side_effect=fake_run,
    ):
        runner = CliRunner()
        res = runner.invoke(cli, [
            "analyze", str(f),
            "--prompt-file", str(pf),
            "--backend", "ollama",
        ], catch_exceptions=False)
    assert res.exit_code == 0
    assert "PROMPT FROM FILE" in captured["prompt"]
