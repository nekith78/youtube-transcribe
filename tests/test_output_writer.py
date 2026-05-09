from pathlib import Path
from skills.youtube_transcribe.utils.output_writer import (
    Segment,
    write_txt_with_timestamps,
    write_txt_plain,
    write_srt,
    format_timestamp_srt,
    sanitize_filename,
)


def make_segments():
    return [
        Segment(start=0.0, end=2.5, text="Hello world."),
        Segment(start=2.5, end=5.0, text="Second segment."),
        Segment(start=8.0, end=10.0, text="After 3 second pause."),
    ]


def test_format_timestamp_srt_zero():
    assert format_timestamp_srt(0.0) == "00:00:00,000"


def test_format_timestamp_srt_with_ms():
    assert format_timestamp_srt(3725.123) == "01:02:05,123"


def test_write_txt_with_timestamps(tmp_path: Path):
    segs = make_segments()
    path = tmp_path / "out.txt"
    write_txt_with_timestamps(segs, path)
    text = path.read_text(encoding="utf-8")
    assert "[00:00:00.000 --> 00:00:02.500] Hello world." in text
    assert "[00:00:02.500 --> 00:00:05.000] Second segment." in text


def test_write_txt_plain_paragraphs_after_long_pause(tmp_path: Path):
    segs = make_segments()
    path = tmp_path / "out.txt"
    write_txt_plain(segs, path)
    text = path.read_text(encoding="utf-8")
    # 3-sec pause between seg 2 and seg 3 should split paragraph
    assert "\n\n" in text
    assert text.count("\n\n") >= 1


def test_write_srt_format(tmp_path: Path):
    segs = make_segments()
    path = tmp_path / "out.srt"
    write_srt(segs, path)
    text = path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:02,500"
    assert lines[2] == "Hello world."
    assert "" in lines  # blank between blocks


def test_sanitize_filename_strips_special_chars():
    assert sanitize_filename("Hello, World! [Official] / 2026?") == "Hello_World_Official_2026"


def test_sanitize_filename_unicode_ok():
    assert sanitize_filename("Привет мир") == "Привет_мир"
