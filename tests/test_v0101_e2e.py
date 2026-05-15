"""End-to-end integration tests for v0.10.1 features.

Drives the actual pipeline_v02 with mocked Gemini client + frame
extractor. Verifies that all the moving parts (CLI flag → config →
pipeline → prompt loader → backend) connect correctly without relying
on a real API.

Real Gemini smoke is run separately (manual + the v0.10 reel test).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skills.neurolearn.backends.base import TranscriptionResult, Segment


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_segments(*pieces) -> list[Segment]:
    """Build a list of Segments from (start, end, text) tuples."""
    out = []
    for start, end, text in pieces:
        s = MagicMock(spec=Segment)
        s.start = start
        s.end = end
        s.text = text
        out.append(s)
    return out


def _fake_response(payload: dict, *, prompt=1500, output=120, cached=0):
    r = MagicMock()
    r.text = json.dumps(payload)
    r.usage_metadata = MagicMock(
        prompt_token_count=prompt,
        candidates_token_count=output,
        cached_content_token_count=cached,
        total_token_count=prompt + output,
    )
    return r


def _stub_gemini_client(payload: dict | None = None) -> MagicMock:
    """genai.Client mock with files/cache/generate wired."""
    client = MagicMock()
    client.files.upload.return_value = MagicMock(name="files/1")
    client.caches.create.return_value.name = "cached/test-id"
    client.models.generate_content.return_value = _fake_response(payload or {
        "description": "Test description",
        "key_objects": ["obj1"],
        "importance": "medium",
        "confidence": 0.9,
        "needs_refinement": False,
    })
    return client


def _make_result(segments: list[Segment]) -> TranscriptionResult:
    r = TranscriptionResult(
        text=" ".join(s.text for s in segments),
        segments=segments,
        language_detected="en",
        backend_name="whisper-local",
        duration_seconds=segments[-1].end if segments else 0.0,
    )
    return r


# ---------------------------------------------------------------------------
# E2E: per-type prompt selection
# ---------------------------------------------------------------------------


def test_e2e_explicit_video_type_overrides_autodetect(tmp_path):
    """CLI `--video-type tutorial` flag should pin the prompt regardless
    of what auto-detect would have picked."""
    from skills.neurolearn.pipeline_v02 import apply_v02_stages

    # Lecture-flavoured transcript — autodetect would NOT pick tutorial.
    segments = _fake_segments(
        (0, 60, "Today we'll discuss attention mechanisms."),
        (60, 120, "Research shows transformers outperform RNNs."),
        (120, 180, "As you can see on the slide, three layers."),
    )
    result = _make_result(segments)

    client = _stub_gemini_client()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    frames_dir = tmp_path / "out" / "frames"

    # Build N detection windows directly — don't depend on trigger matching.
    from skills.neurolearn.detection.base import DetectionWindow
    fake_windows = [
        DetectionWindow(start=10.0, end=15.0, reason="raw",
                        score=0.8, weight=1.0, phrase="x"),
        DetectionWindow(start=30.0, end=35.0, reason="raw",
                        score=0.8, weight=1.0, phrase="y"),
    ]

    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[frames_dir / "v.jpg"],
    ), patch(
        "skills.neurolearn.pipeline_v02._config_mod.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.neurolearn.pipeline_v02.find_detection_windows",
        return_value=fake_windows,
    ):
        cfg = {
            "vision_backend": "gemini",
            "detect_method": "keywords_only",
            "video_type": "tutorial",   # explicit override
            "frames_per_window": 1,
            "max_windows_per_video": 5,
            "gemini_tier": "free",
        }
        apply_v02_stages(
            result=result, cfg=cfg, video_path=video,
            video_id="v", out_dir=tmp_path / "out", source="whisper",
        )

    # The user prompt passed to generate_content must come from the
    # tutorial template (distinctive phrasing about UI actions).
    sent_prompts = [
        c.kwargs["contents"][0]
        for c in client.models.generate_content.call_args_list
    ]
    # At least one call should contain tutorial-specific phrasing.
    assert any("UI tutorial" in p or "UI action" in p for p in sent_prompts), \
        f"Expected tutorial-template text in sent prompts; got: {sent_prompts}"


def test_e2e_autodetect_picks_tutorial_from_dense_transcript(tmp_path):
    """No explicit video_type → autodetect runs on the transcript.
    Tutorial-dense transcript → tutorial prompt used."""
    from skills.neurolearn.pipeline_v02 import apply_v02_stages

    # 4 minutes of explicit UI actions.
    segments = _fake_segments(
        (0, 30,   "Click the Save button in the toolbar."),
        (30, 60,  "Now press Enter to confirm."),
        (60, 90,  "Select the file and open it."),
        (90, 120, "Type your password to log in."),
        (120, 150, "Copy the link and paste it."),
        (150, 180, "Scroll down to find the option."),
        (180, 210, "Click OK to save changes."),
        (210, 240, "Navigate to the settings page."),
    )
    result = _make_result(segments)

    client = _stub_gemini_client()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    frames_dir = tmp_path / "out" / "frames"

    # Build N detection windows directly — don't depend on trigger matching.
    from skills.neurolearn.detection.base import DetectionWindow
    fake_windows = [
        DetectionWindow(start=10.0, end=15.0, reason="raw",
                        score=0.8, weight=1.0, phrase="x"),
        DetectionWindow(start=30.0, end=35.0, reason="raw",
                        score=0.8, weight=1.0, phrase="y"),
    ]

    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[frames_dir / "v.jpg"],
    ), patch(
        "skills.neurolearn.pipeline_v02._config_mod.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.neurolearn.pipeline_v02.find_detection_windows",
        return_value=fake_windows,
    ):
        cfg = {
            "vision_backend": "gemini",
            "detect_method": "keywords_only",
            "frames_per_window": 1,
            "max_windows_per_video": 5,
            "gemini_tier": "free",
            # No video_type → auto-detect should pick "tutorial".
        }
        apply_v02_stages(
            result=result, cfg=cfg, video_path=video,
            video_id="v", out_dir=tmp_path / "out", source="whisper",
        )

    sent_prompts = [
        c.kwargs["contents"][0]
        for c in client.models.generate_content.call_args_list
    ]
    # Auto-detect should pick tutorial — tutorial-template text present.
    assert any("UI tutorial" in p or "UI action" in p for p in sent_prompts)


def test_e2e_no_signal_falls_back_to_talking_head(tmp_path):
    """A long signal-less narrative → autodetect picks talking_head."""
    from skills.neurolearn.pipeline_v02 import apply_v02_stages

    # 5 minutes of generic narrative.
    segments = _fake_segments(
        (0, 60,    "And so I was thinking about life and what it means."),
        (60, 120,  "It's a complicated topic with no easy answers."),
        (120, 180, "But here's what I've come to believe over the years."),
        (180, 240, "The journey matters more than the destination."),
        (240, 300, "And the people you meet along the way."),
    )
    result = _make_result(segments)

    client = _stub_gemini_client()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    frames_dir = tmp_path / "out" / "frames"

    # Build N detection windows directly — don't depend on trigger matching.
    from skills.neurolearn.detection.base import DetectionWindow
    fake_windows = [
        DetectionWindow(start=10.0, end=15.0, reason="raw",
                        score=0.8, weight=1.0, phrase="x"),
        DetectionWindow(start=30.0, end=35.0, reason="raw",
                        score=0.8, weight=1.0, phrase="y"),
    ]

    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[frames_dir / "v.jpg"],
    ), patch(
        "skills.neurolearn.pipeline_v02._config_mod.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.neurolearn.pipeline_v02.find_detection_windows",
        return_value=fake_windows,
    ):
        cfg = {
            "vision_backend": "gemini",
            "detect_method": "keywords_only",
            "frames_per_window": 1,
            "max_windows_per_video": 5,
            "gemini_tier": "free",
        }
        apply_v02_stages(
            result=result, cfg=cfg, video_path=video,
            video_id="v", out_dir=tmp_path / "out", source="whisper",
        )

    sent_prompts = [
        c.kwargs["contents"][0]
        for c in client.models.generate_content.call_args_list
    ]
    # talking_head prompt has distinct phrasing about "talking-head video"
    # AND tells the model that "low importance" is the default.
    assert any(
        "talking-head" in p or "talking head" in p
        for p in sent_prompts
    ), f"Expected talking_head template; got: {sent_prompts}"


# ---------------------------------------------------------------------------
# E2E: user TOML override
# ---------------------------------------------------------------------------


def test_e2e_user_toml_override_loaded(tmp_path):
    """Real ~/.neurolearn/prompts.toml file should be loaded and used."""
    from skills.neurolearn.vision.prompts import load_prompt

    user_toml = tmp_path / "prompts.toml"
    user_toml.write_text("""
