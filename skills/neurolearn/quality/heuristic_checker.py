"""Composite QualityChecker — aggregates spell + repetition + BoH + non-speech."""
from __future__ import annotations

from dataclasses import dataclass

from skills.neurolearn.quality.base import (
    QualityReport,
    Recommendation,
    TranscriptSource,
)
from skills.neurolearn.quality.boh import bag_of_hallucinations_coverage
from skills.neurolearn.quality.repetition import (
    non_speech_marker_ratio,
    trigram_repetition_rate,
)
from skills.neurolearn.quality.spell import (
    is_language_supported,
    out_of_vocab_ratio,
)
from skills.neurolearn.utils.output_writer import Segment


@dataclass
class HeuristicChecker:
    """Default QualityChecker implementation. Local, no network.

    Perplexity (kirpich F per spec §3) is OFF by default. Pass
    `enable_perplexity=True` to activate — requires `[perplexity]` extra
    and triggers ~500 MB GPT-2 download on first call (English only).
    """

    music_threshold: float = 0.25
    oov_threshold: float = 0.15
    rep_threshold: float = 0.3
    boh_threshold: float = 0.1
    perplexity_threshold: float = 0.5
    enable_perplexity: bool = False

    def check(
        self,
        segments: list[Segment],
        language: str,
        source: TranscriptSource,
    ) -> QualityReport:
        if source == "youtube_manual":
            return QualityReport(
                score=1.0,
                breakdown={"reason": "manual_captions"},
                flags=[],
                recommendation="use_as_is",
            )

        text = " ".join(s.text for s in segments)
        breakdown: dict[str, float] = {}
        flags: list[str] = []

        music = non_speech_marker_ratio(segments)
        breakdown["music"] = music
        if music > self.music_threshold:
            flags.append("mostly_music")
            return QualityReport(
                score=0.3,
                breakdown=breakdown,
                flags=flags,
                recommendation="fallback_recommended",
            )

        oov = out_of_vocab_ratio(text, language) if is_language_supported(language) else -1.0
        rep = trigram_repetition_rate(text)
        boh = bag_of_hallucinations_coverage(text)

        breakdown["oov"] = oov
        breakdown["repetition"] = rep
        breakdown["boh"] = boh

        # Weights (sum 1.0). If language is unsupported, OOV is disabled — re-weight.
        if oov < 0:
            oov_component = 0.5  # neutral
            score = (
                0.4 * (1 - min(rep / self.rep_threshold, 1.0)) +
                0.4 * (1 - min(boh / self.boh_threshold, 1.0)) +
                0.2 * oov_component
            )
        else:
            score = (
                0.40 * (1 - min(oov / self.oov_threshold, 1.0)) +
                0.30 * (1 - min(rep / self.rep_threshold, 1.0)) +
                0.30 * (1 - min(boh / self.boh_threshold, 1.0))
            )
            if oov > self.oov_threshold:
                flags.append("high_oov")

        if rep > self.rep_threshold:
            flags.append("looped")
        if boh > self.boh_threshold:
            flags.append("boilerplate_hallucinations")

        # Perplexity (opt-in) — penalty term, never boost.
        if self.enable_perplexity:
            from skills.neurolearn.quality.perplexity import (
                is_perplexity_available_for_lang,
                perplexity_anomaly_score,
            )
            if is_perplexity_available_for_lang(language):
                ppl = perplexity_anomaly_score(segments, language)
                breakdown["perplexity"] = ppl
                if ppl >= 0:
                    if ppl > self.perplexity_threshold:
                        flags.append("high_perplexity")
                    # Penalty: subtract up to 0.25 from score for fully-anomalous text.
                    score = max(score - 0.25 * ppl, 0.0)

        rec: Recommendation = (
            "use_as_is" if score >= 0.6
            else "fallback_recommended" if score >= 0.3
            else "low_quality"
        )
        return QualityReport(score=score, breakdown=breakdown, flags=flags, recommendation=rec)
