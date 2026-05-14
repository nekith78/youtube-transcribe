"""Cross-OS schedule helpers — generate snippet files for cron / launchd
/ systemd / Windows Task Scheduler.

We DON'T install schedules ourselves — printing snippet + instructions
keeps cross-platform safety. User installs via documented one-liner.
"""
from __future__ import annotations

import re
import shlex
import shutil
import sys
from xml.sax.saxutils import escape as _xml_escape

__all__ = [
    "detect_platform", "parse_interval",
    "generate_cron_line", "generate_launchd_plist",
    "generate_systemd_units", "generate_taskscheduler_xml",
]


def detect_platform() -> str:
    """Return one of 'launchd' / 'systemd' / 'cron' / 'taskscheduler'."""
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform == "win32":
        return "taskscheduler"
    if sys.platform.startswith("linux"):
        if shutil.which("systemctl"):
            return "systemd"
        return "cron"
    return "cron"


def parse_interval(spec: str) -> int:
    """Parse '15m' / '1h' / '6h' / '1d' to seconds. Raises ValueError on garbage."""
    m = re.match(r"^(\d+)([mhd])$", (spec or "").strip().lower())
    if not m:
        raise ValueError(f"invalid interval: {spec!r}")
    n = int(m.group(1))
    if n <= 0:
        raise ValueError("interval must be positive")
    return n * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]


def generate_cron_line(
    *,
    command_argv: list[str],
    every_seconds: int,
) -> str:
    """Generate a crontab line that runs `command_argv` at `every_seconds`."""
    cron_expr = _seconds_to_cron(every_seconds)
    cmd = " ".join(shlex.quote(a) for a in command_argv)
    return f"{cron_expr} {cmd}"


def generate_systemd_units(
    *,
    command_argv: list[str],
    every_seconds: int,
    label: str,
) -> tuple[str, str]:
    """Generate (timer_unit, service_unit) text pair for systemd."""
    timer = (
        f"[Unit]\n"
        f"Description=neurolearn {label}\n\n"
        f"[Timer]\n"
        f"OnBootSec=2min\n"
        f"OnUnitActiveSec={every_seconds}\n"
        f"Unit={label}.service\n\n"
        f"[Install]\n"
        f"WantedBy=timers.target\n"
    )
    exec_start = " ".join(shlex.quote(a) for a in command_argv)
    service = (
        f"[Unit]\n"
        f"Description=neurolearn {label}\n\n"
        f"[Service]\n"
        f"Type=oneshot\n"
        f"ExecStart={exec_start}\n"
    )
    return timer, service


def generate_launchd_plist(
    *,
    command_argv: list[str],
    every_seconds: int,
    label: str,
) -> str:
    """Generate a macOS LaunchAgent plist text."""
    args_xml = "\n    ".join(
        f"<string>{_xml_escape(a)}</string>" for a in command_argv
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        f'  <key>Label</key>\n  <string>{_xml_escape(label)}</string>\n'
        '  <key>ProgramArguments</key>\n'
        '  <array>\n'
        f'    {args_xml}\n'
        '  </array>\n'
        f'  <key>StartInterval</key>\n  <integer>{every_seconds}</integer>\n'
        '  <key>RunAtLoad</key>\n  <true/>\n'
        '  <key>StandardOutPath</key>\n'
        f'  <string>/tmp/{_xml_escape(label)}.log</string>\n'
        '  <key>StandardErrorPath</key>\n'
        f'  <string>/tmp/{_xml_escape(label)}.err</string>\n'
        '</dict>\n'
        '</plist>\n'
    )


def generate_taskscheduler_xml(
    *,
    command_argv: list[str],
    every_seconds: int,
    task_name: str,
) -> str:
    """Generate a Windows Task Scheduler import XML."""
    duration = _seconds_to_iso8601(every_seconds)
    command = _xml_escape(command_argv[0])
    args = " ".join(_xml_escape(a) for a in command_argv[1:])
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.4" '
        'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        '  <RegistrationInfo>\n'
        f'    <URI>\\{_xml_escape(task_name)}</URI>\n'
        '  </RegistrationInfo>\n'
        '  <Triggers>\n'
        '    <TimeTrigger>\n'
        '      <Repetition>\n'
        f'        <Interval>{duration}</Interval>\n'
        '        <StopAtDurationEnd>false</StopAtDurationEnd>\n'
        '      </Repetition>\n'
        '      <StartBoundary>2026-01-01T00:00:00</StartBoundary>\n'
        '      <Enabled>true</Enabled>\n'
        '    </TimeTrigger>\n'
        '  </Triggers>\n'
        '  <Settings>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n'
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n'
        '    <StartWhenAvailable>true</StartWhenAvailable>\n'
        '  </Settings>\n'
        '  <Actions>\n'
        '    <Exec>\n'
        f'      <Command>{command}</Command>\n'
        f'      <Arguments>{args}</Arguments>\n'
        '    </Exec>\n'
        '  </Actions>\n'
        '</Task>\n'
    )


def _seconds_to_cron(seconds: int) -> str:
    if seconds < 60:
        raise ValueError("cron supports minute resolution at best")
    minutes = seconds // 60
    if minutes < 60:
        return f"*/{minutes} * * * *"
    hours = minutes // 60
    if hours < 24:
        return f"0 */{hours} * * *" if hours > 1 else "0 * * * *"
    days = hours // 24
    return f"0 0 */{days} * *" if days > 1 else "0 0 * * *"


def _seconds_to_iso8601(seconds: int) -> str:
    if seconds < 60:
        raise ValueError("interval below 1 minute not supported")
    minutes = seconds // 60
    if minutes < 60:
        return f"PT{minutes}M"
    hours = minutes // 60
    if hours < 24:
        return f"PT{hours}H"
    days = hours // 24
    return f"P{days}D"