[global]
prefix = "CUSTOM GLOBAL — reply briefly in {language}."

[prompts.tutorial]
prompt = "CUSTOM TUTORIAL: focus on keyboard shortcuts only."
append_global = true

[prompts.cooking-show]
prompt = "Focus on ingredients and cooking actions."
append_global = false
""", encoding="utf-8")

    # Built-in tutorial → replaced by user template
    spec = load_prompt("tutorial", user_path=user_toml)
    assert "CUSTOM TUTORIAL: focus on keyboard shortcuts only." in spec.template
    assert "CUSTOM GLOBAL — reply briefly" in spec.template
    assert spec.source == "user_override"

    # New user-defined type that doesn't exist in built-ins
    spec = load_prompt("cooking-show", user_path=user_toml)
    assert spec.template == "Focus on ingredients and cooking actions."


# ---------------------------------------------------------------------------
# E2E: caching activation logic
# ---------------------------------------------------------------------------


def test_e2e_single_window_skips_cache_in_full_pipeline(tmp_path):
    """One detected visual moment → cache must NOT be created."""
    from skills.neurolearn.pipeline_v02 import apply_v02_stages

    segments = _fake_segments(
        (0, 30, "Plain talk."),
        (30, 60, "More plain talk, see this important point."),
    )
    result = _make_result(segments)

    client = _stub_gemini_client()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    frames_dir = tmp_path / "out" / "frames"

    # Single window — verifies skip-cache logic.
    from skills.neurolearn.detection.base import DetectionWindow
    single_window = [
        DetectionWindow(start=10.0, end=15.0, reason="raw",
                        score=0.8, weight=1.0, phrase="x"),
    ]

    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[frames_dir / "v.jpg"],
    ), patch(
        "skills.neurolearn.pipeline_v02._config_mod.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.neurolearn.pipeline_v02.find_detection_windows",
        return_value=single_window,
    ):
        cfg = {
            "vision_backend": "gemini",
            "detect_method": "keywords_only",
            "frames_per_window": 1,
            "max_windows_per_video": 5,
            "gemini_tier": "free",
        }
        apply_v02_stages(
            result=result, cfg=cfg, video_path=video,
            video_id="v", out_dir=tmp_path / "out", source="whisper",
        )

    # 1 window → skip caching.
    assert client.caches.create.call_count == 0


def test_e2e_multiple_windows_create_cache(tmp_path):
    """3 windows → cache IS created (with video bundled)."""
    from skills.neurolearn.pipeline_v02 import apply_v02_stages

    # Three trigger-matching segments → three windows.
    segments = _fake_segments(
        (0, 30,    "Click the button. Notice this part."),
        (30, 60,   "Press save. See this code."),
        (60, 90,   "Open the menu. For example."),
    )
    result = _make_result(segments)

    client = _stub_gemini_client()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    frames_dir = tmp_path / "out" / "frames"

    # Build N detection windows directly — don't depend on trigger matching.
    from skills.neurolearn.detection.base import DetectionWindow
    fake_windows = [
        DetectionWindow(start=10.0, end=15.0, reason="raw",
                        score=0.8, weight=1.0, phrase="x"),
        DetectionWindow(start=30.0, end=35.0, reason="raw",
                        score=0.8, weight=1.0, phrase="y"),
    ]

    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[frames_dir / "v.jpg"],
    ), patch(
        "skills.neurolearn.pipeline_v02._config_mod.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.neurolearn.pipeline_v02.find_detection_windows",
        return_value=fake_windows,
    ):
        cfg = {
            "vision_backend": "gemini",
            "detect_method": "keywords_only",
            "frames_per_window": 1,
            "max_windows_per_video": 5,
            "gemini_tier": "free",
        }
        apply_v02_stages(
            result=result, cfg=cfg, video_path=video,
            video_id="v", out_dir=tmp_path / "out", source="whisper",
        )

    # Multiple windows → cache IS created.
    assert client.caches.create.call_count == 1


# ---------------------------------------------------------------------------
# E2E: tier-aware concurrency
# ---------------------------------------------------------------------------


def test_e2e_free_tier_limits_concurrency(tmp_path):
    """`gemini_tier='free'` → backend instantiated with max_concurrent=3."""
    from skills.neurolearn.pipeline_v02 import apply_v02_stages
    from skills.neurolearn.vision import gemini as gemini_mod

    # Capture the GeminiVisionBackend constructor call.
    captured = {}

    real_class = gemini_mod.GeminiVisionBackend

    def factory(**kwargs):
        captured.update(kwargs)
        # Build a real backend but with a no-op annotate to keep test fast.
        backend = real_class(**kwargs)
        backend.annotate_segments = lambda **kw: []   # no API calls
        return backend

    segments = _fake_segments(
        (0, 30, "Click the button, see this code."),
        (30, 60, "Press save, notice this."),
    )
    result = _make_result(segments)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    from skills.neurolearn.detection.base import DetectionWindow
    fake_windows = [
        DetectionWindow(start=10.0, end=15.0, reason="raw",
                        score=0.8, weight=1.0, phrase="x"),
        DetectionWindow(start=30.0, end=35.0, reason="raw",
                        score=0.8, weight=1.0, phrase="y"),
    ]
    with patch(
        "skills.neurolearn.pipeline_v02.GeminiVisionBackend",
        side_effect=factory,
    ), patch(
        "skills.neurolearn.pipeline_v02._config_mod.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.neurolearn.pipeline_v02.find_detection_windows",
        return_value=fake_windows,
    ):
        cfg = {
            "vision_backend": "gemini",
            "detect_method": "keywords_only",
            "frames_per_window": 1,
            "max_windows_per_video": 5,
            "gemini_tier": "free",
        }
        apply_v02_stages(
            result=result, cfg=cfg, video_path=video,
            video_id="v", out_dir=tmp_path / "out", source="whisper",
        )

    assert captured.get("max_concurrent") == 3


def test_e2e_paid_tier_raises_concurrency(tmp_path):
    """`gemini_tier='paid'` → max_concurrent=10."""
    from skills.neurolearn.pipeline_v02 import apply_v02_stages
    from skills.neurolearn.vision import gemini as gemini_mod

    captured = {}
    real_class = gemini_mod.GeminiVisionBackend

    def factory(**kwargs):
        captured.update(kwargs)
        backend = real_class(**kwargs)
        backend.annotate_segments = lambda **kw: []
        return backend

    segments = _fake_segments((0, 30, "Click the button."))
    result = _make_result(segments)

    from skills.neurolearn.detection.base import DetectionWindow
    fake_windows = [
        DetectionWindow(start=10.0, end=15.0, reason="raw",
                        score=0.8, weight=1.0, phrase="x"),
    ]
    with patch(
        "skills.neurolearn.pipeline_v02.GeminiVisionBackend",
        side_effect=factory,
    ), patch(
        "skills.neurolearn.pipeline_v02._config_mod.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.neurolearn.pipeline_v02.find_detection_windows",
        return_value=fake_windows,
    ):
        cfg = {
            "vision_backend": "gemini",
            "detect_method": "keywords_only",
            "frames_per_window": 1,
            "max_windows_per_video": 5,
            "gemini_tier": "paid",
        }
        apply_v02_stages(
            result=result, cfg=cfg, video_path=tmp_path / "v.mp4",
            video_id="v", out_dir=tmp_path / "out", source="whisper",
        )

    assert captured.get("max_concurrent") == 10


# ---------------------------------------------------------------------------
# E2E: --vision-prompt + --no-global-prefix CLI flags
# ---------------------------------------------------------------------------


def test_e2e_custom_prompt_file_drops_global_prefix(tmp_path):
    """`cfg.vision_prompt_path` + `cfg.no_global_prefix=True` → only the
    user's file is sent, no built-in global rules prepended."""
    from skills.neurolearn.pipeline_v02 import apply_v02_stages

    prompt_file = tmp_path / "custom.txt"
    prompt_file.write_text(
        "STANDALONE CUSTOM PROMPT IN {language}: {transcript_snippet}",
        encoding="utf-8",
    )

    segments = _fake_segments(
        (0, 30, "Click button."), (30, 60, "Press save."),
    )
    result = _make_result(segments)

    client = _stub_gemini_client()

    from skills.neurolearn.detection.base import DetectionWindow
    fake_windows = [
        DetectionWindow(start=10.0, end=15.0, reason="raw",
                        score=0.8, weight=1.0, phrase="x"),
        DetectionWindow(start=30.0, end=35.0, reason="raw",
                        score=0.8, weight=1.0, phrase="y"),
    ]
    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[tmp_path / "v.jpg"],
    ), patch(
        "skills.neurolearn.pipeline_v02._config_mod.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.neurolearn.pipeline_v02.find_detection_windows",
        return_value=fake_windows,
    ):
        cfg = {
            "vision_backend": "gemini",
            "detect_method": "keywords_only",
            "frames_per_window": 1,
            "max_windows_per_video": 5,
            "gemini_tier": "free",
            "vision_prompt_path": str(prompt_file),
            "no_global_prefix": True,
        }
        apply_v02_stages(
            result=result, cfg=cfg, video_path=tmp_path / "v.mp4",
            video_id="v", out_dir=tmp_path / "out", source="whisper",
        )

    sent_prompts = [
        c.kwargs["contents"][0]
        for c in client.models.generate_content.call_args_list
    ]
    # Custom prompt text present.
    assert any("STANDALONE CUSTOM PROMPT" in p for p in sent_prompts)
    # Built-in global prefix NOT present.
    assert not any("Output language" in p for p in sent_prompts)


