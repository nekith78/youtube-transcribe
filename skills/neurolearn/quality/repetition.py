"""3-gram repetition rate (Whisper loop detector) + non-speech marker coverage."""
from __future__ import annotations

import re
from collections import Counter

from skills.neurolearn.utils.output_writer import Segment

_NON_SPEECH_RE = re.compile(
    r"\[Music\]|\[Applause\]|\[Laughter\]|\[laughter\]|\[applause\]|\[music\]|"
    r"\[unintelligible\]|\(unintelligible\)|\[Music playing\]|♪|🎵",
    re.IGNORECASE,
)


def trigram_repetition_rate(text: str) -> float:
    """Returns 0..1 — higher means more looped. Counter most-common trigram / total trigrams.

    Returns 0.0 for texts shorter than 6 tokens (insufficient signal).
    """
    tokens = text.lower().split()
    if len(tokens) < 6:
        return 0.0
    trigrams = list(zip(tokens, tokens[1:], tokens[2:]))
    if not trigrams:
        return 0.0
    counter = Counter(trigrams)
    most_common_count = counter.most_common(1)[0][1]
    return most_common_count / len(trigrams)


def non_speech_marker_ratio(segments: list[Segment]) -> float:
    """Returns 0..1 — fraction of total duration covered by [Music]/♪/etc segments."""
    if not segments:
        return 0.0
    total_dur = sum(max(s.end - s.start, 0.0) for s in segments)
    if total_dur <= 0:
        return 0.0
    music_dur = sum(
        max(s.end - s.start, 0.0)
        for s in segments
        if _NON_SPEECH_RE.search(s.text)
    )
    return music_dur / total_dur
