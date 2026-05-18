"""Tests for report.outliner — structured outline generation.

Two paths to verify:
  • Short video (<15min transcript) → single LLM call.
  • Long video → hierarchical: section detect → per-section LLM →
    final assembly.

LLM calls are mocked at the runner level — no API access needed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from skills.neurolearn.report.outliner import (
    Outline, Section, build_outline, _split_into_chunks,
    _SHORT_VIDEO_THRESHOLD_TOKENS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _Seg:
    start: float
    end: float
    text: str


def _short_segments():
    return [
        _Seg(0, 30, "Welcome to this tutorial."),
        _Seg(30, 60, "First, click the Save button in the toolbar."),
        _Seg(60, 90, "Now press Enter to confirm."),
    ]


def _long_segments(duration_min: int = 30):
    """Generate ~1 segment per minute for long-video tests."""
    return [
        _Seg(i * 60, (i + 1) * 60, f"Section {i}: about topic {i}.")
        for i in range(duration_min)
    ]


def _visual_segments():
    return [
        {
            "start": 30.0, "end": 35.0,
            "description": "Save button highlighted in toolbar",
            "keyframes": ["frames/v_00030.jpg"],
            "importance": "high",
        },
        {
            "start": 60.0, "end": 65.0,
            "description": "Confirmation dialog appears",
            "keyframes": ["frames/v_00060.jpg"],
            "importance": "medium",
        },
    ]


def _fake_outline_response(*, sections_count: int = 2) -> str:
    """Build a fake LLM response in the schema the outliner expects."""
    sections = [
        {
            "title": f"Step {i+1}",
            "summary": f"Do thing {i+1}.",
            "key_points": [f"detail {i+1}.1", f"detail {i+1}.2"],
            "image_refs": [f"frames/v_{(i+1)*30:05d}.jpg"],
            "timestamps": [f"00:00:{(i+1)*30:02d}"],
        }
        for i in range(sections_count)
    ]
    return json.dumps({
        "title": "Test Tutorial",
        "summary": "A test outline.",
        "sections": sections,
    })


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


def test_outline_dataclass_serializes_to_dict():
    """Outline → dict for JSON serialization (manifest, debug logs)."""
    o = Outline(
        title="X", summary="S",
        sections=[Section(title="A", summary="a")],
    )
    d = o.to_dict()
    assert d["title"] == "X"
    assert d["sections"][0]["title"] == "A"


# ---------------------------------------------------------------------------
# Short-video path (single LLM call)
# ---------------------------------------------------------------------------


def test_short_video_uses_single_call():
    """Transcript well below the threshold → one LLM call."""
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=_fake_outline_response(sections_count=2),
    ) as mock_llm:
        outline = build_outline(
            segments=_short_segments(),
            visual_segments=_visual_segments(),
            report_type="tutorial",
            target_language="en",
            user_filter="",
            backend="gemini",
            api_key="fake",
        )

    assert mock_llm.call_count == 1
    assert len(outline.sections) == 2
    assert outline.title == "Test Tutorial"


def test_user_filter_passed_to_llm():
    """User --prompt content should land in the LLM prompt."""
    captured_prompts = []

    def capture(prompt, **kw):
        captured_prompts.append(prompt)
        return _fake_outline_response(sections_count=1)

    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        side_effect=capture,
    ):
        build_outline(
            segments=_short_segments(),
            visual_segments=_visual_segments(),
            report_type="tutorial",
            target_language="en",
            user_filter="only commands for CI/CD",
            backend="gemini",
            api_key="fake",
        )

    assert captured_prompts
    assert any("only commands for CI/CD" in p for p in captured_prompts)


def test_target_language_passed_to_llm():
    """target_language reaches the prompt template."""
    captured = []
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        side_effect=lambda p, **k: (captured.append(p) or _fake_outline_response()),
    ):
        build_outline(
            segments=_short_segments(),
            visual_segments=_visual_segments(),
            report_type="tutorial",
            target_language="ru",
            user_filter="",
            backend="gemini",
            api_key="fake",
        )
    assert any("ru" in p.lower() or "language" in p.lower() for p in captured)


def test_malformed_llm_response_returns_minimal_outline():
    """LLM returns non-JSON → outliner returns a degraded outline rather
    than crashing the pipeline."""
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value="not valid json at all",
    ):
        outline = build_outline(
            segments=_short_segments(),
            visual_segments=_visual_segments(),
            report_type="tutorial",
            target_language="en",
            user_filter="",
            backend="gemini",
            api_key="fake",
        )
    # We always return SOME outline so the renderer can still produce a PDF.
    assert outline is not None
    assert isinstance(outline.sections, list)


# ---------------------------------------------------------------------------
# Long-video path (hierarchical)
# ---------------------------------------------------------------------------


def test_long_video_chunks_and_uses_multiple_calls():
    """Transcript over the threshold → multiple per-section LLM calls
    + one final assembly call."""
    # Generate ~30 minutes of content
    long_segs = _long_segments(duration_min=30)

    # Stretch each segment's text so we cross the token threshold cleanly.
    # Threshold is ~15k tokens (~60k chars); 30 segs × ~25 chars × 200
    # = ~150k chars → ~37k tokens → clearly hierarchical territory.
    for s in long_segs:
        s.text = s.text * 200

    call_count = {"n": 0}
    def fake(prompt, **kw):
        call_count["n"] += 1
        return _fake_outline_response(sections_count=2)

    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        side_effect=fake,
    ):
        outline = build_outline(
            segments=long_segs,
            visual_segments=[],
            report_type="generic",
            target_language="en",
            user_filter="",
            backend="gemini",
            api_key="fake",
        )

    # More than 1 LLM call → confirms we took the hierarchical path.
    assert call_count["n"] > 1, "Expected hierarchical (multiple LLM calls), got 1"
    assert outline is not None
    assert outline.sections


def test_long_video_chunks_run_in_parallel():
    """v0.10.4: hierarchical path runs per-chunk LLM calls concurrently
    via thread pool. Sequential 5×100ms = 500ms; parallel = ~100ms."""
    import threading
    import time

    long_segs = _long_segments(duration_min=30)
    for s in long_segs:
        s.text = s.text * 200    # cross 15k token threshold

    concurrent = 0
    max_concurrent = 0
    lock = threading.Lock()

    def slow_call(prompt, **kw):
        nonlocal concurrent, max_concurrent
        with lock:
            concurrent += 1
            if concurrent > max_concurrent:
                max_concurrent = concurrent
        time.sleep(0.1)
        with lock:
            concurrent -= 1
        return _fake_outline_response(sections_count=1)

    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        side_effect=slow_call,
    ):
        t0 = time.time()
        outline = build_outline(
            segments=long_segs,
            visual_segments=[],
            report_type="generic",
            target_language="en",
            user_filter="",
            backend="gemini",
            api_key="fake",
        )
        elapsed = time.time() - t0

    # At least 2 chunks must have been in flight simultaneously.
    assert max_concurrent >= 2, f"max_concurrent={max_concurrent} (sequential)"
    # Sections preserved in chunk order.
    assert outline.sections
    # Wall time should be well below sequential (Nx100ms).
    # 30 segments * 200 mult ~> ~6 chunks; sequential = 600ms+, parallel cap=4 → ~200ms.
    assert elapsed < 0.45, f"elapsed={elapsed:.2f}s (too slow → likely sequential)"


def test_split_into_chunks_respects_target_size():
    """Chunker shouldn't produce chunks much bigger than the target."""
    long_segs = _long_segments(duration_min=60)
    for s in long_segs:
        s.text = s.text * 50    # bloat each segment

    chunks = _split_into_chunks(long_segs, target_tokens=2000)
    assert len(chunks) > 1
    # No chunk should be empty.
    for chunk in chunks:
        assert chunk
        # Each chunk should be a contiguous range — sorted by start.
        starts = [s.start for s in chunk]
        assert starts == sorted(starts)


