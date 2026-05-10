"""Test that --with-visuals actually triggers visual mode wiring (with mocks)."""
from pathlib import Path
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from skills.youtube_transcribe.transcribe import cli


def test_with_visuals_triggers_download_video(tmp_path, monkeypatch):
    """Verify that --with-visuals on a URL kicks off download_video."""
    # Mock the entire pipeline to avoid real transcription
    fake_segment = MagicMock(start=0.0, end=5.0, text="hello")
    fake_result = MagicMock()
    fake_result.segments = [fake_segment]
    fake_result.text = "hello"
    fake_result.language_detected = "en"
    fake_result.backend_name = "subtitles_auto"
    fake_result.duration_seconds = 5.0
    fake_result.quality = None
    fake_result.visual_segments = []

    fake_video_path = tmp_path / "video_abc.mp4"
    fake_video_path.write_bytes(b"fake mp4")

    download_called = {"v": False}

    def fake_download_video(url, out_dir, **kw):
        download_called["v"] = True
        # Mimic real path return
        f = out_dir / "video_abc.mp4"
        f.write_bytes(b"fake")
        return f

    runner = CliRunner()
    monkeypatch.setattr(
        "skills.youtube_transcribe.transcribe.run_pipeline",
        lambda *a, **kw: fake_result,
    )
    monkeypatch.setattr(
        "skills.youtube_transcribe.utils.downloader.download_video",
        fake_download_video,
    )
    monkeypatch.setattr(
        "skills.youtube_transcribe.config.get_api_key",
        lambda backend, env_path=None: "fake_key" if backend == "gemini" else None,
    )
    # apply_v02_stages should be called with non-None video_path.
    # It's imported locally inside transcribe_cmd, so patch at the source module.
    apply_call_args = {}

    def fake_apply(**kwargs):
        apply_call_args.update(kwargs)
        return kwargs["result"]

    monkeypatch.setattr(
        "skills.youtube_transcribe.pipeline_v02.apply_v02_stages",
        fake_apply,
    )

    # Avoid wizard (config exists check)
    monkeypatch.setattr(
        "skills.youtube_transcribe.transcribe.CONFIG_PATH",
        tmp_path / "config.toml",
    )
    (tmp_path / "config.toml").write_text("default_preset = \"smart\"\n", encoding="utf-8")

    res = runner.invoke(
        cli,
        ["transcribe", "https://youtu.be/test123", "--with-visuals",
         "--output-dir", str(tmp_path)],
        catch_exceptions=False,
    )

    # download_video should have been called for URL + visual mode
    assert download_called["v"], f"download_video NOT called. Output:\n{res.output}"
    # apply_v02_stages should have video_path set (non-None)
    assert apply_call_args.get("video_path") is not None, \
        f"video_path was None. Output:\n{res.output}"
