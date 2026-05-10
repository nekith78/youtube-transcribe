"""Tests for manifest.json v0.2 extensions (quality, visual_segments)."""
import json
from datetime import date, datetime
from pathlib import Path

from skills.youtube_transcribe.utils.output_writer import (
    BatchMeta,
    BatchVideoStatus,
    write_manifest_json,
)
from skills.youtube_transcribe.backends.vision_base import VisualSegment
from skills.youtube_transcribe.quality.base import QualityReport


def _meta():
    return BatchMeta(
        batch_name="b", created_at=datetime(2026, 5, 10),
        source_type="inline", source_url=None,
        backend="whisper-local", backend_options={}, language="en",
    )


def test_manifest_includes_quality_field(tmp_path):
    v = BatchVideoStatus(
        index=1, url="https://x", video_id="x", title="X",
        upload_date=date(2026, 4, 1), duration_sec=60, channel="C",
        language_detected="en",
        text="hi", files={"txt": "X.txt"}, status="ok",
        quality=QualityReport(score=0.8, breakdown={"oov": 0.05}, flags=[],
                              recommendation="use_as_is"),
    )
    write_manifest_json([v], [], _meta(), tmp_path)
    data = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert data["videos"][0]["quality"]["score"] == 0.8
    assert data["videos"][0]["quality"]["recommendation"] == "use_as_is"


def test_manifest_includes_visual_segments(tmp_path):
    v = BatchVideoStatus(
        index=1, url="https://x", video_id="x", title="X",
        upload_date=date(2026, 4, 1), duration_sec=60, channel="C",
        language_detected="en",
        text="hi", files={"txt": "X.txt"}, status="ok",
        visual_segments=[
            VisualSegment(
                start=10.0, end=15.0, description="d",
                keyframes=["frames/x.jpg"], importance="high",
                detected_objects=["a"], trigger_reason="raw",
            ),
        ],
    )
    write_manifest_json([v], [], _meta(), tmp_path)
    data = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    vs = data["videos"][0]["visual_segments"][0]
    assert vs["start"] == 10.0
    assert vs["importance"] == "high"
    assert vs["keyframes"] == ["frames/x.jpg"]


def test_manifest_no_quality_field_when_none(tmp_path):
    v = BatchVideoStatus(
        index=1, url="https://x", video_id="x", title="X",
        upload_date=date(2026, 4, 1), duration_sec=60, channel="C",
        language_detected="en",
        text="hi", files={"txt": "X.txt"}, status="ok",
    )
    write_manifest_json([v], [], _meta(), tmp_path)
    data = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert data["videos"][0].get("quality") is None
