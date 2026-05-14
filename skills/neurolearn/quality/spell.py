"""Out-of-vocabulary ratio via pyspellchecker.

OOV ratio = % tokens not in language dictionary. High OOV = garbled ASR.
Used as one component of HeuristicChecker.
"""
from __future__ import annotations

import re
from functools import lru_cache

from spellchecker import SpellChecker

# pyspellchecker built-in language codes (as of 0.8.x)
_SUPPORTED_LANGUAGES = {"en", "es", "fr", "pt", "de", "ru", "ar", "eu", "lv", "nl", "it"}

_TOKEN_RE = re.compile(r"\b[a-zA-Zа-яА-ЯёЁ]+\b")


def is_language_supported(lang: str) -> bool:
    return lang in _SUPPORTED_LANGUAGES


@lru_cache(maxsize=8)
def _get_checker(lang: str) -> SpellChecker:
    return SpellChecker(language=lang)


def out_of_vocab_ratio(text: str, lang: str) -> float:
    """Returns 0.0..1.0 (lower is better) or -1.0 if language unsupported.

    Empty/whitespace text returns 1.0 (worst case — caller should treat as bad signal).
    """
    if not is_language_supported(lang):
        return -1.0

    text = text.strip()
    if not text:
        return 1.0

    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    if not tokens:
        return 1.0

    spell = _get_checker(lang)
    unknown = spell.unknown(tokens)
    return len(unknown) / len(tokens)
