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


import json
from datetime import date, datetime
from skills.youtube_transcribe.utils.output_writer import (
    BatchMeta,
    BatchFailure,
    BatchVideoStatus,
    write_combined_md,
    write_manifest_json,
    write_errors_log,
)


def _make_meta() -> BatchMeta:
    return BatchMeta(
        batch_name="anthropicai-test",
        created_at=datetime(2026, 5, 9, 15, 30, 12),
        source_type="channel",
        source_url="https://youtube.com/@anthropicai",
        backend="whisper-local",
        backend_options={"whisper_model": "turbo"},
        language="auto",
    )


def _make_video_status(idx: int, ok: bool = True) -> BatchVideoStatus:
    return BatchVideoStatus(
        index=idx,
        url=f"https://youtu.be/aaa{idx}",
        video_id=f"aaa{idx}",
        title=f"Video {idx}",
        upload_date=date(2026, 4, 20),
        duration_sec=134,
        channel="@anthropicai",
        language_detected="en",
        text="Hello world. This is a test transcript.",
        files={"txt": f"videos/0{idx}_video-{idx}_aaa{idx}.txt",
               "srt": f"videos/0{idx}_video-{idx}_aaa{idx}.srt"},
        status="ok" if ok else "failed",
        error=None if ok else "stub",
    )


def test_write_combined_md_includes_yaml_frontmatter(tmp_path):
    meta = _make_meta()
    videos = [_make_video_status(1), _make_video_status(2)]
    path = write_combined_md(videos, meta, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "batch_name: anthropicai-test" in text
    assert "total: 2" in text
    assert "ok: 2" in text
    assert "## 1. Video 1" in text
    assert "## 2. Video 2" in text
    assert "Hello world." in text


def test_write_combined_md_renders_dashes_for_missing_metadata(tmp_path):
    meta = _make_meta()
    bad = _make_video_status(1)
    bad.upload_date = None
    bad.duration_sec = None
    path = write_combined_md([bad], meta, tmp_path)
    text = path.read_text(encoding="utf-8")
    # Both date and duration rendered as em-dash placeholder
    assert "| Date | — |" in text or "| Дата | — |" in text
    assert "—" in text


def test_write_manifest_json_schema(tmp_path):
    meta = _make_meta()
    videos = [_make_video_status(1)]
    failures = [BatchFailure(
        index=2,
        url="https://youtu.be/bad",
        stage="download",
        error_text="HTTP 403",
        hint="try --cookies-from-browser chrome",
    )]
    path = write_manifest_json(videos, failures, meta, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["batch_name"] == "anthropicai-test"
    assert data["stats"]["total"] == 2  # 1 ok + 1 failed
    assert data["stats"]["ok"] == 1
    assert data["stats"]["failed"] == 1
    assert data["videos"][0]["status"] == "ok"
    failed_entry = next(v for v in data["videos"] if v["status"] == "failed")
    assert failed_entry["error"] == "HTTP 403"


def test_write_errors_log_returns_none_when_no_failures(tmp_path):
    assert write_errors_log([], tmp_path) is None
    assert not (tmp_path / "errors.log").exists()


def test_write_errors_log_format(tmp_path):
    failures = [BatchFailure(
        index=7,
        url="https://youtu.be/CCC",
        stage="download",
        error_text="HTTP 403 — 'Sign in to confirm you're not a bot'",
        hint="try --cookies-from-browser chrome",
    )]
    path = write_errors_log(failures, tmp_path)
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "FAILED #7 https://youtu.be/CCC" in text
    assert "Stage: download" in text
    assert "Reason: HTTP 403" in text
    assert "Hint: try --cookies-from-browser chrome" in text
