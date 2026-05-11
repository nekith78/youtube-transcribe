"""Tests for subscribes.group — channel grouping helpers."""
from skills.youtube_transcribe.subscribes.store import Channel
from skills.youtube_transcribe.subscribes.group import (
    filter_by_group,
    list_groups,
)


def _c(handle, group):
    return Channel(url=f"u/{handle}", handle=handle, channel_id=f"UC_{handle}",
                   group=group, added="x")


def test_filter_by_group_named():
    chans = [_c("@A", "ai"), _c("@B", "philosophy"), _c("@C", "ai")]
    out = filter_by_group(chans, "ai")
    assert [c.handle for c in out] == ["@A", "@C"]


def test_filter_by_group_none_returns_all():
    chans = [_c("@A", "ai"), _c("@B", None), _c("@C", "philosophy")]
    assert filter_by_group(chans, None) == chans


def test_filter_by_group_unknown_returns_empty():
    chans = [_c("@A", "ai")]
    assert filter_by_group(chans, "nope") == []


def test_filter_by_group_ungrouped_keyword():
    """Special keyword 'ungrouped' selects channels with group=None."""
    chans = [_c("@A", "ai"), _c("@B", None), _c("@C", None)]
    out = filter_by_group(chans, "ungrouped")
    assert [c.handle for c in out] == ["@B", "@C"]


def test_list_groups_returns_unique_sorted():
    chans = [_c("@A", "ai"), _c("@B", "philosophy"), _c("@C", "ai"),
             _c("@D", None), _c("@E", "art")]
    groups = list_groups(chans)
    assert groups == ["ai", "art", "philosophy"]
    # None should NOT appear in list (use 'ungrouped' filter explicitly).


def test_list_groups_empty():
    assert list_groups([]) == []
