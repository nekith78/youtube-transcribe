"""OpenAIVisionBackend — multimodal annotation via GPT-4o vision.

Like ClaudeVisionBackend: images-only, keyframes via ffmpeg, base64 data
URLs in chat.completions content blocks.

Cost note: GPT-4o ≈ $2.50/M input tokens (Nov 2025 pricing).
Images ~765 tokens each at default detail. 3 frames × 20 windows ≈
50k tokens ≈ $0.13 per video on 1h tutorial. Between Gemini (~$0.07) and
Claude (~$0.30) — middle-priced option with mature SDK.
"""
from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from skills.youtube_transcribe.backends.vision_base import VisionBackend, VisualSegment
from skills.youtube_transcribe.detection.base import DetectionWindow
from skills.youtube_transcribe.vision import frames as frames_mod
from skills.youtube_transcribe.vision.prompts import format_prompt


@dataclass
class OpenAIVisionBackend:
    api_key: str
    model: str = "gpt-4o"
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
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key)

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
        """Pack images + text into OpenAI chat.completions content blocks."""
        content: list[dict] = []
        for kf in keyframes:
            data = base64.b64encode(kf.read_bytes()).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{data}"},
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
                resp = client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": content}],
                )
                text = (resp.choices[0].message.content or "") if resp.choices else ""
                return self._parse_response(text)
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