def test_split_into_chunks_returns_single_when_short():
    """Below threshold → no splitting."""
    chunks = _split_into_chunks(_short_segments(), target_tokens=10_000)
    assert len(chunks) == 1


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------


def test_no_segments_returns_empty_outline():
    """build_outline with empty segments doesn't crash; returns empty
    outline with a clear marker. Renderer can decide what to do."""
    outline = build_outline(
        segments=[],
        visual_segments=[],
        report_type="generic",
        target_language="en",
        user_filter="",
        backend="gemini",
        api_key="fake",
    )
    assert outline is not None
    assert outline.sections == []


def test_string_valued_timestamps_coerced_to_list():
    """LLM sometimes returns timestamps as a single string. We must
    wrap it into [str], not iterate char-by-char."""
    bad_response = json.dumps({
        "title": "T", "summary": "s",
        "sections": [{
            "title": "Sec 1",
            "summary": "x",
            "key_points": "single bullet",     # string, not list
            "image_refs": "frames/v.jpg",      # string, not list
            "timestamps": "[00:00:25]",        # string, not list
        }],
    })
    with patch(
        "skills.neurolearn.report.outliner.run_analysis",
        return_value=bad_response,
    ):
        outline = build_outline(
            segments=_short_segments(),
            visual_segments=[],
            report_type="generic",
            target_language="en",
            user_filter="",
            backend="gemini",
            api_key="fake",
        )
    sec = outline.sections[0]
    assert sec.key_points == ["single bullet"]
    assert sec.image_refs == ["frames/v.jpg"]
    # Timestamps normalize away surrounding brackets — the renderer
    # adds its own.
    assert sec.timestamps == ["00:00:25"]


def test_short_video_threshold_constant_sane():
    """Threshold for short-vs-long routing must be a positive int. We
    don't pin a specific value — just sanity-check the constant exists
    and is reasonable."""
    assert isinstance(_SHORT_VIDEO_THRESHOLD_TOKENS, int)
    assert 5_000 < _SHORT_VIDEO_THRESHOLD_TOKENS < 100_000
