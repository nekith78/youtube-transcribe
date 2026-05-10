"""Trigger matching: raw (any lang exact) + strict (per-lang exact) +
soft (per-lang lemmatized) + universal (cross-lingual embeddings).

Embeddings + lemmatization are added in Tasks 11-12.
"""
from __future__ import annotations

from dataclasses import dataclass

import ahocorasick

from skills.youtube_transcribe.detection.triggers import TriggerConfig


@dataclass(frozen=True)
class TriggerMatch:
    score: float           # 0..1, базовый
    weight: float          # из TOML, default 1.0
    reason: str            # "raw" | "strict:ru" | "soft:ru" | "universal"
    phrase: str            # фраза, которая сработала


def _build_raw_automaton(cfg: TriggerConfig) -> ahocorasick.Automaton | None:
    if not cfg.raw:
        return None
    auto = ahocorasick.Automaton()
    for phrase, weight in cfg.raw.items():
        auto.add_word(phrase.lower(), (phrase.lower(), weight))
    auto.make_automaton()
    return auto


def _build_strict_automaton(cfg: TriggerConfig, lang: str) -> ahocorasick.Automaton | None:
    lang_cfg = cfg.languages.get(lang)
    if not lang_cfg or not lang_cfg.strict:
        return None
    auto = ahocorasick.Automaton()
    for phrase, weight in lang_cfg.strict.items():
        auto.add_word(phrase.lower(), (phrase.lower(), weight))
    auto.make_automaton()
    return auto


def _match_aho(text: str, auto: ahocorasick.Automaton | None) -> tuple[str, float] | None:
    """Find first match. Returns (phrase, weight) or None."""
    if auto is None or not text:
        return None
    text_lower = text.lower()
    for _end_idx, value in auto.iter(text_lower):
        return value
    return None


# === Lemmatization-based soft matching ===

from functools import lru_cache


@lru_cache(maxsize=4)
def _get_lemmatizer(lang: str):
    """Lazy lemmatizer per language. None if unsupported."""
    if lang == "en":
        try:
            from lemminflect import getLemma  # noqa: F401
            return ("lemminflect", None)
        except ImportError:
            return None
    if lang == "ru":
        try:
            import pymorphy3
            return ("pymorphy3", pymorphy3.MorphAnalyzer())
        except ImportError:
            return None
    return None


def _normalize_ru_token(analyzer, tok: str) -> str:
    """Get normal form, stripping perfective 'по-' prefix when it yields a valid verb."""
    nf = analyzer.parse(tok)[0].normal_form
    if nf.startswith("по") and len(nf) > 3:
        candidate = nf[2:]
        for p in analyzer.parse(candidate):
            if "VERB" in str(p.tag) or "INFN" in str(p.tag):
                return candidate
    return nf


def _lemmatize(text: str, lang: str) -> str:
    """Tokenize, lemmatize, return space-joined lemmas. Empty string if unsupported."""
    info = _get_lemmatizer(lang)
    if info is None:
        return ""
    lib, analyzer = info
    tokens = text.lower().split()
    if lib == "lemminflect":
        from lemminflect import getLemma
        # Skip determiners/articles that lemminflect handles poorly
        _EN_SKIP = {"the", "a", "an", "this", "that", "these", "those"}
        out = []
        for tok in tokens:
            if tok in _EN_SKIP:
                continue
            lemmas = getLemma(tok, upos="VERB") or getLemma(tok, upos="NOUN") or [tok]
            out.append(lemmas[0])
        return " ".join(out)
    if lib == "pymorphy3":
        return " ".join(_normalize_ru_token(analyzer, tok) for tok in tokens)
    return ""


def _match_soft(text: str, cfg: TriggerConfig, lang: str) -> tuple[str, float] | None:
    lang_cfg = cfg.languages.get(lang)
    if not lang_cfg or not lang_cfg.soft:
        return None
    text_lemmas = _lemmatize(text, lang)
    if not text_lemmas:
        return None
    for phrase, weight in lang_cfg.soft.items():
        phrase_lemmas = _lemmatize(phrase, lang)
        if phrase_lemmas and phrase_lemmas in text_lemmas:
            return phrase, weight
    return None


# === Universal cross-lingual embedding match ===

import numpy as np

_ENCODER_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=1)
def _get_encoder():
    """Lazy-load embedding model. ~118MB download on first call."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(_ENCODER_MODEL)


@lru_cache(maxsize=1)
def _get_universal_embeddings_cached(phrases_tuple: tuple[str, ...]):
    """Cache by hash of sorted phrases tuple."""
    encoder = _get_encoder()
    return encoder.encode(list(phrases_tuple))


def _cosine(a, b) -> float:
    """Single-vector cosine similarity."""
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))


def _match_universal(text: str, cfg: TriggerConfig) -> tuple[str, float, float] | None:
    """Returns (phrase, score, weight) or None."""
    if not cfg.universal:
        return None

    phrases = list(cfg.universal.keys())
    encoder = _get_encoder()
    phrase_embs = _get_universal_embeddings_cached(tuple(phrases))
    text_emb = np.array(encoder.encode(text)).reshape(-1)  # ensure 1-D

    sims = [_cosine(text_emb, np.array(pe).reshape(-1)) for pe in phrase_embs]
    best_idx = int(np.argmax(sims))
    best_score = float(sims[best_idx])

    if best_score < cfg.universal_match_threshold:
        return None
    phrase = phrases[best_idx]
    return phrase, best_score, cfg.universal[phrase]
