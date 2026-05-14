"""Heuristic detector — is this video a UI tutorial?

Counts "action phrases" (click, press, нажимаем, выбираем, ...) per
minute of transcript. Above the threshold → caller should switch to
the `tutorial` preset (asymmetric frame offsets + Claude fallback +
tighter vision settings).

The detection is intentionally regex-only and free. It runs after
transcription, before the visual stage, so the decision lands in time
to influence frame extraction and backend choice.

Pure-function module: callers pass a list of segments with text + time
and get back `TutorialSignals` with the density score and decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# Russian and English action verbs that strongly suggest a UI tutorial.
# Word-boundary'd to avoid matching `вот клик-беит` or `clicker`, but
# tolerant of common conjugations.
_ACTION_PATTERNS_RU = [
    r"\bкл(ик|икае(м|шь)|икни|икни(те)?)\b",
    r"\bнажм[уём]\b",
    r"\bнажима(ем|ешь|й)\b",
    r"\bжмём?\b",
    r"\bжмякн[уём]\b",
    r"\bтап(ае(м|шь)|ни|ни(те)?)\b",
    r"\bвыбира(ем|ешь|й)\b",
    r"\bвыбер(ем|и|ите)\b",
    r"\bввод(им|ишь|и)\b",
    r"\bвведи(те)?\b",
    r"\bпиш(ем|ешь|и|ите)\b",
    r"\bнапиш(ем|и|ите)\b",
    r"\bоткр(оем|ываешь|ой|ойте|ываем)\b",
    r"\bзакр(оем|ываешь|ой|ойте|ываем)\b",
    r"\bперех(одим|одишь|оди|одите)\b",
    r"\bсохран(яем|и|ишь|ите|им)\b",
    r"\bкопир(уем|ую|уй|уйте)\b",
    r"\bвст(авляем|авь|авьте)\b",
    r"\bпрокр(учиваем|ути|утите)\b",
    r"\bвыдел(яем|и|ите)\b",
    r"\bпереместим|перетащим|потащим\b",
    r"\bпролист(аем|ай|айте)\b",
]

_ACTION_PATTERNS_EN = [
    r"\bclick(ing|s|ed)?\b",
    r"\btap(ping|s|ped)?\b",
    r"\bpress(ing|es|ed)?\b",
    r"\bselect(ing|s|ed)?\b",
    r"\bchoos(e|ing|es)\b",
    r"\btyp(e|ing|es|ed)\b",
    r"\benter\b",
    r"\bopen(ing|s|ed)?\b",
    r"\bclos(e|ing|es|ed)\b",
    r"\bnavigat(e|ing|es|ed)\b",
    r"\bgo to\b",
    r"\bsav(e|ing|es|ed)\b",
    r"\bcop(y|ying|ies|ied)\b",
    r"\bpast(e|ing|es|ed)\b",
    r"\bdrag(ging|s)?\b",
    r"\bdrop(ping|s|ped)?\b",
    r"\bscroll(ing|s|ed)?\b",
    r"\bhighlight(ing|s|ed)?\b",
    r"\bswitch(ing|es|ed)?\b",
]

_COMPILED_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (_ACTION_PATTERNS_RU + _ACTION_PATTERNS_EN)
]


# A 10-minute UI tutorial with explicit narration typically has 1.5–3
# action mentions per minute. Below 1/min usually means a lecture or
# review, not a tutorial. Threshold of 1.5 is permissive on purpose;
# false positives (lecture mis-classified as tutorial) cost a 4×
# vision token bill but no quality loss.
TUTORIAL_DENSITY_THRESHOLD = 1.5


@dataclass(frozen=True)
class TutorialSignals:
    """Result of running tutorial detection on a transcript."""
    is_tutorial: bool
    action_count: int
    duration_min: float
    density_per_min: float
    sample_matches: list[str]   # up to 5 example matched phrases, for debug logging


def detect_tutorial(segments) -> TutorialSignals:
    """Decide whether the transcript is for a UI tutorial.

    `segments` is the list of TranscriptionResult.segments — each has
    `.text` and `.start`/`.end` (seconds).

    Returns `TutorialSignals` with the density score and a boolean
    decision. Defaults to False on empty / unusably short transcripts.
    """
    if not segments:
        return TutorialSignals(False, 0, 0.0, 0.0, [])

    action_count = 0
    samples: list[str] = []
    for seg in segments:
        text = getattr(seg, "text", "") or ""
        for pattern in _COMPILED_PATTERNS:
            m = pattern.search(text)
            if m:
                action_count += 1
                if len(samples) < 5:
                    samples.append(m.group(0))
                break   # don't double-count one segment

    # Duration = end of last segment in minutes.
    last_end = float(getattr(segments[-1], "end", 0.0) or 0.0)
    duration_min = max(last_end / 60.0, 0.1)
    density = action_count / duration_min

    # Need a meaningful sample: very short clips can't have density.
    is_tutorial = (
        duration_min >= 0.5
        and density >= TUTORIAL_DENSITY_THRESHOLD
    )
    return TutorialSignals(
        is_tutorial=is_tutorial,
        action_count=action_count,
        duration_min=round(duration_min, 2),
        density_per_min=round(density, 2),
        sample_matches=samples,
    )
