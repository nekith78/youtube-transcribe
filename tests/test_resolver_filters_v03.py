"""Tests for v0.3 channel filters in resolver._apply_filters."""
from datetime import date

from skills.youtube_transcribe.utils.resolver import (
    ResolvedTarget,
    ResolverFilters,
    _apply_filters,
)


def _t(*, video_id: str, upload_date=None, duration_sec=None) -> ResolvedTarget:
    return ResolvedTarget(
        url=f"https://youtu.be/{video_id}",
        title=None,
        upload_date=upload_date,
        duration_sec=duration_sec,
        channel=None,
        source="channel",
        video_id=video_id,
    )


# === since ===

def test_since_drops_older_videos():
    targets = [
        _t(video_id="a", upload_date=date(2025, 1, 1)),
        _t(video_id="b", upload_date=date(2026, 5, 1)),
    ]
    filters = ResolverFilters(since=date(2026, 1, 1))
    out = _apply_filters(targets, filters)
    assert [t.video_id for t in out] == ["b"]


def test_since_keeps_unknown_dates():
    """Targets with no upload_date pass — filter is best-effort."""
    targets = [_t(video_id="x", upload_date=None)]
    filters = ResolverFilters(since=date(2026, 1, 1))
    out = _apply_filters(targets, filters)
    assert len(out) == 1


# === until ===

def test_until_drops_newer_videos():
    targets = [
        _t(video_id="a", upload_date=date(2025, 1, 1)),
        _t(video_id="b", upload_date=date(2026, 5, 1)),
    ]
    filters = ResolverFilters(until=date(2026, 1, 1))
    out = _apply_filters(targets, filters)
    assert [t.video_id for t in out] == ["a"]


def test_since_and_until_combined():
    targets = [
        _t(video_id="a", upload_date=date(2024, 1, 1)),  # too old
        _t(video_id="b", upload_date=date(2025, 6, 1)),  # in range
        _t(video_id="c", upload_date=date(2027, 1, 1)),  # too new
    ]
    filters = ResolverFilters(since=date(2025, 1, 1), until=date(2026, 12, 31))
    out = _apply_filters(targets, filters)
    assert [t.video_id for t in out] == ["b"]


# === duration ===

def test_min_duration_drops_short_videos():
    targets = [
        _t(video_id="short", duration_sec=30),
        _t(video_id="long", duration_sec=600),
    ]
    filters = ResolverFilters(min_duration_sec=120)
    out = _apply_filters(targets, filters)
    assert [t.video_id for t in out] == ["long"]


def test_max_duration_drops_long_videos():
    targets = [
        _t(video_id="medium", duration_sec=300),
        _t(video_id="huge", duration_sec=7200),
    ]
    filters = ResolverFilters(max_duration_sec=3600)
    out = _apply_filters(targets, filters)
    assert [t.video_id for t in out] == ["medium"]


def test_duration_filter_skips_unknown():
    """Targets with no duration_sec pass — filter is best-effort."""
    targets = [_t(video_id="x", duration_sec=None)]
    filters = ResolverFilters(min_duration_sec=120, max_duration_sec=600)
    out = _apply_filters(targets, filters)
    assert len(out) == 1


# === shorts ===

def test_no_shorts_drops_short_videos():
    """include_shorts=False → drop videos <= 60s."""
    targets = [
        _t(video_id="short_1", duration_sec=30),
        _t(video_id="short_2", duration_sec=60),
        _t(video_id="reg_1", duration_sec=61),
        _t(video_id="reg_2", duration_sec=600),
    ]
    filters = ResolverFilters(include_shorts=False)
    out = _apply_filters(targets, filters)
    assert [t.video_id for t in out] == ["reg_1", "reg_2"]


def test_include_shorts_default_keeps_all():
    targets = [
        _t(video_id="short", duration_sec=15),
        _t(video_id="reg", duration_sec=600),
    ]
    filters = ResolverFilters()  # include_shorts=True by default
    out = _apply_filters(targets, filters)
    assert len(out) == 2


def test_no_shorts_skips_unknown_duration():
    """Targets with duration_sec=None aren't shorts (we can't tell)."""
    targets = [_t(video_id="unknown", duration_sec=None)]
    filters = ResolverFilters(include_shorts=False)
    out = _apply_filters(targets, filters)
    assert len(out) == 1


# === all combined ===

def test_all_filters_combined():
    targets = [
        _t(video_id="too_old", upload_date=date(2020, 1, 1), duration_sec=300),
        _t(video_id="too_short", upload_date=date(2026, 1, 1), duration_sec=30),
        _t(video_id="too_long", upload_date=date(2026, 1, 1), duration_sec=10000),
        _t(video_id="ok", upload_date=date(2026, 1, 1), duration_sec=300),
    ]
    filters = ResolverFilters(
        since=date(2025, 1, 1),
        min_duration_sec=120,
        max_duration_sec=3600,
        include_shorts=False,
    )
    out = _apply_filters(targets, filters)
    assert [t.video_id for t in out] == ["ok"]


def test_default_filters_keep_all():
    """All defaults → no filtering happens."""
    targets = [
        _t(video_id="a", upload_date=date(2020, 1, 1), duration_sec=10),
        _t(video_id="b", upload_date=date(2030, 1, 1), duration_sec=100000),
    ]
    out = _apply_filters(targets, ResolverFilters())
    assert len(out) == 2
