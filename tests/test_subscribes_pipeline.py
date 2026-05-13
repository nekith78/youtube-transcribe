"""Tests for subscribes.pipeline — orchestration of update flow."""
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _channel(handle="@A", channel_id="UC_a", last_id=None, last_pub=None,
             group=None, platform="youtube"):
    from skills.youtube_transcribe.subscribes.store import Channel
    base_url = {
        "youtube": "https://www.youtube.com",
        "instagram": "https://www.instagram.com",
        "tiktok": "https://www.tiktok.com",
    }[platform]
    return Channel(
        url=f"{base_url}/{handle}", handle=handle,
        channel_id=channel_id, group=group, added="2026-05-12",
        last_seen_video_id=last_id, last_seen_published=last_pub,
        platform=platform,
    )


def _rss(vid, pub_iso="2026-05-11T14:00:00+00:00"):
    from skills.youtube_transcribe.subscribes.rss import RssEntry
    return RssEntry(
        video_id=vid, url=f"https://www.youtube.com/watch?v={vid}",
        title=f"Title {vid}", channel_id="UC_a",
        published=datetime.fromisoformat(pub_iso),
    )


def test_first_run_requires_window(tmp_path: Path):
    """If a channel has no state and no override window — exit 2 via raise."""
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update, SubscribesError,
    )
    sub_path = tmp_path / "subscribes.toml"
    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[_channel(last_id=None)],
    ):
        with pytest.raises(SubscribesError, match="initial"):
            run_subscribes_update(
                subscribes_path=sub_path,
                group=None,
                days=None, since=None, until=None,
                match=None, filter_text=None,
                no_rss=False, yes=True, no_analyze=True,
                prompt=None, prompt_file=None,
                analyze_backend="gemini", filter_backend="gemini",
                ollama_model="llama3.2:3b",
                ollama_host="http://localhost:11434",
                no_stdout=False, output_dir=str(tmp_path),
                api_keys={}, batch_opts={},
            )


def test_stateful_default_uses_last_seen(tmp_path: Path):
    """Channel with state: pipeline filters entries where published > last_seen."""
    from skills.youtube_transcribe.subscribes.pipeline import run_subscribes_update
    sub_path = tmp_path / "subscribes.toml"
    ch = _channel(last_id="oldvid", last_pub="2026-05-10T00:00:00+00:00")
    entries = [_rss("new1", "2026-05-12T00:00:00+00:00"),
               _rss("old1", "2026-05-09T00:00:00+00:00")]

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[ch],
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.fetch_rss",
        return_value=entries,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        return_value=tmp_path / "out",
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.update_last_seen",
    ) as mock_state, patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    # State updated with newest video
    mock_state.assert_called_once()
    args, _ = mock_state.call_args
    # update_last_seen(path, channel_id, video_id, published)
    assert args[2] == "new1"


def test_bootstrap_first_run_initializes_state(tmp_path: Path):
    """Channel without state + --days 7: state IS initialized (bootstrap).

    Pre-fix v0.7 bug: --days marked the run as "override → don't update
    state", so first-run with --days produced an empty state, and the next
    incremental call kept asking for --days. Now bootstrap is recognized
    separately and the state is seeded.
    """
    from skills.youtube_transcribe.subscribes.pipeline import run_subscribes_update
    sub_path = tmp_path / "subscribes.toml"
    ch = _channel(last_id=None, last_pub=None)  # ← no state yet
    entries = [_rss("v1", "2026-05-12T00:00:00+00:00")]

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[ch],
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.fetch_rss",
        return_value=entries,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        return_value=tmp_path / "out",
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.update_last_seen",
    ) as mock_state, patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, days=7,  # ← bootstrap window
            since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    # Bootstrap recognized → state initialized to the newest entry.
    mock_state.assert_called_once()
    assert mock_state.call_args.args[2] == "v1"


def test_state_advances_when_transcribe_batch_returns_none(tmp_path: Path):
    """Variant 2: state must advance even if _run_batch_pipeline returns None
    (e.g. catastrophic transcribe failure). Otherwise a temporary blip would
    pin the channel forever."""
    from skills.youtube_transcribe.subscribes.pipeline import run_subscribes_update
    sub_path = tmp_path / "subscribes.toml"
    ch = _channel(last_id="oldvid", last_pub="2026-05-10T00:00:00+00:00")
    entries = [_rss("recent", "2026-05-12T00:00:00+00:00")]

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[ch],
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.fetch_rss",
        return_value=entries,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        return_value=None,  # ← simulate batch failure
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.update_last_seen",
    ) as mock_state, patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    mock_state.assert_called_once()
    assert mock_state.call_args.args[2] == "recent"


