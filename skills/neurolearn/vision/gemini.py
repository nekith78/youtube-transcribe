"""GeminiVisionBackend — multimodal annotation via Gemini File API.

v0.10 optimization wave (see docs/tutorial-pipeline guidance):
  • MEDIA_RESOLUTION_LOW (66 tok/sec vs 258) — 4× video-token savings.
    UI tutorials still legible; high-detail content not affected.
  • response_schema enforcement — Gemini cannot return invalid JSON,
    parser never crashes on a stray fence or missing field.
  • temperature=0.2 + max_output_tokens=300 — determinism, capped cost.
  • Async parallelism (Semaphore(10)) — N windows processed concurrently
    instead of sequentially.
  • Prompt caching (CreateCachedContentConfig) — system prompt cached once
    per video; subsequent windows reuse it (~75% input-token savings).
  • Per-segment confidence + needs_refinement signals so the orchestrator
    can route low-confidence outputs to Claude refinement.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from google import genai
from google.genai import types

from skills.neurolearn.backends.vision_base import VisionBackend, VisualSegment
from skills.neurolearn.detection.base import DetectionWindow
from skills.neurolearn.vision import frames as frames_mod
from skills.neurolearn.vision.prompts import format_prompt


# JSON schema Gemini MUST follow. response_mime_type=application/json plus
# this schema makes the model emit a structured object every time.
_SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "Concise description of what's happening visually (≤300 chars).",
        },
        "key_objects": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Names of UI elements / objects in focus.",
        },
        "importance": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "1.0 = transcript and frames unambiguously confirm the action; "
                "0.5 = some doubt remains about which element/state; "
                "0.0 = action not visible. Drives Claude refinement."
            ),
        },
        "needs_refinement": {
            "type": "boolean",
            "description": (
                "True when the frame contains small text or similar-looking "
                "elements you couldn't read precisely. Triggers Claude refinement."
            ),
        },
    },
    "required": [
        "description", "key_objects", "importance",
        "confidence", "needs_refinement",
    ],
}


# Concurrency caps per Gemini tier. The actual API limits are higher,
# but a conservative cap leaves room for retries inside the same minute.
_TIER_CONCURRENCY: dict[str, int] = {
    "free": 3,
    "paid": 10,
    "paid-tier2": 20,
    "paid-tier3": 50,
}


def concurrency_for_tier(tier: str) -> int:
    """Pick a sensible max_concurrent for the given Gemini tier. Unknown
    tier strings fall back to the safe `free` floor."""
    return _TIER_CONCURRENCY.get(tier, _TIER_CONCURRENCY["free"])


@dataclass
class TokenUsage:
    """Per-call billing summary.

    Populated from Gemini SDK's `usage_metadata`. Aggregated by the caller
    into BudgetTracker (skills/neurolearn/budget.py).
    """
    prompt_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0     # contribution of cached content (subtract from prompt for cost)
    total_tokens: int = 0


@dataclass
class GeminiVisionBackend:
    api_key: str
    model: str = "gemini-2.5-flash"
    frames_per_window: int = 3
    max_retries: int = 3
    # Concurrency floor — tuned per Gemini tier. Free tier 2.5-flash has
    # an RPM limit of 5; we keep 3 to leave headroom for retries hitting
    # the same minute. Paid Tier 1 gets 1000 RPM → 10 is safe and fast.
    # Callers override via gemini_tier (config) or this kwarg directly.
    max_concurrent: int = 3
    # When True (driven by tutorial preset / asymmetric frame mode), the
    # caller passes `event_ts` so we can take frames at offsets
    # `-1.5s / +0.3s / +2.0s` instead of evenly spaced through the window.
    use_asymmetric_offsets: bool = False
    # Populated by annotate_segments — read by orchestrator into the
    # BudgetTracker. Initialised empty; one TokenUsage per window.
    last_run_usage: list[TokenUsage] = field(default_factory=list)

    def annotate_segments(
        self,
        video_path: Path,
        windows: list[DetectionWindow],
        prompt_template: str,
        language: str,
        video_id: str,
        out_dir: Path,
    ) -> list[VisualSegment]:
        """Sync facade. Drives the async pipeline internally so callers
        don't need to be async (yet)."""
        self.last_run_usage = []
        if not windows:
            return []
        return asyncio.run(self._annotate_async(
            video_path=video_path,
            windows=windows,
            prompt_template=prompt_template,
            language=language,
            video_id=video_id,
            out_dir=out_dir,
        ))

    async def _annotate_async(
        self,
        *,
        video_path: Path,
        windows: list[DetectionWindow],
        prompt_template: str,
        language: str,
        video_id: str,
        out_dir: Path,
    ) -> list[VisualSegment]:
        client = genai.Client(api_key=self.api_key)
        # Upload video ONCE, reuse uploaded reference for every window.
        try:
            uploaded = await asyncio.to_thread(
                client.files.upload, file=str(video_path),
            )
        except Exception:
            return []

        # Caching strategy (v0.10.1):
        # We cache the UPLOADED VIDEO together with the system prompt —
        # not the prompt alone. Caching the prompt alone hits the 1024-
        # token minimum and rarely activates. The video easily clears
        # that threshold (~66 tok/sec on LOW res), so the bundle always
        # qualifies for caching. Subsequent per-window calls reference
        # the cached bundle and pay only 25% of the rate on its tokens —
        # which dominate the per-call billing, so this is the actual win.
        #
        # Skip caching entirely when there's only 1 window: setup +
        # storage cost outweighs the single cached call.
        cached_name = None
        if len(windows) >= 2:
            cached_name = await self._maybe_create_cache(
                client, prompt_template, uploaded,
            )

        frames_dir = out_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        # Extract keyframes synchronously (ffmpeg-bound, not API-bound).
        # The expensive part is the LLM call — that's where we parallelise.
        per_window_keyframes: list[tuple[DetectionWindow, list[Path]]] = []
        for w in windows:
            try:
                keyframes = self._extract_frames_for_window(
                    video_path, w, frames_dir, video_id,
                )
            except Exception:
                continue
            if not keyframes:
                continue
            per_window_keyframes.append((w, keyframes))

        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _run_one(w: DetectionWindow, keyframes: list[Path]):
            async with semaphore:
                return await self._annotate_window_async(
                    client=client,
                    uploaded=uploaded,
                    window=w,
                    prompt_template=prompt_template,
                    language=language,
                    cached_name=cached_name,
                    keyframes=keyframes,
                )

        results = await asyncio.gather(
            *[_run_one(w, kf) for w, kf in per_window_keyframes],
            return_exceptions=False,
        )
        return [r for r in results if r is not None]

    def _extract_frames_for_window(
        self,
        video_path: Path,
        window: DetectionWindow,
        frames_dir: Path,
        video_id: str,
    ) -> list[Path]:
        if self.use_asymmetric_offsets:
            # Tutorial preset: speech-anchored offsets. window.start is
            # already `seg.start - 1.5`, so the speech event lands at
            # window.start + 1.5. Take frames at -1.5 / +0.3 / +2.0
            # relative to that event.
            event_ts = window.start + 1.5
            return frames_mod.extract_keyframes_asymmetric(
                video_path=video_path,
                event_ts=event_ts,
                out_dir=frames_dir,
                video_id=video_id,
            )
        return frames_mod.extract_keyframes(
            video_path=video_path,
            start=window.start,
            end=window.end,
            count=self.frames_per_window,
            out_dir=frames_dir,
            video_id=video_id,
        )

    async def _maybe_create_cache(
        self,
        client: genai.Client,
        prompt_template: str,
        uploaded,
    ) -> str | None:
        """Cache the uploaded video + system prompt for reuse across windows.

        The combined bundle is what makes caching worthwhile (the video
        easily clears the 1024-token cache minimum; the prompt alone
        usually doesn't). The cache lives for 1h by default, which
        comfortably covers any single-video pipeline run.

        Returns the cache resource name on success; None on failure
        (caller falls back to per-call system_instruction inclusion).
        """
        try:
            cache = await asyncio.to_thread(
                client.caches.create,
                model=self.model,
                config=types.CreateCachedContentConfig(
                    contents=[uploaded],
                    system_instruction=prompt_template,
                    ttl="3600s",
                ),
            )
        except Exception:
            return None
        # Defensive: SDK shape may evolve; only return a string. Mock
        # objects (tests) hit this branch and silently fall back to the
        # per-call system_instruction path.
        name = getattr(cache, "name", None)
        if isinstance(name, str) and name:
            return name
        return None

    async def _annotate_window_async(
        self,
        *,
        client: genai.Client,
        uploaded,
        window: DetectionWindow,
        prompt_template: str,
        language: str,
        cached_name: str | None,
        keyframes: list[Path],
    ) -> VisualSegment | None:
        user_prompt = format_prompt(
            prompt_template,
            language=language,
            transcript_snippet=window.phrase or "(window from scene change)",
            start_sec=window.start,
            end_sec=window.end,
        )

        config_kwargs: dict = dict(
            temperature=0.2,
            max_output_tokens=300,
            response_mime_type="application/json",
            response_schema=_SEGMENT_SCHEMA,
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        )
        if cached_name:
            config_kwargs["cached_content"] = cached_name
        else:
            # No cache available — inline the system prompt.
            config_kwargs["system_instruction"] = prompt_template

        config = types.GenerateContentConfig(**config_kwargs)

        # When caching is active the bundle (video + system prompt) is
        # already on Google's side — we only send the dynamic per-window
        # part. Otherwise (cache failed / N<2 windows) we re-send the
        # uploaded video reference together with the user prompt.
        contents = [user_prompt] if cached_name else [user_prompt, uploaded]

        usage: TokenUsage | None = None
        # Default exponential backoff used when the server doesn't tell
        # us how long to wait. Gemini 429s include a `retryDelay` value
        # in seconds — we honor that when present (so we wake up right
        # after the per-minute quota window resets, not earlier and not
        # 31 seconds later).
        default_backoffs = [3.0, 6.0, 12.0]
        last_err: Exception | None = None
        response = None
        for attempt in range(self.max_retries):
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=self.model,
                    contents=contents,
                    config=config,
                )
                usage = _extract_usage(response)
                break
            except Exception as e:
                last_err = e
                if attempt >= self.max_retries - 1:
                    break
                # Prefer the server-suggested retry delay (seconds).
                # Falls back to exponential backoff when we can't parse one.
                retry_delay = _parse_retry_delay_seconds(e)
                wait = retry_delay if retry_delay is not None else default_backoffs[attempt]
                # Cap wait at 60s so a single failed call doesn't stall
                # the whole pipeline.
                await asyncio.sleep(min(wait, 60.0))
        if response is None:
            # All retries failed — record a zero-cost usage entry so
            # downstream budget logging stays correct.
            self.last_run_usage.append(TokenUsage())
            return VisualSegment(
                start=window.start,
                end=window.end,
                description=f"(error: {last_err})",
                keyframes=[f"frames/{p.name}" for p in keyframes],
                detected_objects=[],
                trigger_reason=window.reason,
                importance="medium",
                confidence=0.0,
                needs_refinement=False,
            )

        if usage is not None:
            self.last_run_usage.append(usage)

        desc, key_objects, importance, confidence, needs_refinement = (
            _parse_structured_response(response.text or "")
        )
        return VisualSegment(
            start=window.start,
            end=window.end,
            description=desc,
            keyframes=[f"frames/{p.name}" for p in keyframes],
            detected_objects=key_objects,
            trigger_reason=window.reason,
            importance=importance,
            confidence=confidence,
            needs_refinement=needs_refinement,
        )


