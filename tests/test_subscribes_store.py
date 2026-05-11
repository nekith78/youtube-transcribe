"""Tests for subscribes.store — TOML read/write with comment preservation."""
from pathlib import Path

import pytest

from skills.youtube_transcribe.subscribes.store import (
    Channel,
    load_subscribes,
    save_subscribes,
    add_channel,
    remove_channel,
    find_channel,
)


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert load_subscribes(tmp_path / "missing.toml") == []


def test_save_and_load_roundtrip(tmp_path: Path):
    p = tmp_path / "sub.toml"
    channels = [
        Channel(url="https://www.youtube.com/@A", handle="@A",
                channel_id="UC_a", group="ai", added="2026-05-12"),
        Channel(url="https://www.youtube.com/@B", handle="@B",
                channel_id="UC_b", group=None, added="2026-05-12"),
    ]
    save_subscribes(p, channels)
    loaded = load_subscribes(p)
    assert len(loaded) == 2
    assert loaded[0].handle == "@A"
    assert loaded[0].group == "ai"
    assert loaded[1].group is None


def test_preserves_comments_on_round_trip(tmp_path: Path):
    """If user added comments — keep them after CLI mutations."""
    p = tmp_path / "sub.toml"
    p.write_text(
        "# my favorite ai channels\n\n"
        "[[channels]]\n"
        "url = \"https://www.youtube.com/@A\"\n"
        "handle = \"@A\"\n"
        "channel_id = \"UC_a\"\n"
        "group = \"ai\"\n"
        "added = \"2026-05-12\"\n",
        encoding="utf-8",
    )
    chans = load_subscribes(p)
    add_channel(p, Channel(
        url="https://www.youtube.com/@B", handle="@B",
        channel_id="UC_b", group="ai", added="2026-05-12",
    ))
    out = p.read_text(encoding="utf-8")
    assert "# my favorite ai channels" in out
    assert "@A" in out
    assert "@B" in out


def test_add_duplicate_replaces(tmp_path: Path):
    """Adding same channel_id twice updates instead of duplicating."""
    p = tmp_path / "sub.toml"
    c1 = Channel(url="u1", handle="@A", channel_id="UC_a", group=None,
                 added="2026-05-12")
    add_channel(p, c1)
    c2 = Channel(url="u1", handle="@A", channel_id="UC_a", group="ai",
                 added="2026-05-12")  # different group
    add_channel(p, c2)
    chans = load_subscribes(p)
    assert len(chans) == 1
    assert chans[0].group == "ai"


def test_remove_by_handle(tmp_path: Path):
    p = tmp_path / "sub.toml"
    add_channel(p, Channel(url="u1", handle="@A", channel_id="UC_a",
                            group=None, added="x"))
    add_channel(p, Channel(url="u2", handle="@B", channel_id="UC_b",
                            group=None, added="x"))
    removed = remove_channel(p, "@A")
    assert removed is True
    chans = load_subscribes(p)
    assert len(chans) == 1
    assert chans[0].handle == "@B"


def test_remove_by_url(tmp_path: Path):
    p = tmp_path / "sub.toml"
    add_channel(p, Channel(url="https://www.youtube.com/@A", handle="@A",
                            channel_id="UC_a", group=None, added="x"))
    removed = remove_channel(p, "https://www.youtube.com/@A")
    assert removed is True
    assert load_subscribes(p) == []


def test_remove_missing_returns_false(tmp_path: Path):
    p = tmp_path / "sub.toml"
    assert remove_channel(p, "@nope") is False


def test_find_channel(tmp_path: Path):
    p = tmp_path / "sub.toml"
    add_channel(p, Channel(url="u1", handle="@A", channel_id="UC_a",
                            group=None, added="x"))
    found = find_channel(p, "@A")
    assert found is not None
    assert found.handle == "@A"
    assert find_channel(p, "@nope") is None


def test_load_with_last_seen_fields(tmp_path: Path):
    p = tmp_path / "sub.toml"
    p.write_text(
        "[[channels]]\n"
        "url = \"u\"\n"
        "handle = \"@A\"\n"
        "channel_id = \"UC_a\"\n"
        "added = \"2026-05-12\"\n"
        "last_seen_video_id = \"vid123\"\n"
        "last_seen_published = \"2026-05-10T14:00:00Z\"\n",
        encoding="utf-8",
    )
    chans = load_subscribes(p)
    assert chans[0].last_seen_video_id == "vid123"
    assert chans[0].last_seen_published == "2026-05-10T14:00:00Z"