def test_override_days_skips_state_update(tmp_path: Path):
    """When --days override is used, state must NOT be updated."""
    from skills.youtube_transcribe.subscribes.pipeline import run_subscribes_update
    sub_path = tmp_path / "subscribes.toml"
    ch = _channel(last_id="oldvid", last_pub="2026-05-10T00:00:00+00:00")
    entries = [_rss("v1", "2026-05-12T00:00:00+00:00")]

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[ch],
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.fetch_rss",
        return_value=entries,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        return_value=tmp_path / "out",
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.update_last_seen",
    ) as mock_state, patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, days=7,
            since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    mock_state.assert_not_called()


def test_no_rss_uses_yt_dlp_fallback(tmp_path: Path):
    """--no-rss flag routes per-channel fetch through yt-dlp, not RSS."""
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update, _ChannelVideo,
    )
    sub_path = tmp_path / "subscribes.toml"
    ch = _channel(last_id="oldvid", last_pub="2026-05-10T00:00:00+00:00")
    fake_yt_dlp_entries = [
        _ChannelVideo(
            video_id="yt1", url="https://www.youtube.com/watch?v=yt1",
            title="Long video", duration_sec=900,
            published=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ),
    ]

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[ch],
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.fetch_rss",
    ) as mock_rss, patch(
        "skills.youtube_transcribe.subscribes.pipeline._fetch_via_yt_dlp",
        return_value=fake_yt_dlp_entries,
    ) as mock_yt, patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        return_value=tmp_path / "out",
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=True,  # ← force yt-dlp path
            yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    # RSS not called when --no-rss is set
    mock_rss.assert_not_called()
    # yt-dlp called instead, with the channel URL
    mock_yt.assert_called_once()


def test_no_rss_returns_duration(tmp_path: Path):
    """When --no-rss is used, candidates carry duration_sec from yt-dlp."""
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update, _ChannelVideo,
    )
    sub_path = tmp_path / "subscribes.toml"
    ch = _channel(last_id="oldvid", last_pub="2026-05-10T00:00:00+00:00")
    fake_yt_dlp_entries = [
        _ChannelVideo(
            video_id="yt1", url="u", title="T", duration_sec=720,
            published=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ),
    ]

    captured_targets = {}

    def capture_batch(*, targets, **kw):
        captured_targets["targets"] = list(targets)
        return tmp_path / "out"

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[ch],
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._fetch_via_yt_dlp",
        return_value=fake_yt_dlp_entries,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        side_effect=capture_batch,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=True, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    targets = captured_targets["targets"]
    assert len(targets) == 1
    assert targets[0].duration_sec == 720


def test_group_filters_channels(tmp_path: Path):
    """--group ai-research should only fetch RSS for matching channels."""
    from skills.youtube_transcribe.subscribes.pipeline import run_subscribes_update
    sub_path = tmp_path / "subscribes.toml"
    channels = [
        _channel(handle="@AI1", channel_id="UC_ai1", last_id="x",
                 last_pub="2026-01-01T00:00:00+00:00", group="ai-research"),
        _channel(handle="@PH1", channel_id="UC_ph1", last_id="x",
                 last_pub="2026-01-01T00:00:00+00:00", group="philosophy"),
    ]
    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=channels,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.fetch_rss",
        return_value=[],
    ) as mock_rss, patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group="ai-research",
            days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    # Only UC_ai1 fetched
    mock_rss.assert_called_once_with("UC_ai1")


# === v0.8: Instagram / TikTok flows ===


def test_instagram_channel_uses_yt_dlp_with_cookies(tmp_path: Path):
    """Instagram channels NEVER hit RSS — always go through yt-dlp with the
    user's configured cookies_browser."""
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update, _ChannelVideo,
    )
    sub_path = tmp_path / "subscribes.toml"
    ch = _channel(
        handle="@anthropic", channel_id="anthropic",
        last_id="oldvid", last_pub="2026-05-01T00:00:00+00:00",
        platform="instagram",
    )
    fake_videos = [_ChannelVideo(
        video_id="reel1", url="https://www.instagram.com/p/reel1/",
        title="A new reel", duration_sec=42,
        published=datetime(2026, 5, 11, tzinfo=timezone.utc),
    )]

    captured: dict = {}

    def fake_fetch(url, *, cookies_browser=None, limit=30, **kw):
        captured["url"] = url
        captured["cookies_browser"] = cookies_browser
        return fake_videos

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[ch],
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.fetch_rss",
        side_effect=AssertionError("RSS must NOT be used for Instagram"),
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._fetch_via_yt_dlp",
        side_effect=fake_fetch,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        return_value=tmp_path / "batch",
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
            instagram_cookies_browser="chrome",
        )
    assert captured["cookies_browser"] == "chrome"


