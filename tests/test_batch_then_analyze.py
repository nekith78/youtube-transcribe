"""--then-analyze hook tests — direct + CLI plumbing."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from skills.youtube_transcribe.transcribe import cli, _run_then_analyze


def _make_fake_batch(tmp_path: Path) -> Path:
    batch = tmp_path / "batch_synth"
    batch.mkdir()
    (batch / "v.txt").write_text(
        "[00:00:00.000 --> 00:00:01.000] hi\n", encoding="utf-8")
    (batch / "manifest.json").write_text(json.dumps({
        "batch_name": "batch_synth", "created_at": "x",
        "stats": {"total": 1, "ok": 1, "failed": 0},
        "videos": [{
            "index": 1, "url": None, "video_id": None, "title": "T",
            "upload_date": None, "duration_sec": None, "channel": None,
            "language_detected": None,
            "files": {"txt": "v.txt"}, "status": "ok",
        }],
    }), encoding="utf-8")
    return batch


def test_run_then_analyze_writes_file(tmp_path: Path):
    """Direct call: _run_then_analyze produces analysis-*.md in batch."""
    batch = _make_fake_batch(tmp_path)

    captured = {}

    def fake_run(full_prompt, **kw):
        captured["prompt"] = full_prompt
        return "ANALYZED"

    with patch(
        "skills.youtube_transcribe.analyze.runner.run_analysis",
        side_effect=fake_run,
    ):
        _run_then_analyze(
            batch_folder=batch,
            prompt_inline="EXTRACT KEY IDEAS",
            prompt_file=None,
            backend="ollama",
        )

    assert "EXTRACT KEY IDEAS" in captured["prompt"]
    out = list(batch.glob("analysis-*.md"))
    assert len(out) == 1
    assert "ANALYZED" in out[0].read_text(encoding="utf-8")


def test_run_then_analyze_uses_prompt_file(tmp_path: Path):
    batch = _make_fake_batch(tmp_path)
    pf = tmp_path / "p.md"
    pf.write_text("FROM FILE", encoding="utf-8")

    captured = {}

    def fake_run(full_prompt, **kw):
        captured["prompt"] = full_prompt
        return "OK"

    with patch(
        "skills.youtube_transcribe.analyze.runner.run_analysis",
        side_effect=fake_run,
    ):
        _run_then_analyze(
            batch_folder=batch,
            prompt_inline=None,
            prompt_file=pf,
            backend="ollama",
        )

    assert "FROM FILE" in captured["prompt"]


def test_run_then_analyze_missing_key_exits_4(tmp_path: Path):
    batch = _make_fake_batch(tmp_path)
    with patch(
        "skills.youtube_transcribe.transcribe.get_api_key",
        return_value=None,
    ):
        try:
            _run_then_analyze(
                batch_folder=batch,
                prompt_inline="x",
                prompt_file=None,
                backend="gemini",
            )
            assert False, "should have exited"
        except SystemExit as e:
            assert e.code == 4


def test_run_then_analyze_empty_response_no_file(tmp_path: Path):
    batch = _make_fake_batch(tmp_path)
    with patch(
        "skills.youtube_transcribe.analyze.runner.run_analysis",
        return_value="",
    ):
        _run_then_analyze(
            batch_folder=batch,
            prompt_inline="x",
            prompt_file=None,
            backend="ollama",
        )
    assert list(batch.glob("analysis-*.md")) == []


def test_then_analyze_cli_requires_prompt(tmp_path: Path):
    """CLI plumbing: --then-analyze + no prompt → exit 2 without running batch."""
    runner = CliRunner()
    res = runner.invoke(cli, [
        "batch", "https://youtu.be/dQw4w9WgXcQ",
        "--then-analyze",
    ], catch_exceptions=False)
    assert res.exit_code == 2
    assert "--then-analyze" in res.output or "prompt" in res.output.lower()


# ── analyze backend fallback chain (v0.7) ───────────────────────────────


def test_select_analyze_backends_primary_first():
    """User's choice comes first; rest follow gemini→claude→openai→ollama."""
    from skills.youtube_transcribe.transcribe import _select_analyze_backends
    with patch(
        "skills.youtube_transcribe.transcribe.get_api_key",
        return_value="fake-key",
    ):
        chain = _select_analyze_backends("claude")
    assert chain[0] == "claude"
    # gemini/claude/openai/ollama in default order, deduped — claude already
    # consumed → next is gemini, then openai, then ollama.
    assert chain == ["claude", "gemini", "openai", "ollama"]


def test_select_analyze_backends_skips_missing_keys():
    """Backends without an API key are excluded (except ollama, no key needed)."""
    from skills.youtube_transcribe.transcribe import _select_analyze_backends

    def fake_key(name):
        return "fake-key" if name == "gemini" else None

    with patch(
        "skills.youtube_transcribe.transcribe.get_api_key",
        side_effect=fake_key,
    ):
        chain = _select_analyze_backends("gemini")
    # claude / openai dropped (no key), ollama kept (local, no key).
    assert chain == ["gemini", "ollama"]


