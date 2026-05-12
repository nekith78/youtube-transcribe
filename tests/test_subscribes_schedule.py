"""Tests for subscribes.schedule — cross-OS snippet generation."""
import pytest

from skills.youtube_transcribe.subscribes.schedule import (
    detect_platform, parse_interval,
    generate_cron_line, generate_systemd_units,
    generate_launchd_plist, generate_taskscheduler_xml,
)


# ─── platform detection ───────────────────────────────────────────────


def test_detect_platform_macos(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    assert detect_platform() == "launchd"


def test_detect_platform_linux(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert detect_platform() in ("systemd", "cron")


def test_detect_platform_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    assert detect_platform() == "taskscheduler"


# ─── interval parsing ─────────────────────────────────────────────────


def test_parse_interval_minutes():
    assert parse_interval("15m") == 900
    assert parse_interval("30m") == 1800


def test_parse_interval_hours():
    assert parse_interval("1h") == 3600
    assert parse_interval("6h") == 21600


def test_parse_interval_days():
    assert parse_interval("1d") == 86400


def test_parse_interval_invalid():
    with pytest.raises(ValueError, match="interval"):
        parse_interval("bogus")
    with pytest.raises(ValueError, match="interval"):
        parse_interval("5x")


def test_parse_interval_zero_raises():
    with pytest.raises(ValueError, match="positive"):
        parse_interval("0h")


# ─── cron line generation ────────────────────────────────────────────


def test_cron_line_hourly():
    line = generate_cron_line(
        command_argv=["/usr/local/bin/youtube-transcribe", "subscribes",
                       "update"],
        every_seconds=3600,
    )
    assert line.startswith("0 * * * *")
    assert "/usr/local/bin/youtube-transcribe" in line


def test_cron_line_every_15min():
    line = generate_cron_line(
        command_argv=["yt-tr", "subscribes", "update"],
        every_seconds=900,
    )
    assert line.startswith("*/15 * * * *")


def test_cron_line_daily():
    line = generate_cron_line(
        command_argv=["yt-tr"], every_seconds=86400,
    )
    assert line.startswith("0 0 * * *")


def test_cron_line_quotes_args_with_spaces():
    line = generate_cron_line(
        command_argv=["yt-tr", "--prompt", "summarize this week"],
        every_seconds=3600,
    )
    assert "'summarize this week'" in line or '"summarize this week"' in line


# ─── systemd units ───────────────────────────────────────────────────


def test_systemd_units_returns_pair():
    timer, service = generate_systemd_units(
        command_argv=["/usr/local/bin/yt-tr", "subscribes", "update"],
        every_seconds=3600,
        label="yt-tr-subscribes",
    )
    assert "[Timer]" in timer
    assert "OnUnitActiveSec=3600" in timer
    assert "[Service]" in service
    assert "ExecStart=" in service
    assert "/usr/local/bin/yt-tr" in service


def test_systemd_user_install_path_hint():
    timer, _ = generate_systemd_units(
        command_argv=["yt-tr"], every_seconds=3600,
        label="yt-tr-subscribes",
    )
    assert "[Install]" in timer
    assert "WantedBy=timers.target" in timer


# ─── launchd plist ──────────────────────────────────────────────────


def test_launchd_plist_basic_structure():
    plist = generate_launchd_plist(
        command_argv=["/usr/local/bin/yt-tr", "subscribes", "update"],
        every_seconds=3600,
        label="com.user.yt-tr-subscribes",
    )
    assert "<?xml" in plist
    assert "<plist" in plist
    assert "<key>Label</key>" in plist
    assert "<string>com.user.yt-tr-subscribes</string>" in plist
    assert "<key>StartInterval</key>" in plist
    assert "<integer>3600</integer>" in plist


def test_launchd_plist_program_arguments():
    plist = generate_launchd_plist(
        command_argv=["/usr/local/bin/yt-tr", "subscribes",
                       "update", "--days", "7"],
        every_seconds=900, label="com.user.test",
    )
    assert "<key>ProgramArguments</key>" in plist
    assert "<string>/usr/local/bin/yt-tr</string>" in plist
    assert "<string>--days</string>" in plist
    assert "<string>7</string>" in plist


def test_launchd_plist_run_at_load():
    plist = generate_launchd_plist(
        command_argv=["yt-tr"], every_seconds=3600, label="com.user.test",
    )
    assert "<key>RunAtLoad</key>" in plist
    assert "<true/>" in plist


def test_launchd_plist_escapes_xml_special_chars():
    plist = generate_launchd_plist(
        command_argv=["yt-tr", "--prompt", "find <ai> & related"],
        every_seconds=3600, label="com.user.test",
    )
    assert "&lt;ai&gt;" in plist
    assert "&amp;" in plist


# ─── Windows Task Scheduler XML ─────────────────────────────────────


def test_taskscheduler_xml_structure():
    xml = generate_taskscheduler_xml(
        command_argv=["C:\\Python\\Scripts\\yt-tr.exe", "subscribes", "update"],
        every_seconds=3600, task_name="yt-tr-subscribes",
    )
    assert "<?xml" in xml
    assert "<Task " in xml
    assert "<Triggers>" in xml
    assert "<TimeTrigger>" in xml
    assert "<Actions>" in xml
    assert "<Exec>" in xml


def test_taskscheduler_xml_interval_pt1h():
    xml = generate_taskscheduler_xml(
        command_argv=["yt-tr.exe"], every_seconds=3600, task_name="t",
    )
    assert "PT1H" in xml


def test_taskscheduler_xml_interval_pt15m():
    xml = generate_taskscheduler_xml(
        command_argv=["yt-tr.exe"], every_seconds=900, task_name="t",
    )
    assert "PT15M" in xml


def test_taskscheduler_xml_command_and_args_separated():
    xml = generate_taskscheduler_xml(
        command_argv=["C:\\Python\\Scripts\\yt-tr.exe", "subscribes",
                       "update", "--days", "7"],
        every_seconds=3600, task_name="t",
    )
    assert "<Command>C:\\Python\\Scripts\\yt-tr.exe</Command>" in xml
    assert "<Arguments>" in xml


def test_taskscheduler_xml_escapes_special_chars():
    xml = generate_taskscheduler_xml(
        command_argv=["yt-tr.exe", "--prompt", "find <x> & y"],
        every_seconds=3600, task_name="t",
    )
    assert "&lt;x&gt;" in xml
    assert "&amp;" in xml