def test_username_change_surfaces_friendly_error(tmp_path: Path, capsys):
    """When yt-dlp reports 'user not found', the loop prints a hint and
    moves on without aborting the run."""
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update, ChannelNotFoundError, _ChannelVideo,
    )
    sub_path = tmp_path / "subscribes.toml"
    ig_ch = _channel(
        handle="@ghost", channel_id="ghost",
        last_id="x", last_pub="2026-05-01T00:00:00+00:00",
        platform="instagram",
    )
    yt_ch = _channel(
        handle="@anthropic-ai", channel_id="UC_anth",
        last_id="x", last_pub="2026-05-01T00:00:00+00:00",
        platform="youtube",
    )
    yt_rss = [_rss("yt_new", "2026-05-11T00:00:00+00:00")]

    def fake_fetch(url, *, cookies_browser=None, limit=30, **kw):
        raise ChannelNotFoundError("user does not exist")

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[ig_ch, yt_ch],
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.fetch_rss",
        return_value=yt_rss,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._fetch_via_yt_dlp",
        side_effect=fake_fetch,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        return_value=tmp_path / "batch",
    ) as mock_batch, patch(
        "skills.youtube_transcribe.subscribes.pipeline.update_last_seen",
    ) as mock_state, patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
            instagram_cookies_browser="chrome",
        )
    # Batch ran with YT video only — IG was skipped, run continues.
    mock_batch.assert_called_once()
    # State advanced for the surviving YT channel, NOT for the broken IG one.
    # update_last_seen signature: (path, channel_id, video_id, published).
    state_targets = [call.args[1] for call in mock_state.call_args_list]
    assert "UC_anth" in state_targets
    assert "ghost" not in state_targets


def test_looks_like_channel_not_found_matches_common_signatures():
    from skills.youtube_transcribe.subscribes.pipeline import (
        _looks_like_channel_not_found,
    )
    assert _looks_like_channel_not_found("ERROR: user not found")
    assert _looks_like_channel_not_found("HTTP Error 404: Not Found")
    assert _looks_like_channel_not_found("This account does not exist")
    assert _looks_like_channel_not_found("Private account, login required")
    # Real-world false-positive guard:
    assert not _looks_like_channel_not_found(
        "RuntimeError: ffmpeg crashed"
    )
    assert not _looks_like_channel_not_found("Quota exceeded")


def test_tiktok_channel_uses_yt_dlp_with_tiktok_cookies(tmp_path: Path):
    """TikTok routes the same as Instagram, but with its own cookies setting.
    Verifies the per-platform cookies plumbing doesn't cross-contaminate."""
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update, _ChannelVideo,
    )
    sub_path = tmp_path / "subscribes.toml"
    ch = _channel(
        handle="@duolingo", channel_id="@duolingo",
        last_id="x", last_pub="2026-05-01T00:00:00+00:00",
        platform="tiktok",
    )
    fake_videos = [_ChannelVideo(
        video_id="v1", url="https://www.tiktok.com/@duolingo/video/v1",
        title="A new short", duration_sec=30,
        published=datetime(2026, 5, 11, tzinfo=timezone.utc),
    )]

    captured: dict = {}

    def fake_fetch(url, *, cookies_browser=None, limit=30, **kw):
        captured["cookies_browser"] = cookies_browser
        return fake_videos

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[ch],
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.fetch_rss",
        side_effect=AssertionError("RSS must NOT be used for TikTok"),
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._fetch_via_yt_dlp",
        side_effect=fake_fetch,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        return_value=tmp_path / "batch",
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
            instagram_cookies_browser="firefox",  # MUST NOT be used here
            tiktok_cookies_browser="chrome",
        )
    assert captured["cookies_browser"] == "chrome"


def test_tiktok_dedup_via_last_seen_video_id(tmp_path: Path):
    """For IG/TikTok the date window is bypassed — dedup is by
    last_seen_video_id. yt-dlp returns entries newest-first; we walk
    until we hit the previously-seen id and stop."""
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update, _ChannelVideo,
    )
    sub_path = tmp_path / "subscribes.toml"
    ch = _channel(
        handle="@duolingo", channel_id="@duolingo",
        last_id="OLD_SEEN", last_pub=None,  # date doesn't exist for TT
        platform="tiktok",
    )
    # Newest first; OLD_SEEN was previously seen → only NEW1, NEW2 are fresh.
    fake_videos = [
        _ChannelVideo(video_id="NEW1", url="...", title="t1",
                      duration_sec=10, published=datetime.now(timezone.utc)),
        _ChannelVideo(video_id="NEW2", url="...", title="t2",
                      duration_sec=10, published=datetime.now(timezone.utc)),
        _ChannelVideo(video_id="OLD_SEEN", url="...", title="t3",
                      duration_sec=10, published=datetime.now(timezone.utc)),
        _ChannelVideo(video_id="OLDER", url="...", title="t4",
                      duration_sec=10, published=datetime.now(timezone.utc)),
    ]
    captured: dict = {}

    def capture_batch(*, targets, **kw):
        captured["targets"] = list(targets)
        return tmp_path / "batch"

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=[ch],
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._fetch_via_yt_dlp",
        return_value=fake_videos,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        side_effect=capture_batch,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    seen_ids = [t.video_id for t in captured["targets"]]
    assert seen_ids == ["NEW1", "NEW2"]  # OLD_SEEN stopped the scan


