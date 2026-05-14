"""Perplexity-based anomaly detection for transcripts (spec §3 brick F).

Uses HuggingFace `transformers` (already pulled by sentence-transformers
core dep) to compute per-segment perplexity via a small causal LM.
GPT-2 small (~500 MB) is the default for English.

Garbled ASR output gives perplexity ~5-10x normal text — we detect that.
Non-supported languages return -1.0 sentinel; HeuristicChecker skips
the brick silently.

Opt-in via `enable_perplexity=True` in HeuristicChecker, or
`quality_perplexity = true` in preset / config.
"""
from __future__ import annotations

from functools import lru_cache

from skills.neurolearn.utils.output_writer import Segment

_LANG_MODELS: dict[str, str] = {
    "en": "gpt2",                                          # ~500 MB
    "ru": "sberbank-ai/rugpt3small_based_on_gpt2",         # ~550 MB
    # Add more entries when models are proven to work cross-platform without
    # heavy GPU. (mGPT/XGLM are 1.4 GB+ — too big for opt-in default.)
}


def is_perplexity_available_for_lang(lang: str) -> bool:
    """True if a model is configured for this language AND transformers importable."""
    if lang not in _LANG_MODELS:
        return False
    try:
        import transformers  # noqa: F401
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=2)
def _get_lm(lang: str):
    """Lazy-load (tokenizer, model) for the given language. Returns None if unavailable.

    Triggers ~500 MB GPT-2 download on first call. Model runs on CPU.
    """
    model_name = _LANG_MODELS.get(lang)
    if model_name is None:
        return None
    try:
        from transformers import AutoTokenizer, AutoModelForCausalLM
        tok = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_pretrained(model_name)
        model.eval()
        return tok, model
    except Exception:
        return None


def _compute_perplexity(text: str, tokenizer, model) -> float | None:
    """Per-segment perplexity. Returns None on failure or if text too short."""
    import torch
    text = text.strip()
    if len(text) < 3:
        return None
    try:
        enc = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        if enc["input_ids"].shape[1] < 2:
            return None
        with torch.no_grad():
            outputs = model(**enc, labels=enc["input_ids"])
        loss = outputs.loss
        return float(torch.exp(loss))
    except Exception:
        return None


def perplexity_anomaly_score(segments: list[Segment], lang: str) -> float:
    """Returns 0.0..1.0 (lower is better) or -1.0 if unsupported.

    Strategy:
      - Compute mean per-segment perplexity via transformers + GPT-2.
      - Normal English speech transcripts: GPT-2 PPL roughly 30-150.
      - Garbled ASR (looped/garbled words): >500.
      - Return min(mean_ppl / 500, 1.0) — bounded score where 1.0 = very bad.
    """
    if lang not in _LANG_MODELS:
        return -1.0
    lm = _get_lm(lang)
    if lm is None:
        return -1.0
    tokenizer, model = lm

    texts = [s.text.strip() for s in segments if s.text.strip()]
    if not texts:
        return 0.0

    perps = []
    for t in texts:
        p = _compute_perplexity(t, tokenizer, model)
        if p is not None:
            perps.append(p)

    if not perps:
        return 0.0

    mean_ppl = sum(perps) / len(perps)
    # Calibration based on observed GPT-2 PPL on real data:
    #   normal English speech transcripts: 30-80
    #   ASR with truncated/garbled words: 100-200
    #   nonsense / wrong language: 200+
    # Subtract baseline (50) so normal text gets ~0 penalty,
    # divide by 150 so PPL>=200 saturates at 1.0.
    return min(max((mean_ppl - 50.0) / 150.0, 0.0), 1.0)
