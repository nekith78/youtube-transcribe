from datetime import date
from pathlib import Path
from unittest.mock import patch
import pytest

from skills.youtube_transcribe.utils.downloader import ChannelEntry
from skills.youtube_transcribe.utils.resolver import (
    ResolvedTarget,
    ResolverFilters,
    resolve,
    parse_from_file,
    UnresolvableInput,
    CLIInputError,
)


def _video_info(vid: str, title: str = "Hello"):
    return ("video", {"id": vid, "title": title, "duration": 60,
                      "upload_date": "20260420", "channel": "@x"})


def _playlist_info(channel: str, entries: list[tuple[str, str]]):
    return ("playlist", {"id": "PL", "title": channel,
                         "entries": [{"id": v, "title": t} for v, t in entries]})


def _channel_entries(*pairs: tuple[str, str]) -> list[ChannelEntry]:
    return [ChannelEntry(video_id=v, url=f"https://youtu.be/{v}", title=t,
                         duration_sec=60, upload_date=date(2026, 4, 20),
                         channel="@x") for v, t in pairs]


def test_resolve_inline_single_url(tmp_path):
    with patch("skills.youtube_transcribe.utils.resolver.probe_input",
               return_value=_video_info("aaa")):
        targets = resolve(["https://youtu.be/aaa"], None, ResolverFilters())
    assert len(targets) == 1
    assert targets[0].url == "https://youtu.be/aaa"
    assert targets[0].source == "inline"
    assert targets[0].video_id == "aaa"


def test_resolve_channel_applies_limit():
    pairs = [(f"v{i}", f"Video {i}") for i in range(50)]
    with patch("skills.youtube_transcribe.utils.resolver.probe_input",
               return_value=_playlist_info("@anth",
                                           [(v, t) for v, t in pairs])), \
         patch("skills.youtube_transcribe.utils.resolver.expand_channel_or_playlist",
               return_value=_channel_entries(*pairs[:10])):
        targets = resolve(["https://youtube.com/@anth"], None,
                          ResolverFilters(limit=10))
    assert len(targets) == 10
    assert all(t.source == "channel" for t in targets)
    assert targets[0].video_id == "v0"


def test_resolve_dedup_inline_and_channel_keeps_first():
    """Inline видео + то же видео из канала → попадает только inline."""
    with patch("skills.youtube_transcribe.utils.resolver.probe_input",
               side_effect=[_video_info("v0"), _playlist_info("@anth",
                                                              [("v0", "v0"), ("v1", "v1")])]), \
         patch("skills.youtube_transcribe.utils.resolver.expand_channel_or_playlist",
               return_value=_channel_entries(("v0", "v0"), ("v1", "v1"))):
        targets = resolve(
            ["https://youtu.be/v0", "https://youtube.com/@anth"],
            None, ResolverFilters(limit=10),
        )
    ids = [t.video_id for t in targets]
    assert ids == ["v0", "v1"]
    assert targets[0].source == "inline"
    assert targets[1].source == "channel"


def test_resolve_no_inputs_raises():
    with pytest.raises(CLIInputError):
        resolve([], None, ResolverFilters())


def test_resolve_unresolvable_url_collected_as_failure():
    with patch("skills.youtube_transcribe.utils.resolver.probe_input",
               side_effect=Exception("HTTP 403")):
        with pytest.raises(UnresolvableInput) as exc:
            resolve(["https://youtu.be/blocked"], None, ResolverFilters())
    assert "blocked" in str(exc.value)


def test_parse_from_file_skips_comments_and_blanks(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text(
        "# comment\n"
        "\n"
        "https://youtu.be/AAA\n"
        "  https://youtu.be/BBB   # trailing comment\n"
        "https://youtu.be/CCC\n",
        encoding="utf-8",
    )
    urls = parse_from_file(f)
    assert urls == ["https://youtu.be/AAA",
                    "https://youtu.be/BBB",
                    "https://youtu.be/CCC"]


def test_parse_from_file_missing_raises(tmp_path):
    with pytest.raises(CLIInputError):
        parse_from_file(tmp_path / "nope.txt")


def test_resolve_from_file_only(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("https://youtu.be/AAA\nhttps://youtu.be/BBB\n", encoding="utf-8")
    with patch("skills.youtube_transcribe.utils.resolver.probe_input",
               side_effect=[_video_info("AAA"), _video_info("BBB")]):
        targets = resolve([], f, ResolverFilters())
    assert len(targets) == 2
    assert {t.video_id for t in targets} == {"AAA", "BBB"}
    assert all(t.source == "file" for t in targets)


def test_resolve_local_path(tmp_path):
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"f")
    with patch("skills.youtube_transcribe.utils.resolver.probe_input",
               return_value=("local", {"path": str(audio)})):
        targets = resolve([str(audio)], None, ResolverFilters())
    assert len(targets) == 1
    assert targets[0].source == "single"
    assert targets[0].url == str(audio)
    assert targets[0].video_id is None
