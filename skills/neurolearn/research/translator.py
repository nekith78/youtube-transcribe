"""LLM-based translation of YouTube search queries between languages.

Translates the user's single query to each requested target language
via the same LLM backend used for analyze/filter. Falls back to the
original query if the LLM returns nothing useful.

Anchor language detection is **script-based** (Unicode block heuristic),
not statistical — predictable on short cyrillic strings where
`langdetect` historically confused ru with mk/uk/bg.
"""
from __future__ import annotations

from skills.neurolearn.analyze.runner import run_analysis


# Language → writing-script mapping. Anything not in cyrillic/cjk/arabic
# falls back to latin (default for most European languages).
_CYRILLIC_LANGS = frozenset({"ru", "uk", "bg", "sr", "mk", "be", "kk"})
_CJK_LANGS = frozenset({"zh", "ja", "ko"})
_ARABIC_LANGS = frozenset({"ar", "fa", "ur", "he"})


def _script_of_language(lang: str) -> str:
    """Classify ISO language code into a writing script."""
    if lang in _CYRILLIC_LANGS:
        return "cyrillic"
    if lang in _CJK_LANGS:
        return "cjk"
    if lang in _ARABIC_LANGS:
        return "arabic"
    return "latin"


def detect_script(text: str) -> str | None:
    """Detect the dominant script of `text`.

    Returns one of 'cyrillic' / 'latin' / 'cjk' / 'arabic',
    or None for empty / unrecognised input.

    Works reliably on strings of any length (2 chars or 2000), unlike
    statistical language detectors that need longer samples.
    """
    if not text:
        return None
    counts = {"cyrillic": 0, "latin": 0, "cjk": 0, "arabic": 0}
    for ch in text:
        if "Ѐ" <= ch <= "ӿ":
            counts["cyrillic"] += 1
        elif (
            "一" <= ch <= "鿿"   # CJK Unified
            or "぀" <= ch <= "ゟ"  # Hiragana
            or "゠" <= ch <= "ヿ"  # Katakana
            or "가" <= ch <= "힯"  # Hangul
        ):
            counts["cjk"] += 1
        elif (
            "؀" <= ch <= "ۿ"   # Arabic
            or "֐" <= ch <= "׿"  # Hebrew
        ):
            counts["arabic"] += 1
        elif ch.isalpha() and ch.isascii():
            counts["latin"] += 1
    max_count = max(counts.values())
    if max_count == 0:
        return None
    # Stable tie-breaker: cyrillic > cjk > arabic > latin
    # (less ambiguous scripts win; latin is the "default" only when alone)
    for script in ("cyrillic", "cjk", "arabic", "latin"):
        if counts[script] == max_count:
            return script
    return None


def pick_anchor_language(
    source_lang_hint: str | None,
    query: str,
    languages: list[str],
) -> str:
    """Decide which language from `languages` is the anchor (no translation).

    Priority:
    1. Explicit `source_lang_hint` if it appears in `languages`.
    2. Script-detection: pick first language in `languages` whose script
       matches the query's dominant script.
    3. Fallback: first language in `languages`.
    """
    if source_lang_hint and source_lang_hint in languages:
        return source_lang_hint
    script = detect_script(query)
    if script is not None:
        for lang in languages:
            if _script_of_language(lang) == script:
                return lang
    return languages[0]


def translate_query(
    query: str,
    *,
    target: str,
    source: str | None,
    backend: str,
    api_key: str | None,
    ollama_model: str = "llama3.2:3b",
    ollama_host: str = "http://localhost:11434",
) -> str:
    """Translate `query` to `target` language. Returns original if target==source
    or LLM fails."""
    if source and target == source:
        return query

    prompt = (
        f"Translate the following YouTube search query to {target}. "
        "Keep technical terms, product names, and proper nouns intact "
        "(e.g. 'Claude', 'GPT', 'transformers'). "
        "Return ONLY the translated text, no quotes, no explanation.\n\n"
        f"Query: {query}"
    )

    response = run_analysis(
        prompt,
        backend=backend,
        api_key=api_key,
        ollama_model=ollama_model,
        ollama_host=ollama_host,
    )

    text = (response or "").strip()
    if not text:
        return query
    # LLMs sometimes wrap output in quotes — strip them.
    text = text.strip('"').strip("'").strip()
    return text or query


def build_queries_per_language(
    query: str,
    *,
    languages: list[str],
    source_lang_hint: str | None = None,
    backend: str,
    api_key: str | None,
    ollama_model: str = "llama3.2:3b",
    ollama_host: str = "http://localhost:11434",
) -> dict[str, str]:
    """Return {lang_code: query_string} for each language in `languages`.

    Anchor selection (see `pick_anchor_language`):
    - `source_lang_hint` wins if provided and in `languages`.
    - Else dominant script of `query` picks first matching language.
    - Else first language in `languages`.

    Anchor gets the query as-is; everything else is translated via LLM.
    """
    if not languages:
        return {}

    anchor = pick_anchor_language(source_lang_hint, query, languages)

    out: dict[str, str] = {}
    for lang in languages:
        if lang == anchor:
            out[lang] = query
        else:
            out[lang] = translate_query(
                query, target=lang, source=anchor,
                backend=backend, api_key=api_key,
                ollama_model=ollama_model, ollama_host=ollama_host,
            )
    return out
