"""Tests for keyframe extraction. ffmpeg subprocess mocked."""
from pathlib import Path
from unittest.mock import patch, MagicMock

from skills.youtube_transcribe.vision.frames import extract_keyframes


def test_extract_keyframes_calls_ffmpeg(tmp_path):
    out_dir = tmp_path / "frames"
    out_dir.mkdir()
    # Pre-create tmp_NNNN.jpg files matching the impl pattern
    for i in range(1, 4):
        (out_dir / f"tmp_{i:04d}.jpg").write_bytes(b"fake jpeg")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = extract_keyframes(
            video_path=Path("input.mp4"),
            start=10.0,
            end=15.0,
            count=3,
            out_dir=out_dir,
            video_id="abc",
        )

    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert "ffmpeg" in cmd[0]
    assert "-ss" in cmd
    assert "10.0" in cmd
    # Returns paths to extracted frames
    assert len(result) == 3


def test_extract_keyframes_renames_with_video_id(tmp_path):
    out_dir = tmp_path / "frames"
    out_dir.mkdir()
    (out_dir / "tmp_0001.jpg").write_bytes(b"fake")

    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        paths = extract_keyframes(
            video_path=Path("v.mp4"),
            start=5.0,
            end=10.0,
            count=1,
            out_dir=out_dir,
            video_id="vid123",
        )
    # Renamed files should follow <video_id>_<sec>.jpg pattern
    for p in paths:
        assert p.name.startswith("vid123_")
        assert p.exists()
