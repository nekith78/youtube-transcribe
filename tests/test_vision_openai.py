"""Tests for OpenAIVisionBackend. openai.OpenAI mocked."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from skills.youtube_transcribe.detection.base import DetectionWindow
from skills.youtube_transcribe.vision.openai_vision import OpenAIVisionBackend


def _fake_resp(text: str):
    """Build an OpenAI chat.completions response."""
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_openai_annotate_returns_visual_segments(tmp_path):
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_resp(json.dumps({
        "description": "Terminal window with python script output",
        "key_objects": ["terminal", "python"],
        "importance": "high",
    }))

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    windows = [
        DetectionWindow(start=10.0, end=15.0, reason="universal",
                        score=0.8, weight=1.0, phrase="code"),
    ]
    fake_frame = out_dir / "frames" / "v_00010.jpg"
    fake_frame.parent.mkdir(parents=True)
    fake_frame.write_bytes(b"\xff\xd8\xff" + b"fake jpeg")

    with patch(
        "openai.OpenAI",
        return_value=fake_client,
    ), patch(
        "skills.youtube_transcribe.vision.frames.extract_keyframes",
        return_value=[fake_frame],
    ):
        backend = OpenAIVisionBackend(api_key="fake", frames_per_window=1)
        result = backend.annotate_segments(
            video_path=Path("v.mp4"),
            windows=windows,
            prompt_template="describe {language} {transcript_snippet} {start_sec} {end_sec}",
            language="en",
            video_id="v",
            out_dir=out_dir,
        )

    assert len(result) == 1
    assert result[0].description == "Terminal window with python script output"
    assert result[0].importance == "high"
    assert "terminal" in result[0].detected_objects
    # Verify content blocks used the data:image/jpeg;base64 scheme
    call = fake_client.chat.completions.create.call_args
    content = call.kwargs["messages"][0]["content"]
    image_blocks = [b for b in content if b.get("type") == "image_url"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_openai_handles_invalid_json(tmp_path):
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_resp("plain text not json")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fake_frame = out_dir / "frames" / "x.jpg"
    fake_frame.parent.mkdir(parents=True)
    fake_frame.write_bytes(b"jpg")

    with patch(
        "openai.OpenAI",
        return_value=fake_client,
    ), patch(
        "skills.youtube_transcribe.vision.frames.extract_keyframes",
        return_value=[fake_frame],
    ):
        backend = OpenAIVisionBackend(api_key="fake")
        out = backend.annotate_segments(
            video_path=Path("v.mp4"),
            windows=[DetectionWindow(0, 1, "raw", 1.0, 1.0, "x")],
            prompt_template="x",
            language="en", video_id="v", out_dir=out_dir,
        )
    assert "plain text not json" in out[0].description


def test_openai_strips_code_fences(tmp_path):
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_resp(
        '```json\n{"description":"d","key_objects":["a"],"importance":"low"}\n```'
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fake_frame = out_dir / "frames" / "x.jpg"
    fake_frame.parent.mkdir(parents=True)
    fake_frame.write_bytes(b"jpg")

    with patch(
        "openai.OpenAI",
        return_value=fake_client,
    ), patch(
        "skills.youtube_transcribe.vision.frames.extract_keyframes",
        return_value=[fake_frame],
    ):
        backend = OpenAIVisionBackend(api_key="fake")
        out = backend.annotate_segments(
            video_path=Path("v.mp4"),
            windows=[DetectionWindow(0, 1, "raw", 1, 1, "x")],
            prompt_template="x",
            language="en", video_id="v", out_dir=out_dir,
        )
    assert out[0].description == "d"
    assert "a" in out[0].detected_objects


def test_openai_empty_keyframes_skipped(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    with patch(
        "openai.OpenAI",
        return_value=MagicMock(),
    ), patch(
        "skills.youtube_transcribe.vision.frames.extract_keyframes",
        return_value=[],
    ):
        backend = OpenAIVisionBackend(api_key="fake")
        out = backend.annotate_segments(
            video_path=Path("v.mp4"),
            windows=[DetectionWindow(0, 1, "raw", 1, 1, "x")],
            prompt_template="x",
            language="en", video_id="v", out_dir=out_dir,
        )
    assert out == []
