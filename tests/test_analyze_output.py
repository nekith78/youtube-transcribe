"""Tests for analyze.output_writer — analysis-*.md writer + --append-to."""
from datetime import datetime
from pathlib import Path

from skills.youtube_transcribe.analyze.output_writer import (
    analysis_filename,
    write_analysis,
    append_analysis,
)
from skills.youtube_transcribe.analyze.source_resolver import VideoSource


def _src(title: str) -> VideoSource:
    return VideoSource(transcript_path=Path("/tmp") / f"{title}.txt", title=title)


def test_filename_pattern():
    t = datetime(2026, 5, 11, 14, 42)
    assert analysis_filename(t) == "analysis-2026-05-11-1442.md"


def test_write_new_file(tmp_path: Path):
    out = write_analysis(
        out_path=tmp_path / "analysis-2026-05-11-1442.md",
        body="HELLO WORLD",
        user_prompt="What was discussed?",
        backend_label="gemini (gemini-2.5-flash)",
        videos=[_src("V1"), _src("V2")],
        total_videos=5,
        now=datetime(2026, 5, 11, 14, 42),
    )
    txt = out.read_text(encoding="utf-8")
    assert txt.startswith("# Analysis — 2026-05-11 14:42")
    assert "gemini (gemini-2.5-flash)" in txt
    assert "**Videos:** 2 of 5" in txt
    assert "- V1" in txt
    assert "- V2" in txt
    assert "What was discussed?" in txt
    assert "HELLO WORLD" in txt


def test_write_truncates_long_prompt_quote(tmp_path: Path):
    long = "x" * 1000
    out = write_analysis(
        out_path=tmp_path / "a.md",
        body="B",
        user_prompt=long,
        backend_label="gemini",
        videos=[_src("V")],
        total_videos=1,
        now=datetime(2026, 5, 11, 14, 42),
    )
    txt = out.read_text(encoding="utf-8")
    # Quote section should not include the entire 1000-char string.
    assert "..." in txt
    assert "x" * 1000 not in txt


def test_write_collision_appends_suffix(tmp_path: Path):
    target = tmp_path / "analysis-2026-05-11-1442.md"
    target.write_text("existing", encoding="utf-8")
    out = write_analysis(
        out_path=target,
        body="NEW",
        user_prompt="P",
        backend_label="gemini",
        videos=[_src("V")],
        total_videos=1,
        now=datetime(2026, 5, 11, 14, 42),
    )
    assert out.name == "analysis-2026-05-11-1442-2.md"
    assert out.read_text(encoding="utf-8").endswith("NEW\n") or "NEW" in out.read_text("utf-8")


def test_append_creates_new_file_with_header(tmp_path: Path):
    target = tmp_path / "combined.md"
    out = append_analysis(
        target=target,
        body="FIRST",
        user_prompt="P",
        backend_label="gemini",
        videos=[_src("V")],
        total_videos=1,
        now=datetime(2026, 5, 11, 14, 42),
    )
    txt = out.read_text(encoding="utf-8")
    assert txt.startswith("# Combined analyses")
    assert "## Analysis — 2026-05-11 14:42" in txt
    assert "FIRST" in txt


def test_append_to_existing_file(tmp_path: Path):
    target = tmp_path / "combined.md"
    target.write_text(
        "# Combined analyses\n\n## Analysis — 2026-05-10 10:00\n\nOLD\n",
        encoding="utf-8",
    )
    append_analysis(
        target=target,
        body="NEW",
        user_prompt="P",
        backend_label="gemini",
        videos=[_src("V")],
        total_videos=1,
        now=datetime(2026, 5, 11, 14, 42),
    )
    txt = target.read_text(encoding="utf-8")
    assert txt.count("## Analysis — ") == 2
    assert "OLD" in txt
    assert "NEW" in txt
