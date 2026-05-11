"""LLM-based translation of YouTube search queries between languages.

Translates the user's single query to each requested target language
via the same LLM backend used for analyze/filter. Falls back to the
original query if the LLM returns nothing useful.
"""
from __future__ import annotations

from skills.youtube_transcribe.analyze.runner import run_analysis


def detect_language(text: str) -> str | None:
    """Best-effort language detection. Returns ISO 639-1 code or None."""
    if not text or len(text.strip()) < 3:
        return None
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0  # reproducible
        return detect(text)
    except Exception:
        return None


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
    backend: str,
    api_key: str | None,
    ollama_model: str = "llama3.2:3b",
    ollama_host: str = "http://localhost:11434",
) -> dict[str, str]:
    """Return {lang_code: query_string} for each language in `languages`.

    The language matching the detected source-language gets the query as-is.
    If detection fails, the first language in `languages` is treated as the
    anchor (no translation), others are translated.
    """
    if not languages:
        return {}

    detected = detect_language(query)
    anchor = detected if detected in languages else languages[0]

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
