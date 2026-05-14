"""Tests for BudgetTracker — token accounting + price math."""
from skills.neurolearn.budget import BudgetTracker, CallRecord


def test_record_single_gemini_call_costs_correctly():
    """1500 prompt tokens + 200 output tokens on gemini-2.5-flash
    should cost: 1500/1M * $0.30 + 200/1M * $2.50 = $0.00045 + $0.0005 = $0.00095."""
    t = BudgetTracker()
    t.record(
        "vision_gemini", "gemini-2.5-flash",
        prompt_tokens=1500, output_tokens=200,
    )
    assert abs(t.total_cost_usd() - 0.00095) < 1e-9


def test_cached_tokens_get_discount():
    """800 of 1500 prompt tokens cached → only 700 billed at full rate,
    800 at 25% rate."""
    r = CallRecord(
        stage="vision_gemini",
        model="gemini-2.5-flash",
        prompt_tokens=1500,
        output_tokens=200,
        cached_tokens=800,
    )
    expected = (
        700 / 1_000_000 * 0.30
        + 800 / 1_000_000 * 0.30 * 0.25
        + 200 / 1_000_000 * 2.50
    )
    assert abs(r.cost_usd() - expected) < 1e-9


def test_unknown_model_costs_zero():
    """Unknown provider keys should fail open (don't crash the pipeline)."""
    r = CallRecord(
        stage="vision_gemini", model="some-future-model-2030",
        prompt_tokens=10_000, output_tokens=1_000,
    )
    assert r.cost_usd() == 0.0


def test_by_stage_aggregates_correctly():
    """Multiple calls in same stage sum into one slot."""
    t = BudgetTracker()
    t.record("vision_gemini", "gemini-2.5-flash",
             prompt_tokens=1000, output_tokens=100)
    t.record("vision_gemini", "gemini-2.5-flash",
             prompt_tokens=2000, output_tokens=300)
    t.record("analyze", "claude-sonnet-4-6",
             prompt_tokens=5000, output_tokens=800)
    by = t.by_stage()
    assert by["vision_gemini"]["calls"] == 2
    assert by["vision_gemini"]["prompt_tokens"] == 3000
    assert by["vision_gemini"]["output_tokens"] == 400
    assert by["analyze"]["calls"] == 1
    assert by["analyze"]["prompt_tokens"] == 5000


def test_summary_shape():
    """summary() must return a JSON-serialisable dict suitable for manifest.json."""
    t = BudgetTracker()
    t.record("vision_gemini", "gemini-2.5-flash",
             prompt_tokens=1000, output_tokens=100, cached_tokens=500)
    s = t.summary()
    assert set(s) == {"total_cost_usd", "total_calls", "by_stage"}
    assert s["total_calls"] == 1
    assert "vision_gemini" in s["by_stage"]
    assert s["by_stage"]["vision_gemini"]["cached_tokens"] == 500


def test_empty_tracker_total_zero():
    """No calls recorded → no cost, no errors."""
    t = BudgetTracker()
    assert t.total_cost_usd() == 0.0
    assert t.summary() == {
        "total_cost_usd": 0.0, "total_calls": 0, "by_stage": {},
    }
