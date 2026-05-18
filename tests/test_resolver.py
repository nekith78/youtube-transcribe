from datetime import date
from pathlib import Path
from unittest.mock import patch
import pytest

from skills.neurolearn.utils.downloader import ChannelEntry
from skills.neurolearn.utils.resolver import (
    ResolvedTarget,
    ResolveFailure,
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


def test_resolve_probes_multiple_urls_in_parallel():
    """v0.10.4: when resolving N inline URLs, probe_input runs concurrently
    via ThreadPoolExecutor. Sequential 4×100ms = 400ms; parallel ≈ 100ms."""
    import threading
    import time

    concurrent = 0
    max_concurrent = 0
    lock = threading.Lock()

    def slow_probe(url: str):
        nonlocal concurrent, max_concurrent
        with lock:
            concurrent += 1
            if concurrent > max_concurrent:
                max_concurrent = concurrent
        time.sleep(0.1)
        with lock:
            concurrent -= 1
        # Extract last 3 chars as fake video_id.
        return _video_info(url[-3:])

    urls = [f"https://youtu.be/v{i:02d}" for i in range(4)]
    with patch("skills.neurolearn.utils.resolver.probe_input",
               side_effect=slow_probe):
        t0 = time.time()
        targets, failures = resolve(urls, None, ResolverFilters())
        elapsed = time.time() - t0

    assert failures == []
    assert len(targets) == 4
    # At least 2 probes in flight at once.
    assert max_concurrent >= 2, f"max_concurrent={max_concurrent} (no parallelism)"
    # Sequential would take 400ms+; allow generous slack for slow CI.
    assert elapsed < 0.35, f"elapsed={elapsed:.2f}s (looks sequential)"


def test_resolve_inline_single_url(tmp_path):
    with patch("skills.neurolearn.utils.resolver.probe_input",
               return_value=_video_info("aaa")):
        targets, failures = resolve(["https://youtu.be/aaa"], None, ResolverFilters())
    assert failures == []
    assert len(targets) == 1
    assert targets[0].url == "https://youtu.be/aaa"
    assert targets[0].source == "inline"
    assert targets[0].video_id == "aaa"


def test_resolve_channel_applies_limit():
    pairs = [(f"v{i}", f"Video {i}") for i in range(50)]
    with patch("skills.neurolearn.utils.resolver.probe_input",
               return_value=_playlist_info("@anth",
                                           [(v, t) for v, t in pairs])), \
         patch("skills.neurolearn.utils.resolver.expand_channel_or_playlist",
               return_value=_channel_entries(*pairs[:10])):
        targets, failures = resolve(["https://youtube.com/@anth"], None,
                                    ResolverFilters(limit=10))
    assert failures == []
    assert len(targets) == 10
    assert all(t.source == "channel" for t in targets)
    assert targets[0].video_id == "v0"


def test_resolve_dedup_inline_and_channel_keeps_first():
    """Inline video + same video from a channel → only inline is kept."""
    with patch("skills.neurolearn.utils.resolver.probe_input",
               side_effect=[_video_info("v0"), _playlist_info("@anth",
                                                              [("v0", "v0"), ("v1", "v1")])]), \
         patch("skills.neurolearn.utils.resolver.expand_channel_or_playlist",
               return_value=_channel_entries(("v0", "v0"), ("v1", "v1"))):
        targets, failures = resolve(
            ["https://youtu.be/v0", "https://youtube.com/@anth"],
            None, ResolverFilters(limit=10),
        )
    assert failures == []
    ids = [t.video_id for t in targets]
    assert ids == ["v0", "v1"]
    assert targets[0].source == "inline"
    assert targets[1].source == "channel"


def test_resolve_no_inputs_raises():
    with pytest.raises(CLIInputError):
        resolve([], None, ResolverFilters())


def test_resolve_unresolvable_url_collected_as_failure():
    """Per spec §5: yt-dlp probe failure is collected, doesn't abort the resolve."""
    with patch("skills.neurolearn.utils.resolver.probe_input",
               side_effect=Exception("HTTP 403")):
        targets, failures = resolve(["https://youtu.be/blocked"], None, ResolverFilters())
    assert targets == []
    assert len(failures) == 1
    assert failures[0].url == "https://youtu.be/blocked"
    assert "403" in failures[0].error


def test_resolve_partial_failure_keeps_good_inputs():
    """Bad URL doesn't abort the rest — collect-and-continue."""
    def fake_probe(url):
        if "blocked" in url:
            raise Exception("HTTP 403")
        return ("video", {"id": "good", "title": "Hello", "duration": 60,
                          "upload_date": "20260420", "channel": "@x"})
    with patch("skills.neurolearn.utils.resolver.probe_input",
               side_effect=fake_probe):
        targets, failures = resolve(
            ["https://youtu.be/blocked", "https://youtu.be/good"],
            None, ResolverFilters(),
        )
    assert len(targets) == 1
    assert targets[0].video_id == "good"
    assert len(failures) == 1
    assert "blocked" in failures[0].url


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
    with patch("skills.neurolearn.utils.resolver.probe_input",
               side_effect=[_video_info("AAA"), _video_info("BBB")]):
        targets, failures = resolve([], f, ResolverFilters())
    assert failures == []
    assert len(targets) == 2
    assert {t.video_id for t in targets} == {"AAA", "BBB"}
    assert all(t.source == "file" for t in targets)


def test_resolve_local_path(tmp_path):
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"f")
    with patch("skills.neurolearn.utils.resolver.probe_input",
               return_value=("local", {"path": str(audio)})):
        targets, failures = resolve([str(audio)], None, ResolverFilters())
    assert failures == []
    assert len(targets) == 1
    assert targets[0].source == "single"
    assert targets[0].url == str(audio)
    assert targets[0].video_id is None
