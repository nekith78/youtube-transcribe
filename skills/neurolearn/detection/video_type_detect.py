"""Heuristic video-type classifier — chooses one of 9 known types.

Pure-function, free, runs after transcription and before the visual
stage. Each type has a set of `signals` (regex patterns) we count in
the transcript. The type with the highest normalized score wins, OR we
fall back to `generic` when no type passes its confidence threshold.

This is intentionally simple — we don't ship a real classifier model.
The signals are tuned for cheap precision: a tutorial detection at
1.5 actions/min is robust; a lecture detection at 0.3 lecture-phrases/min
is intentionally permissive to catch even sparse academic content.

Decision lives close to the prompt selection: if you're adding a new
video type to `prompts_default.toml`, add a section here too.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Signal vocabularies. Each list is a small set of patterns chosen for
# precision — words that strongly indicate the type without ambiguity.
# ---------------------------------------------------------------------------

# UI action verbs in en / ru — same set already used by tutorial_detect.py.
_TUTORIAL_SIGNALS = [
    r"\bкл(ик|икае(м|шь)|икни|икни(те)?)\b",
    r"\bнажм[уём]\b", r"\bнажима(ем|ешь|й)\b",
    r"\bжмём?\b", r"\bвыбира(ем|ешь|й)\b",
    r"\bвыбер(ем|и|ите)\b", r"\bввод(им|ишь|и)\b",
    r"\bпиш(ем|ешь|и|ите)\b", r"\bнапиш(ем|и|ите)\b",
    r"\bоткр(оем|ываешь|ой|ойте|ываем)\b",
    r"\bзакр(оем|ываешь|ой|ойте|ываем)\b",
    r"\bперех(одим|одишь|оди|одите)\b",
    r"\bсохран(яем|и|ишь|ите|им)\b",
    r"\bкопир(уем|ую|уй|уйте)\b",
    r"\bвст(авляем|авь|авьте)\b",
    r"\bclick(ing|s|ed)?\b", r"\btap(ping|s|ped)?\b",
    r"\bpress(ing|es|ed)?\b", r"\bselect(ing|s|ed)?\b",
    r"\bchoos(e|ing|es)\b", r"\btyp(e|ing|es|ed)\b",
    r"\bopen(ing|s|ed)?\b", r"\bclos(e|ing|es|ed)\b",
    r"\bnavigat(e|ing|es|ed)\b", r"\bgo to\b",
    r"\bsav(e|ing|es|ed)\b", r"\bcop(y|ying|ies|ied)\b",
    r"\bpast(e|ing|es|ed)\b",
    r"\bscroll(ing|s|ed)?\b",
]

# Lecture / talk vocabulary — pedagogical framing words.
_LECTURE_SIGNALS = [
    r"\btoday (we'll|we will|i'll)\b", r"\bin this (lecture|talk)\b",
    r"\bresearch shows\b", r"\bstud(y|ies) (show|suggest)\b",
    r"\bhypothes(is|es)\b", r"\bin this slide\b", r"\bnext slide\b",
    r"\bas you can see (in|on) the (slide|chart|graph|figure)\b",
    r"\bthe (concept|principle|theorem|equation|formula)\b",
    r"\bлекци[яи]\b", r"\bсегодня (мы|я) (поговорим|расскаж)\b",
    r"\bисследовани[ея] показ\b", r"\bпринц[иы]п\b",
    r"\bна слайде\b", r"\bна графике\b", r"\bна диаграмме\b",
    r"\bтеори[яи]\b",
]

# Code / programming vocabulary.
_CODE_SIGNALS = [
    r"\bfunction\b", r"\bclass\b", r"\bimport\b",
    r"\breturn\b", r"\bvariable\b", r"\bparameter\b",
    r"\bdef \b", r"\bconst \b", r"\blet \b", r"\bvar \b",
    r"\barray\b", r"\bobject\b",
    r"\berror\b", r"\bexception\b", r"\bstack trace\b",
    r"\bcomp(il)?e\b", r"\bdebug(ging|ger)?\b",
    r"\bcommand line\b", r"\bterminal\b", r"\b(npm|pip|cargo|yarn)\s+(install|run)\b",
    r"\b(github|repository|repo|commit|pull request)\b",
    r"\bфункци[яи]\b", r"\bкласс\b", r"\bперемен(ная|ной)\b",
    r"\bошибк(а|и)\b", r"\bдебаг\b", r"\bкод\b",
]

# Product demo / feature showcase.
_DEMO_SIGNALS = [
    r"\b(new|new feature|just launched|introducing|announce|release)\b",
    r"\b(beta|alpha|preview|public release)\b",
    r"\b(try it|sign up|get started|free trial)\b",
    r"\b(feature|capability|workflow)\b",
    r"\bsubscri(be|ption)\b", r"\bpricing\b",
    r"\bновая (фича|функция|версия)\b",
    r"\bпредставляем\b", r"\bзапустили\b",
    r"\bпопробу(й|йте|ем)\b", r"\bподписк[ау]\b",
]

# Interview / podcast — dialogue + introductions.
_INTERVIEW_SIGNALS = [
    r"\b(welcome|joining (me|us) today|my guest)\b",
    r"\b(host|guest|interviewer)\b",
    r"\bso (you|your) (work|company|research)\b",
    r"\btell (me|us) about\b",
    r"\bthank you for (joining|coming|being)\b",
    r"\bin your (opinion|view|experience)\b",
    r"\b(добро пожаловать|у нас в гостях|мой гость)\b",
    r"\bрасскажи(те)? о (своей|своём)\b",
    r"\bспасибо что (пришёл|пришли|присоединил)\b",
]

# Vlog / personal content — first-person narration, casual.
_VLOG_SIGNALS = [
    r"\b(today i'm|i decided|i wanted|my day|let me show you my)\b",
    r"\b(yesterday i|this morning i|last week i)\b",
    r"\b(coffee|breakfast|grocery|walking around|street)\b",
    r"\b(home|apartment|kitchen|bedroom)\b",
    r"\b(welcome back to my channel|subscribe to my)\b",
    r"\bсегодня я\b", r"\bвчера я\b", r"\bу меня дома\b",
    r"\bпрогул(ка|яюсь)\b", r"\bна кухне\b",
    r"\bподпишитесь на мой канал\b",
]

# Review / unboxing.
_REVIEW_SIGNALS = [
    r"\b(unbox(ing)?|reviewing|review of)\b",
    r"\bspecs?\b", r"\bbenchmark\b",
    r"\bworth (it|the money)\b", r"\bpros (and|\|) cons\b",
    r"\b(comparison|compared to|versus|vs\.?)\b",
    r"\bin the box\b", r"\bpack(ag(e|ing)|aging)\b",
    r"\bобзор\b", r"\bраспаковк[аи]\b",
    r"\bсравнени[ея]\b", r"\bстоит ли\b",
    r"\bв коробке\b",
]

# Talking head has no positive signal — it's the absence of others.
# We detect it via low density of all the above.


# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TypeRule:
    name: str
    patterns: list[re.Pattern]
    # Density threshold (matches per minute) at which we trigger.
    # Picked permissively per-type — false positives cost a 4× vision
    # bill but no quality loss.
    threshold_per_min: float


_RULES: list[_TypeRule] = [
    _TypeRule(
        "tutorial",
        [re.compile(p, re.IGNORECASE) for p in _TUTORIAL_SIGNALS],
        threshold_per_min=1.5,
    ),
    _TypeRule(
        "code",
        [re.compile(p, re.IGNORECASE) for p in _CODE_SIGNALS],
        # Lower threshold — programmer videos use these words densely.
        threshold_per_min=2.0,
    ),
    _TypeRule(
        "lecture",
        [re.compile(p, re.IGNORECASE) for p in _LECTURE_SIGNALS],
        threshold_per_min=0.5,
    ),
    _TypeRule(
        "demo",
        [re.compile(p, re.IGNORECASE) for p in _DEMO_SIGNALS],
        threshold_per_min=0.5,
    ),
    _TypeRule(
        "review",
        [re.compile(p, re.IGNORECASE) for p in _REVIEW_SIGNALS],
        threshold_per_min=0.5,
    ),
    _TypeRule(
        "interview",
        [re.compile(p, re.IGNORECASE) for p in _INTERVIEW_SIGNALS],
        threshold_per_min=0.4,
    ),
    _TypeRule(
        "vlog",
        [re.compile(p, re.IGNORECASE) for p in _VLOG_SIGNALS],
        threshold_per_min=0.4,
    ),
]


# Minimum density below which we don't trust ANY positive class —
# the transcript has too few signals to be confident. Caller treats
# this as "fall back to talking_head" if duration ≥ 1 min, else "generic".
_NO_CLASS_DENSITY_FLOOR = 0.3


@dataclass(frozen=True)
class VideoTypeSignals:
    """Result of running classification on a transcript."""
    video_type: str
    confidence: float       # 0-1; 1.0 = density >> threshold, 0 = no signal
    duration_min: float
    counts_per_type: dict[str, int] = field(default_factory=dict)
    densities_per_type: dict[str, float] = field(default_factory=dict)


def detect_video_type(segments) -> VideoTypeSignals:
    """Classify the transcript into one of the 9 known video types.

    `segments` is the list of TranscriptionResult.segments — each has
    `.text` and `.start`/`.end` (seconds).

    Returns VideoTypeSignals with `video_type` set to the winning class
    OR to 'generic' (and 'talking_head' for long videos with no
    positive class signal — the canonical "person sitting and talking"
    case the user named).
    """
    if not segments:
        return VideoTypeSignals(
            video_type="generic", confidence=0.0, duration_min=0.0,
        )

    last_end = float(getattr(segments[-1], "end", 0.0) or 0.0)
    duration_min = max(last_end / 60.0, 0.1)

    counts: dict[str, int] = {}
    densities: dict[str, float] = {}
    scores: dict[str, float] = {}

    for rule in _RULES:
        count = 0
        for seg in segments:
            text = getattr(seg, "text", "") or ""
            # One match per segment per rule — don't double-count
            # several action verbs in one sentence.
            for pat in rule.patterns:
                if pat.search(text):
                    count += 1
                    break
        counts[rule.name] = count
        density = count / duration_min
        densities[rule.name] = round(density, 2)
        # Score = density / threshold, clipped to [0, 5]. The class with
        # highest score wins, provided it's > 1.0 (above its threshold).
        score = density / rule.threshold_per_min if rule.threshold_per_min > 0 else 0
        scores[rule.name] = min(score, 5.0)

    # Pick the winner.
    if scores:
        winner = max(scores, key=scores.get)
        winner_score = scores[winner]
    else:
        winner, winner_score = "generic", 0.0

    # Decide outcome.
    if winner_score >= 1.0:
        # Above its threshold — confident enough.
        # Cap confidence at 1.0; map score 1.0→0.5, 2.0→0.7, 5.0→1.0.
        confidence = min(1.0, 0.4 + 0.15 * winner_score)
        return VideoTypeSignals(
            video_type=winner,
            confidence=round(confidence, 2),
            duration_min=round(duration_min, 2),
            counts_per_type=counts,
            densities_per_type=densities,
        )

    # No class crossed its threshold. If the video is long enough,
    # call it talking_head — the canonical "person sitting and talking"
    # mode. Otherwise (short clip with no signal), generic.
    total_signals = sum(counts.values())
    overall_density = total_signals / duration_min
    if duration_min >= 1.0 and overall_density < _NO_CLASS_DENSITY_FLOOR:
        return VideoTypeSignals(
            video_type="talking_head",
            confidence=0.5,
            duration_min=round(duration_min, 2),
            counts_per_type=counts,
            densities_per_type=densities,
        )

    return VideoTypeSignals(
        video_type="generic",
        confidence=0.0,
        duration_min=round(duration_min, 2),
        counts_per_type=counts,
        densities_per_type=densities,
    )