def _extract_usage(response) -> TokenUsage:
    """Pull token counts from a Gemini response. Resilient to SDK shape changes."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return TokenUsage()
    prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
    out = int(getattr(meta, "candidates_token_count", 0) or 0)
    cached = int(getattr(meta, "cached_content_token_count", 0) or 0)
    total = int(getattr(meta, "total_token_count", 0) or 0)
    return TokenUsage(
        prompt_tokens=prompt,
        output_tokens=out,
        cached_tokens=cached,
        total_tokens=total,
    )


def _parse_structured_response(
    text: str,
) -> tuple[str, list[str], str, float, bool]:
    """Parse the JSON Gemini returned. Schema-enforced so we expect a
    valid object, but be defensive — log + fall back to text if shape
    drifted between SDK versions."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = "\n".join(line for line in text.split("\n") if not line.startswith("```"))
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text, [], "medium", 0.5, False

    description = str(data.get("description", text))[:2000]
    raw_objects = data.get("key_objects", [])
    key_objects = [str(o) for o in raw_objects] if isinstance(raw_objects, list) else []

    importance = data.get("importance", "medium")
    if importance not in ("low", "medium", "high"):
        importance = "medium"

    try:
        confidence = float(data.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 1.0
    confidence = max(0.0, min(1.0, confidence))

    needs_refinement = bool(data.get("needs_refinement", False))
    return description, key_objects, importance, confidence, needs_refinement


def _parse_retry_delay_seconds(exc: Exception) -> float | None:
    """Pull a `retryDelay` (seconds) out of a Gemini 429 exception.

    Gemini's RESOURCE_EXHAUSTED responses embed a Google `RetryInfo`
    detail with a string like `"retryDelay": "31s"`. Honoring it makes
    retries land right after the per-minute quota resets, instead of
    sleeping the default backoff and missing the window.

    Returns the delay in seconds, or None when the exception doesn't
    carry one (e.g. transient network failure, server-side timeout).
    """
    import re
    text = str(exc)
    if "429" not in text and "RESOURCE_EXHAUSTED" not in text:
        return None
    # Format observed in production: "retryDelay": "31s" or 'retryDelay': '31s'
    match = re.search(
        r"retry[_-]?delay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s",
        text,
        re.IGNORECASE,
    )
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None