def test_select_analyze_backends_primary_without_key_returns_empty():
    """Primary backend explicitly chosen but has no API key → empty chain.
    Caller exits 4 — we don't silently swap in a different backend the
    user didn't ask for."""
    from skills.youtube_transcribe.transcribe import _select_analyze_backends
    with patch(
        "skills.youtube_transcribe.transcribe.get_api_key",
        return_value=None,
    ):
        # primary=gemini without key → don't substitute, exit 4 is correct
        assert _select_analyze_backends("gemini") == []


def test_select_analyze_backends_ollama_primary_always_ok():
    """Ollama as primary never needs a key — chain non-empty even without
    any cloud key configured."""
    from skills.youtube_transcribe.transcribe import _select_analyze_backends
    with patch(
        "skills.youtube_transcribe.transcribe.get_api_key",
        return_value=None,
    ):
        chain = _select_analyze_backends("ollama")
    assert chain == ["ollama"]


def test_then_analyze_falls_back_when_primary_returns_empty(tmp_path: Path):
    """Primary backend returns '' (quota / 429) → next backend in chain runs."""
    batch = _make_fake_batch(tmp_path)

    calls: list[str] = []

    def fake_run(full_prompt, *, backend, **_kw):
        calls.append(backend)
        return "" if backend == "gemini" else "ANALYZED BY FALLBACK"

    with patch(
        "skills.youtube_transcribe.transcribe.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.youtube_transcribe.analyze.runner.run_analysis",
        side_effect=fake_run,
    ):
        _run_then_analyze(
            batch_folder=batch,
            prompt_inline="x", prompt_file=None,
            backend="gemini",
        )
    # gemini tried first, fell back to claude (next in default order).
    assert calls[0] == "gemini"
    assert len(calls) >= 2
    out = list(batch.glob("analysis-*.md"))
    assert len(out) == 1
    assert "ANALYZED BY FALLBACK" in out[0].read_text(encoding="utf-8")


def test_then_analyze_all_backends_empty_writes_no_file(tmp_path: Path):
    """Every backend in the chain returns '' → no analysis file, no crash."""
    batch = _make_fake_batch(tmp_path)
    with patch(
        "skills.youtube_transcribe.transcribe.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.youtube_transcribe.analyze.runner.run_analysis",
        return_value="",
    ):
        _run_then_analyze(
            batch_folder=batch,
            prompt_inline="x", prompt_file=None,
            backend="gemini",
        )
    assert list(batch.glob("analysis-*.md")) == []


def test_download_error_becomes_batch_failure_not_traceback(tmp_path: Path):
    """Pre-v0.8.1 bug: a DownloadError from yt-dlp propagated out of
    _run_batch_pipeline, killing the whole batch (and subscribes update).
    Common trigger: TikTok's anti-bot system returning a malformed
    response on one specific video while the rest succeed.

    Fix: _process_one catches DownloadError and converts to a BatchFailure
    with stage="download", so the loop continues through remaining videos.
    """
    from unittest.mock import MagicMock
    from skills.youtube_transcribe.transcribe import _run_batch_pipeline
    from skills.youtube_transcribe.utils.downloader import DownloadError

    def fake_run_pipeline(target, cfg, **kw):
        if "broken" in target.url:
            raise DownloadError("yt-dlp: Unexpected response")
        result = MagicMock()
        result.segments = [MagicMock(start=0, end=1, text="ok")]
        result.text = "ok"
        result.language_detected = "en"
        result.backend_name = "subtitles"
        result.duration_seconds = 1.0
        result.quality = None
        result.visual_segments = []
        return result

    targets = []
    for vid, url in [
        ("ok1", "https://www.tiktok.com/@u/video/ok1"),
        ("broken", "https://www.tiktok.com/@u/video/broken"),
        ("ok2", "https://www.tiktok.com/@u/video/ok2"),
    ]:
        t = MagicMock(
            url=url, video_id=vid, title=vid, upload_date=None,
            duration_sec=10, channel="@u", source="channel",
            source_language=None,
        )
        targets.append(t)

    from skills.youtube_transcribe.config import Config
    cfg = Config(
        default_backend="subtitles",
        output_dir=str(tmp_path),
        cookies_file="",
        keep_audio=False,
        timestamps=True,
        srt=True,
        language="auto",
    )
    opts = {
        "output_dir": str(tmp_path),
        "batch_name": "test-batch",
        "no_combined": False, "fail_fast": False,
    }

    with patch(
        "skills.youtube_transcribe.transcribe.run_pipeline",
        side_effect=fake_run_pipeline,
    ):
        batch_dir = _run_batch_pipeline(targets=targets, cfg=cfg, opts=opts)

    assert batch_dir is not None
    # The two healthy videos should have produced transcripts despite the
    # broken middle one crashing the downloader.
    txts = list((batch_dir / "videos").glob("*.txt"))
    assert len(txts) == 2
    # errors.log should mention the broken one with stage="download".
    errors_log = batch_dir / "errors.log"
    assert errors_log.exists()
    content = errors_log.read_text(encoding="utf-8")
    assert "broken" in content
