"""Budget tracker — record token usage and cost per pipeline run.

Aggregates per-call usage from vision backends + analyze runner + ASR
correction LLM and converts into USD via published per-million-token
prices for each provider.

Output goes into `manifest.json` so users can see exactly what each
batch cost without spelunking through provider dashboards.

Prices (as of 2026-05 — refresh when providers re-price):
  gemini-2.5-flash : $0.30 / 1M input,  $2.50 / 1M output
                     50% off via Batch API (not modeled — opt-in)
                     75% off on cached input tokens
  claude-sonnet-4.6: $3.00 / 1M input,  $15.00 / 1M output
  claude-haiku-4.5 : $0.80 / 1M input,  $4.00 / 1M output
  gpt-4o           : $2.50 / 1M input,  $10.00 / 1M output
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Literal


_PROVIDER_PRICES: dict[str, tuple[float, float]] = {
    # (input_per_million_usd, output_per_million_usd)
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro":   (1.25, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5":  (0.80, 4.00),
    "gpt-4o":            (2.50, 10.00),
    "gpt-4o-mini":       (0.15, 0.60),
}

# Cached input tokens are billed at ~25% of normal rate on Gemini. Keep
# the math simple: cached → 0.25× input cost.
_CACHE_DISCOUNT = 0.25


VisionStage = Literal[
    "vision_gemini", "vision_claude", "vision_openai",
    "analyze", "asr_correction", "translate", "filter", "research_translate",
]


@dataclass
class CallRecord:
    """One LLM-call worth of metering."""
    stage: VisionStage
    model: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0    # subset of prompt_tokens billed at discount

    def cost_usd(self) -> float:
        prices = _PROVIDER_PRICES.get(self.model)
        if prices is None:
            return 0.0
        in_rate, out_rate = prices
        fresh_prompt = max(0, self.prompt_tokens - self.cached_tokens)
        return (
            fresh_prompt / 1_000_000 * in_rate
            + self.cached_tokens / 1_000_000 * in_rate * _CACHE_DISCOUNT
            + self.output_tokens / 1_000_000 * out_rate
        )


@dataclass
class BudgetTracker:
    """Accumulates CallRecords for one pipeline run.

    Usage:
        tracker = BudgetTracker()
        tracker.record("vision_gemini", "gemini-2.5-flash",
                       prompt_tokens=1500, output_tokens=200,
                       cached_tokens=800)
        ...
        tracker.summary()  # → dict with totals + per-stage breakdown
    """
    records: list[CallRecord] = field(default_factory=list)

    def record(
        self,
        stage: VisionStage,
        model: str,
        *,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
    ) -> None:
        self.records.append(CallRecord(
            stage=stage,
            model=model,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        ))

    def total_cost_usd(self) -> float:
        return sum(r.cost_usd() for r in self.records)

    def by_stage(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in self.records:
            slot = out.setdefault(r.stage, {
                "calls": 0,
                "prompt_tokens": 0,
                "output_tokens": 0,
                "cached_tokens": 0,
                "cost_usd": 0.0,
            })
            slot["calls"] += 1
            slot["prompt_tokens"] += r.prompt_tokens
            slot["output_tokens"] += r.output_tokens
            slot["cached_tokens"] += r.cached_tokens
            slot["cost_usd"] += r.cost_usd()
        for slot in out.values():
            slot["cost_usd"] = round(slot["cost_usd"], 6)
        return out

    def summary(self) -> dict:
        """Compact dict for embedding into manifest.json."""
        return {
            "total_cost_usd": round(self.total_cost_usd(), 6),
            "total_calls": len(self.records),
            "by_stage": self.by_stage(),
        }
