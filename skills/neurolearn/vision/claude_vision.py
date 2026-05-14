"""ClaudeVisionBackend — multimodal annotation via Claude Sonnet vision.

Unlike Gemini File API, Claude vision is images-only: we extract keyframes
via ffmpeg (already done in vision/frames.py) and send them as base64
images per prompt. Each window = 1 messages.create call with N keyframes
+ text context (transcript snippet + structured output instructions).

Cost note: Claude Sonnet 4.6 ≈ $3/M input tokens. Images ~1.6k tokens each
(at 1568×1568 max). 3 frames/window × 20 windows ≈ 100k input ≈ $0.30 per
video on a 1h tutorial. More expensive than Gemini File API but doesn't
hit Gemini's daily free-tier quota wall.
"""
from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from skills.neurolearn.backends.vision_base import VisionBackend, VisualSegment
from skills.neurolearn.detection.base import DetectionWindow
from skills.neurolearn.vision import frames as frames_mod
from skills.neurolearn.vision.prompts import format_prompt


@dataclass
class ClaudeVisionBackend:
    api_key: str
    model: str = "claude-sonnet-4-6"
    frames_per_window: int = 3
    max_retries: int = 3
    max_tokens: int = 1024

    def annotate_segments(
        self,
        video_path: Path,
        windows: list[DetectionWindow],
        prompt_template: str,
        language: str,
        video_id: str,
        out_dir: Path,
    ) -> list[VisualSegment]:
        from anthropic import Anthropic
        client = Anthropic(api_key=self.api_key)

        frames_dir = out_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        out: list[VisualSegment] = []
        for w in windows:
            try:
                keyframes = frames_mod.extract_keyframes(
                    video_path=video_path,
                    start=w.start,
                    end=w.end,
                    count=self.frames_per_window,
                    out_dir=frames_dir,
                    video_id=video_id,
                )
            except Exception:
                continue
            if not keyframes:
                continue

            prompt = format_prompt(
                prompt_template,
                language=language,
                transcript_snippet=w.phrase or "(window from scene change)",
                start_sec=w.start,
                end_sec=w.end,
            )

            content = self._build_content(keyframes, prompt)
            description, key_objects, importance = self._call_with_retry(
                client, content,
            )
            rel_keyframes = [f"frames/{p.name}" for p in keyframes]
            out.append(VisualSegment(
                start=w.start,
                end=w.end,
                description=description,
                keyframes=rel_keyframes,
                detected_objects=key_objects,
                trigger_reason=w.reason,
                importance=importance,
            ))
        return out

    @staticmethod
    def _build_content(keyframes: list[Path], prompt: str) -> list[dict]:
        """Pack images + text into Anthropic messages content blocks."""
        content: list[dict] = []
        for kf in keyframes:
            data = base64.b64encode(kf.read_bytes()).decode("ascii")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": data,
                },
            })
        content.append({"type": "text", "text": prompt})
        return content

    def _call_with_retry(
        self, client, content: list[dict],
    ) -> tuple[str, list[str], str]:
        backoffs = [3.0, 6.0, 12.0]
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": content}],
                )
                # Anthropic returns a list of content blocks; pick text
                text_blocks = [
                    b.text for b in resp.content
                    if getattr(b, "type", None) == "text"
                ]
                return self._parse_response("".join(text_blocks))
            except Exception as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    time.sleep(backoffs[attempt])
        return f"(error: {last_err})", [], "medium"

    @staticmethod
    def _parse_response(text: str) -> tuple[str, list[str], str]:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```\s*$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text, [], "medium"
        desc = str(data.get("description", text))[:2000]
        ko = data.get("key_objects", [])
        if not isinstance(ko, list):
            ko = []
        importance = data.get("importance", "medium")
        if importance not in ("low", "medium", "high"):
            importance = "medium"
        return desc, [str(o) for o in ko], importance
