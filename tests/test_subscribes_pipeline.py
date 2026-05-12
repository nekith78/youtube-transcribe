"""Tests for subscribes.pipeline — orchestration of update flow."""
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _channel(handle="@A", channel_id="UC_a", last_id=None, last_pub=None,
             group=None):
    from skills.youtube_transcribe.subscribes.store import Channel
    return Channel(
        url=f"https://www.youtube.com/{handle}", handle=handle,
        channel_id=channel_id, group=group, added="2026-05-12",
        last_seen_video_id=last_id, last_seen_published=last_pub,
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