# ---------------------------------------------------------------------------
# E2E: budget tracker still flows into manifest
# ---------------------------------------------------------------------------


def test_e2e_budget_tracker_populated_after_run(tmp_path):
    """Backend.last_run_usage → BudgetTracker → result.budget. Validates
    the v0.10 wiring still works after v0.10.1 refactors."""
    from skills.neurolearn.pipeline_v02 import apply_v02_stages

    segments = _fake_segments(
        (0, 30, "Click button."), (30, 60, "Press save."),
    )
    result = _make_result(segments)

    client = _stub_gemini_client()

    from skills.neurolearn.detection.base import DetectionWindow
    fake_windows = [
        DetectionWindow(start=10.0, end=15.0, reason="raw",
                        score=0.8, weight=1.0, phrase="x"),
        DetectionWindow(start=30.0, end=35.0, reason="raw",
                        score=0.8, weight=1.0, phrase="y"),
    ]
    with patch(
        "skills.neurolearn.vision.gemini.genai.Client",
        return_value=client,
    ), patch(
        "skills.neurolearn.vision.frames.extract_keyframes",
        return_value=[tmp_path / "v.jpg"],
    ), patch(
        "skills.neurolearn.pipeline_v02._config_mod.get_api_key",
        return_value="fake-key",
    ), patch(
        "skills.neurolearn.pipeline_v02.find_detection_windows",
        return_value=fake_windows,
    ):
        cfg = {
            "vision_backend": "gemini",
            "detect_method": "keywords_only",
            "frames_per_window": 1,
            "max_windows_per_video": 5,
            "gemini_tier": "free",
        }
        out = apply_v02_stages(
            result=result, cfg=cfg, video_path=tmp_path / "v.mp4",
            video_id="v", out_dir=tmp_path / "out", source="whisper",
        )

    budget = getattr(out, "budget", None)
    assert budget is not None
    summary = budget.summary()
    assert summary["total_calls"] >= 1
    assert summary["total_cost_usd"] > 0
    assert "vision_gemini" in summary["by_stage"]
