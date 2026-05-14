"""GeminiVisionBackend — multimodal annotation via Gemini File API."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from google import genai

from skills.neurolearn.backends.vision_base import VisionBackend, VisualSegment
from skills.neurolearn.detection.base import DetectionWindow
from skills.neurolearn.vision import frames as frames_mod
from skills.neurolearn.vision.prompts import format_prompt


@dataclass
class GeminiVisionBackend:
    api_key: str
    model: str = "gemini-2.5-flash"
    frames_per_window: int = 3
    max_retries: int = 3

    def annotate_segments(
        self,
        video_path: Path,
        windows: list[DetectionWindow],
        prompt_template: str,
        language: str,
        video_id: str,
        out_dir: Path,
    ) -> list[VisualSegment]:
        client = genai.Client(api_key=self.api_key)
        # Upload video once, use for all windows
        try:
            uploaded = client.files.upload(file=str(video_path))
        except Exception as e:
            # Failure to upload — skip vision annotation entirely
            return []

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

            description, key_objects, importance = self._call_with_retry(client, uploaded, prompt)
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

    def _call_with_retry(self, client, uploaded, prompt: str) -> tuple[str, list[str], str]:
        backoffs = [3.0, 6.0, 12.0]
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = client.models.generate_content(
                    model=self.model,
                    contents=[prompt, uploaded],
                )
                return self._parse_response(resp.text or "")
            except Exception as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    time.sleep(backoffs[attempt])
        return f"(error: {last_err})", [], "medium"

    @staticmethod
    def _parse_response(text: str) -> tuple[str, list[str], str]:
        text = text.strip()
        if text.startswith("```"):
            # Strip code fences
            text = "\n".join(line for line in text.split("\n") if not line.startswith("```"))
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
