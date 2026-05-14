"""Bag of Hallucinations: catch known Whisper boilerplate hallucinations.

Reference: https://arxiv.org/html/2501.11378v1
"""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

import ahocorasick


@lru_cache(maxsize=1)
def _build_automaton() -> ahocorasick.Automaton:
    text = files("skills.neurolearn.quality.data").joinpath("boh_phrases.txt").read_text(
        encoding="utf-8"
    )
    phrases = [
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    auto = ahocorasick.Automaton()
    for idx, phrase in enumerate(phrases):
        auto.add_word(phrase, (idx, phrase))
    auto.make_automaton()
    return auto


def bag_of_hallucinations_coverage(text: str) -> float:
    """Returns 0..1 — fraction of text characters covered by BoH phrases.

    Sums lengths of all hallucination matches (without overlapping double-count
    by tracking covered character positions), divided by total text length.
    """
    if not text:
        return 0.0
    text_lower = text.lower()
    auto = _build_automaton()
    covered = bytearray(len(text_lower))  # bitmap of covered chars
    for end_idx, (_, phrase) in auto.iter(text_lower):
        start_idx = end_idx - len(phrase) + 1
        for i in range(start_idx, end_idx + 1):
            covered[i] = 1
    return sum(covered) / len(text_lower) if text_lower else 0.0
