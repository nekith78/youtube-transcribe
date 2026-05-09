"""Wrapper around yt-dlp with cookies, retries, friendly errors, and auto-update.
Also exposes probe_input + expand_channel_or_playlist for the Resolver (Task 7B)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from skills.youtube_transcribe.config import CONFIG_DIR


class DownloadError(Exception):
    """Raised on download failure with a friendly hint."""


_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_YOUTUBE_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w\-]+)",
    re.IGNORECASE,
)
_STATE_PATH = CONFIG_DIR / "state.json"


def is_url(s: str) -> bool:
    return bool(_URL_RE.match(s))


def is_youtube_url(s: str) -> bool:
    return bool(_YOUTUBE_RE.match(s))


def extract_youtube_video_id(s: str) -> str | None:
    m = _YOUTUBE_RE.match(s)
    return m.group(1) if m else None


def build_ytdlp_command(
    *,
    url: str,
    output_template: str,
    cookies_browser: str = "",
    audio_format: str = "mp3",
) -> list[str]:
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", audio_format,
        "--audio-quality", "0",
        "--geo-bypass",
        "--no-playlist",
        "-o", output_template,
    ]
    if cookies_browser:
        cmd += ["--cookies-from-browser", cookies_browser]
    cmd.append(url)
    return cmd


def _load_state() -> dict:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def maybe_auto_update_ytdlp(enabled: bool, *, max_age_hours: int = 24) -> bool:
    """If `enabled` and last update was >max_age_hours ago, run `yt-dlp -U`.
    Returns True if an update was attempted."""
    if not enabled:
        return False
    state = _load_state()
    last_iso = state.get("yt_dlp_last_update")
    if last_iso:
        try:
            last = datetime.fromisoformat(last_iso)
            if datetime.now() - last < timedelta(hours=max_age_hours):
                return False
        except ValueError:
            pass

    try:
        subprocess.run(
            ["yt-dlp", "-U"],
            capture_output=True,
            timeout=60,
            check=False,
        )
        state["yt_dlp_last_update"] = datetime.now().isoformat()
        _save_state(state)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _diagnose_ytdlp_error(stderr: str) -> str:
    """Map common yt-dlp errors to actionable hints."""
    s = stderr.lower()
    if "sign in to confirm you" in s or "bot" in s or "403" in s:
        return ("YouTube заблокировал запрос как бот. Попробуй: "
                "--cookies-from-browser chrome (или firefox/edge). "
                "Также может помочь обновить yt-dlp: youtube-transcribe update-deps.")
    if "video is private" in s or "members-only" in s:
        return "Видео приватное или только для подписчиков. Нужны cookies залогиненного аккаунта."
    if "age" in s and "restrict" in s:
        return "Видео с возрастным ограничением. Используй --cookies-from-browser."
    if "country" in s or "geo" in s:
        return "Видео заблокировано в твоём регионе. Попробуй VPN или другой регион."
    if "unable to download" in s and "requested format" in s:
        return "Формат недоступен. Возможно, видео — только live-stream или premiere."
    return "Скачивание упало. См. полный stderr выше."


def download_audio(
    url: str,
    output_dir: Path,
    *,
    cookies_browser: str = "",
    timeout_seconds: int = 600,
) -> Path:
    """Download audio from URL via yt-dlp. Returns path to the audio file."""
    if shutil.which("yt-dlp") is None:
        raise DownloadError("yt-dlp не найден в PATH. Установи через `uv sync` или `pip install yt-dlp`.")
    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "audio_%(id)s.%(ext)s")
    cmd = build_ytdlp_command(
        url=url,
        output_template=template,
        cookies_browser=cookies_browser,
    )

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired:
        raise DownloadError(f"Скачивание превысило {timeout_seconds} сек. Проверь интернет или используй --cookies.")

    if result.returncode != 0:
        hint = _diagnose_ytdlp_error(result.stderr or "")
        raise DownloadError(f"{hint}\n\n--- stderr ---\n{result.stderr}")

    # Find downloaded file
    candidates = sorted(output_dir.glob("audio_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise DownloadError("yt-dlp завершился успешно, но файл не найден.")
    return candidates[0]


# ---------------------------------------------------------------------------
# Task 7B: probe_input + expand_channel_or_playlist for the Resolver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelEntry:
    """Один entry из канала/плейлиста (только метадата, без скачивания)."""
    video_id: str
    url: str
    title: str | None
    duration_sec: int | None
    upload_date: date | None
    channel: str | None


def _yt_url_from_id(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _parse_yt_date(s: str | None) -> date | None:
    """yt-dlp возвращает 'YYYYMMDD' либо None."""
    if not s or len(s) != 8:
        return None
    try:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _extract_flat(url: str) -> dict:
    """Тонкая обёртка над yt-dlp YoutubeDL.extract_info(extract_flat=True).
    Изолирована, чтобы тесты могли мокать её точечно через patch."""
    from yt_dlp import YoutubeDL  # импорт локальный — yt-dlp тяжёлый
    from yt_dlp.utils import DownloadError as YtDlpDownloadError
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "geo_bypass": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except YtDlpDownloadError as e:
        raise DownloadError(_diagnose_ytdlp_error(str(e))) from e


def probe_input(url_or_path: str) -> tuple[Literal["video", "playlist", "local"], dict]:
    """Определить тип входа: одиночное видео / канал-или-плейлист / локальный файл.
    Для локальных файлов возвращает {"path": <str>}.
    Для URL — yt-dlp metadata dict с ключом '_type' = 'video' | 'playlist'."""
    if not is_url(url_or_path):
        p = Path(url_or_path).expanduser().resolve()
        if not p.exists():
            raise DownloadError(f"Файл не найден: {p}")
        return "local", {"path": str(p)}

    info = _extract_flat(url_or_path)
    kind = info.get("_type", "video")
    if kind not in ("video", "playlist"):
        # 'url'-тип означает unresolved redirect; для нашей цели приравниваем к 'video'
        kind = "video"
    return kind, info  # type: ignore[return-value]


def expand_channel_or_playlist(url: str, limit: int) -> list[ChannelEntry]:
    """Развернуть канал/плейлист в первые N entries. Только метадата, без скачивания."""
    info = _extract_flat(url)
    entries = info.get("entries") or []
    out: list[ChannelEntry] = []
    for e in entries[:limit]:
        if not e or not e.get("id"):
            continue
        vid = e["id"]
        out.append(ChannelEntry(
            video_id=vid,
            url=e.get("url") or _yt_url_from_id(vid),
            title=e.get("title"),
            duration_sec=int(e["duration"]) if e.get("duration") else None,
            upload_date=_parse_yt_date(e.get("upload_date")),
            channel=info.get("title") or info.get("uploader"),
        ))
    return out
