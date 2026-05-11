"""Tests for analyze.source_resolver — path/batch/--latest → VideoSource list."""
import json
import time
from pathlib import Path

import pytest

from skills.youtube_transcribe.analyze.source_resolver import (
    VideoSource,
    resolve_source,
    pick_latest_batch,
)


def _write_manifest(folder: Path, videos: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(
        json.dumps({
            "batch_name": folder.name,
            "created_at": "2026-05-11T14:42:00",
            "stats": {"total": len(videos), "ok": len(videos), "failed": 0},
            "videos": videos,
        }),
        encoding="utf-8",
    )


def test_single_txt_file(tmp_path: Path):
    f = tmp_path / "video.txt"
    f.write_text("[00:00:00.000 --> 00:00:01.000] hi\n", encoding="utf-8")
    out = resolve_source(f, outputs_dir=tmp_path, latest=False)
    assert len(out) == 1
    assert out[0].transcript_path == f
    assert out[0].title is None


def test_single_json_file(tmp_path: Path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"segments": [{"start": 0, "end": 1, "text": "hi"}]}),
                 encoding="utf-8")
    out = resolve_source(f, outputs_dir=tmp_path, latest=False)
    assert len(out) == 1
    assert out[0].transcript_path == f


def test_batch_folder_with_manifest(tmp_path: Path):
    batch = tmp_path / "batch_001"
    (batch / "vid.txt").parent.mkdir(parents=True, exist_ok=True)
    (batch / "vid.txt").write_text("[00:00:00.000 --> 00:00:01.000] hi\n",
                                   encoding="utf-8")
    _write_manifest(batch, [{
        "index": 1, "url": "https://youtu.be/x", "video_id": "x",
        "title": "Hello world", "upload_date": "2026-05-09",
        "duration_sec": 222, "channel": "ch", "language_detected": "en",
        "files": {"txt": "vid.txt"}, "status": "ok",
    }])
    out = resolve_source(batch, outputs_dir=tmp_path, latest=False)
    assert len(out) == 1
    assert out[0].title == "Hello world"
    assert out[0].upload_date == "2026-05-09"
    assert out[0].duration_sec == 222
    assert out[0].language == "en"
    assert out[0].url == "https://youtu.be/x"
    assert out[0].transcript_path == batch / "vid.txt"


def test_batch_folder_without_manifest(tmp_path: Path):
    folder = tmp_path / "loose"
    folder.mkdir()
    (folder / "a.txt").write_text("[00:00:00.000 --> 00:00:01.000] a\n",
                                  encoding="utf-8")
    (folder / "b.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nb\n", encoding="utf-8")
    out = resolve_source(folder, outputs_dir=tmp_path, latest=False)
    assert len(out) == 2
    names = sorted(v.transcript_path.name for v in out)
    assert names == ["a.txt", "b.srt"]
    assert all(v.title is None for v in out)


def test_missing_path_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        resolve_source(tmp_path / "nope", outputs_dir=tmp_path, latest=False)


def test_pick_latest_batch(tmp_path: Path):
    older = tmp_path / "b1"
    newer = tmp_path / "b2"
    older.mkdir()
    newer.mkdir()
    (older / "manifest.json").write_text("{}", encoding="utf-8")
    (newer / "manifest.json").write_text("{}", encoding="utf-8")
    # bump newer's mtime
    later = time.time() + 60
    import os
    os.utime(newer, (later, later))
    assert pick_latest_batch(tmp_path) == newer


def test_pick_latest_batch_empty(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="no batches"):
        pick_latest_batch(tmp_path)


def test_latest_flag_uses_pick(tmp_path: Path):
    b = tmp_path / "the_only_batch"
    (b / "vid.txt").parent.mkdir(parents=True, exist_ok=True)
    (b / "vid.txt").write_text("[00:00:00.000 --> 00:00:01.000] x\n",
                               encoding="utf-8")
    _write_manifest(b, [{
        "index": 1, "url": None, "video_id": None,
        "title": "T", "upload_date": None, "duration_sec": None,
        "channel": None, "language_detected": None,
        "files": {"txt": "vid.txt"}, "status": "ok",
    }])
    out = resolve_source(None, outputs_dir=tmp_path, latest=True)
    assert len(out) == 1
    assert out[0].title == "T"