def test_platform_filter_restricts_to_one_platform(tmp_path: Path):
    """--platform tiktok updates ONLY TikTok channels, skipping YT and IG."""
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update, _ChannelVideo,
    )
    sub_path = tmp_path / "subscribes.toml"
    channels = [
        _channel(handle="@yt", channel_id="UC_yt", last_id="x",
                 last_pub="2026-01-01T00:00:00+00:00", platform="youtube"),
        _channel(handle="@ig", channel_id="ig", last_id="x",
                 last_pub="2026-01-01T00:00:00+00:00", platform="instagram"),
        _channel(handle="@tt", channel_id="@tt", last_id="x",
                 last_pub="2026-01-01T00:00:00+00:00", platform="tiktok"),
    ]
    fake_videos = [_ChannelVideo(
        video_id="v1", url="u", title="t", duration_sec=10,
        published=datetime.now(timezone.utc),
    )]

    fetch_calls: list[str] = []

    def fake_fetch(url, *, cookies_browser=None, limit=30, **kw):
        fetch_calls.append(url)
        return fake_videos

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=channels,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline.fetch_rss",
        side_effect=AssertionError("RSS must NOT be called: only TT in scope"),
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._fetch_via_yt_dlp",
        side_effect=fake_fetch,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        return_value=tmp_path / "batch",
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group=None, platform="tiktok",
            days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    # Exactly one fetch call — for the TikTok channel.
    assert len(fetch_calls) == 1
    assert "tiktok" in fetch_calls[0].lower()


def test_platform_filter_combined_with_group(tmp_path: Path):
    """--platform tiktok --group ai → only TikTok channels in group 'ai'."""
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update, _ChannelVideo,
    )
    sub_path = tmp_path / "subscribes.toml"
    channels = [
        _channel(handle="@tt1", channel_id="@tt1", last_id="x",
                 last_pub="2026-01-01T00:00:00+00:00",
                 group="ai", platform="tiktok"),
        _channel(handle="@tt2", channel_id="@tt2", last_id="x",
                 last_pub="2026-01-01T00:00:00+00:00",
                 group="memes", platform="tiktok"),
        _channel(handle="@ig1", channel_id="ig1", last_id="x",
                 last_pub="2026-01-01T00:00:00+00:00",
                 group="ai", platform="instagram"),
    ]

    fetch_calls: list[str] = []

    def fake_fetch(url, *, cookies_browser=None, limit=30, **kw):
        fetch_calls.append(url)
        return [_ChannelVideo(
            video_id="v1", url="u", title="t", duration_sec=10,
            published=datetime.now(timezone.utc),
        )]

    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=channels,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._fetch_via_yt_dlp",
        side_effect=fake_fetch,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        return_value=tmp_path / "batch",
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._stdin_is_tty",
        return_value=False,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._append_history",
    ):
        run_subscribes_update(
            subscribes_path=sub_path,
            group="ai", platform="tiktok",
            days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    # Only @tt1 matches: platform=tiktok AND group=ai. @tt2 wrong group,
    # @ig1 wrong platform.
    assert len(fetch_calls) == 1


def test_platform_filter_empty_intersection_returns_none(tmp_path: Path):
    """--platform tiktok with no TikTok channels in subscribes → no-op."""
    from skills.youtube_transcribe.subscribes.pipeline import (
        run_subscribes_update,
    )
    sub_path = tmp_path / "subscribes.toml"
    channels = [
        _channel(handle="@yt", channel_id="UC_yt", last_id="x",
                 last_pub="2026-01-01T00:00:00+00:00", platform="youtube"),
    ]
    with patch(
        "skills.youtube_transcribe.subscribes.pipeline.load_subscribes",
        return_value=channels,
    ), patch(
        "skills.youtube_transcribe.subscribes.pipeline._run_batch_pipeline",
        side_effect=AssertionError("batch must NOT run when filter empty"),
    ):
        result = run_subscribes_update(
            subscribes_path=sub_path,
            group=None, platform="tiktok",
            days=None, since=None, until=None,
            match=None, filter_text=None,
            no_rss=False, yes=True, no_analyze=True,
            prompt=None, prompt_file=None,
            analyze_backend="gemini", filter_backend="gemini",
            ollama_model="llama3.2:3b", ollama_host="http://localhost:11434",
            no_stdout=False, output_dir=str(tmp_path),
            api_keys={}, batch_opts={},
        )
    assert result is None
