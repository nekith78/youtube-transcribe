import os
import shutil
import subprocess
from pathlib import Path
import pytest


@pytest.mark.skipif(
    os.environ.get("RUN_E2E_SMOKE") != "1",
    reason="Set RUN_E2E_SMOKE=1 to run end-to-end smoke against YouTube",
)
def test_e2e_short_youtube(tmp_path: Path):
    if not shutil.which("yt-dlp"):
        pytest.skip("yt-dlp not on PATH")
    out = tmp_path / "out"
    r = subprocess.run(
        [
            "uv", "run", "youtube-transcribe", "transcribe",
            "https://www.youtube.com/watch?v=jNQXAC9IVRw",
            "--backend", "subtitles",
            "--language", "en",
            "--output-dir", str(out),
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert any(out.glob("*.txt"))
    assert any(out.glob("*.srt"))


@pytest.mark.skipif(
    os.environ.get("RUN_E2E_SMOKE") != "1",
    reason="Set RUN_E2E_SMOKE=1 to run end-to-end smoke against YouTube",
)
def test_e2e_batch_two_urls_via_subtitles(tmp_path: Path):
    if not shutil.which("yt-dlp"):
        pytest.skip("yt-dlp not on PATH")
    out = tmp_path / "out"
    r = subprocess.run(
        [
            "uv", "run", "youtube-transcribe", "batch",
            # same short public-domain video twice — dedup should keep one
            "https://www.youtube.com/watch?v=jNQXAC9IVRw",
            "https://www.youtube.com/watch?v=jNQXAC9IVRw",
            "--backend", "subtitles",
            "--language", "en",
            "--output-dir", str(out),
        ],
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, r.stderr
    batch_dirs = list(out.glob("batch_*"))
    assert len(batch_dirs) == 1
    bd = batch_dirs[0]
    assert (bd / "combined.md").exists()
    assert (bd / "manifest.json").exists()
    assert (bd / "videos").is_dir()
    # dedup → exactly 1 video in videos/
    txt_files = list((bd / "videos").glob("*.txt"))
    assert len(txt_files) == 1
    # combined.md has YAML front-matter
    head = (bd / "combined.md").read_text(encoding="utf-8")[:200]
    assert head.startswith("---\n")
    assert "total: 1" in head
