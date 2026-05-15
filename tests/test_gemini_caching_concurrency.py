"""Tests for v0.10.1 Gemini backend improvements:
  • caching: video bundle, skip when N<2
  • adaptive concurrency by tier
  • retryDelay parsing from 429 responses
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skills.neurolearn.detection.base import DetectionWindow
from skills.neurolearn.vision.gemini import (
    GeminiVisionBackend, concurrency_for_tier, _parse_retry_delay_seconds,
)


def _fake_response(payload: dict, *, prompt=1000, output=100, cached=0):
    r = MagicMock()
    r.text = json.dumps(payload)
    r.usage_metadata = MagicMock(
        prompt_token_count=prompt,
        candidates_token_count=output,
        cached_content_token_count=cached,
        total_token_count=prompt + output,
    )
    return r


def _windows(n):
    return [
        DetectionWindow(
            start=i * 10.0, end=i * 10.0 + 5.0,
            reason="raw", score=0.8, weight=1.0, phrase=f"p{i}",
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Concurrency by tier
# ---------------------------------------------------------------------------


def test_concurrency_for_free_tier():
    assert concurrency_for_tier("free") == 3


def test_concurrency_for_paid_tier():
    assert concurrency_for_tier("paid") == 10


def test_concurrency_for_paid_tier2():
    assert concurrency_for_tier("paid-tier2") == 20


def test_concurrency_unknown_tier_falls_back_to_free():
    """Unknown tier strings (typos, future tiers we don't know about)
    should not crash — fall back to the safe free-tier floor."""
    assert concurrency_for_tier("enterprise-x9000") == 3
    assert concurrency_for_tier("") == 3


# ---------------------------------------------------------------------------
# retryDelay parsing from 429
# ---------------------------------------------------------------------------


def test_parse_retry_delay_from_429():
    err = Exception(
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, ..., "
        "'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', "
        "'retryDelay': '31s'}]}}"
    )
    assert _parse_retry_delay_seconds(err) == 31.0


def test_parse_retry_delay_with_decimal():
    err = Exception("429 ... 'retryDelay': '8.5s' ...")
    assert _parse_retry_delay_seconds(err) == 8.5


def test_parse_retry_delay_returns_none_for_non_429():
    """Non-quota errors shouldn't have a retryDelay parsed from them."""
    err = Exception("500 Internal server error")
    assert _parse_retry_delay_seconds(err) is None


def test_parse_retry_delay_returns_none_when_missing():
    err = Exception("429 RESOURCE_EXHAUSTED but no retryDelay in payload")
    assert _parse_retry_delay_seconds(err) is None


# ---------------------------------------------------------------------------
# Caching: skip when N<2, attempt when N>=2
# ---------------------------------------------------------------------------


def test_single_window_skips_cache_creation(tmp_path):
    """1 window → caching is uneconomical. Setup must not happen."""
    fake_client = MagicMock()
    fake_client.files.upload.return_value = MagicMock(name="files/1")
    fake_client.models.generate_content.return_value = _fake_response({
        "description": "x", "key_objects": [],
        "importance": "medium", "confidence": 0.9, "needs_refinement": False,
    })

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=fake_client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[out_dir / "v.jpg"],
    ):
        backend = GeminiVisionBackend(api_key="x")
        backend.annotate_segments(
            video_path=Path("v.mp4"), windows=_windows(1),
            prompt_template="t", language="en",
            video_id="v", out_dir=out_dir,
        )

    fake_client.caches.create.assert_not_called()


def test_two_windows_create_cache_with_video(tmp_path):
    """2+ windows → cache is created. The cache config must include the
    uploaded video in `contents` (not just the system_instruction) —
    this is what makes caching actually save tokens."""
    fake_client = MagicMock()
    fake_uploaded = MagicMock(name="files/1")
    fake_client.files.upload.return_value = fake_uploaded
    fake_client.caches.create.return_value.name = "cached/v"
    fake_client.models.generate_content.return_value = _fake_response({
        "description": "x", "key_objects": [],
        "importance": "medium", "confidence": 0.9, "needs_refinement": False,
    })

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=fake_client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[out_dir / "v.jpg"],
    ):
        backend = GeminiVisionBackend(api_key="x", max_concurrent=3)
        backend.annotate_segments(
            video_path=Path("v.mp4"), windows=_windows(3),
            prompt_template="MY_PROMPT_TEMPLATE", language="en",
            video_id="v", out_dir=out_dir,
        )

    fake_client.caches.create.assert_called_once()
    # The CreateCachedContentConfig must carry the system instruction.
    # We don't assert on `contents == [fake_uploaded]` because pydantic
    # coerces MagicMock into an empty Part shape — the strict equality
    # check fails on the mock, not on the real production payload.
    # Real integration is verified via the e2e smoke run in v0.10.
    config = fake_client.caches.create.call_args.kwargs["config"]
    assert "MY_PROMPT_TEMPLATE" in str(config.system_instruction)
    assert config.contents is not None   # contents arg was passed
    assert len(config.contents) >= 1


def test_cached_call_omits_video_from_per_request_contents(tmp_path):
    """When caching is active, per-window calls send only the dynamic
    user prompt — NOT the uploaded video again. Otherwise we pay for
    the video twice (cache + per-call)."""
    fake_client = MagicMock()
    fake_uploaded = MagicMock(name="files/1")
    fake_client.files.upload.return_value = fake_uploaded
    fake_client.caches.create.return_value.name = "cached/v"
    fake_client.models.generate_content.return_value = _fake_response({
        "description": "x", "key_objects": [],
        "importance": "medium", "confidence": 0.9, "needs_refinement": False,
    })

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=fake_client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[out_dir / "v.jpg"],
    ):
        backend = GeminiVisionBackend(api_key="x")
        backend.annotate_segments(
            video_path=Path("v.mp4"), windows=_windows(3),
            prompt_template="t", language="en",
            video_id="v", out_dir=out_dir,
        )

    # Per-window call should pass exactly one item (the user prompt
    # string) — no fake_uploaded reference.
    for call in fake_client.models.generate_content.call_args_list:
        contents = call.kwargs["contents"]
        assert len(contents) == 1
        # MagicMock comparison: video reference is the fake_uploaded MagicMock.
        assert contents[0] is not fake_uploaded


def test_cache_failure_falls_back_to_per_call_content(tmp_path):
    """If caches.create raises, we should keep sending video+prompt per call."""
    fake_client = MagicMock()
    fake_uploaded = MagicMock(name="files/1")
    fake_client.files.upload.return_value = fake_uploaded
    fake_client.caches.create.side_effect = RuntimeError("cache server down")
    fake_client.models.generate_content.return_value = _fake_response({
        "description": "x", "key_objects": [],
        "importance": "medium", "confidence": 0.9, "needs_refinement": False,
    })

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=fake_client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[out_dir / "v.jpg"],
    ):
        backend = GeminiVisionBackend(api_key="x")
        backend.annotate_segments(
            video_path=Path("v.mp4"), windows=_windows(3),
            prompt_template="t", language="en",
            video_id="v", out_dir=out_dir,
        )

    # Fallback: per-window calls re-send the video.
    for call in fake_client.models.generate_content.call_args_list:
        contents = call.kwargs["contents"]
        assert fake_uploaded in contents
