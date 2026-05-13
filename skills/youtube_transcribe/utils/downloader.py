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
_INSTAGRAM_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/([\w\-]+)",
    re.IGNORECASE,
)
_STATE_PATH = CONFIG_DIR / "state.json"


def is_url(s: str) -> bool:
    return bool(_URL_RE.match(s))


def is_youtube_url(s: str) -> bool:
    return bool(_YOUTUBE_RE.match(s))


def is_instagram_url(s: str) -> bool:
    return bool(_INSTAGRAM_RE.match(s))


def extract_youtube_video_id(s: str) -> str | None:
    m = _YOUTUBE_RE.match(s)
    return m.group(1) if m else None


def extract_instagram_shortcode(s: str) -> str | None:
    m = _INSTAGRAM_RE.match(s)
    return m.group(1) if m else None


def build_ytdlp_command(
    *,
    url: str,
    output_template: str,
    cookies_file: str = "",
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
    if cookies_file:
        # Explicit Netscape cookies.txt path — NEVER --cookies-from-browser.
        # See project memory: feedback_cookies_strict_file_only.md
        cmd += ["--cookies", cookies_file]
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
    # Instagram-specific signals first (more specific than generic YouTube ones)
    if "instagram" in s and (
        "login" in s or "session" in s or "logged" in s or "rate-limit" in s
    ):
        return (
            "Instagram требует залогиненную сессию. Зарегистрируй cookies-файл:\n"
            "  yt-tr subscribes cookies set instagram <path-to-cookies.txt>\n"
            "Stories и приватные аккаунты — только с cookies того, кто на них подписан."
        )
    if "sign in to confirm you" in s or "bot" in s or "403" in s:
        return ("YouTube заблокировал запрос как бот. Зарегистрируй cookies-файл:\n"
                "  yt-tr config set-cookies <path-to-cookies.txt>\n"
                "Также может помочь обновить yt-dlp: youtube-transcribe update-deps.")
    if "video is private" in s or "members-only" in s:
        return "Видео приватное или только для подписчиков. Нужны cookies залогиненного аккаунта."
    if "age" in s and "restrict" in s:
        return "Видео с возрастным ограничением. Передай --cookies-file <path>."
    if "country" in s or "geo" in s:
        return "Видео заблокировано в твоём регионе. Попробуй VPN или другой регион."
    if "unable to download" in s and "requested format" in s:
        return "Формат недоступен. Возможно, видео — только live-stream или premiere."
    return "Скачивание упало. См. полный stderr выше."


def download_audio(
    url: str,
    output_dir: Path,
    *,
    cookies_file: str = "",
    timeout_seconds: int = 600,
) -> Path:
    """Download audio from URL via yt-dlp. Returns path to the audio file.

    `cookies_file` (Netscape cookies.txt) is the ONLY supported way to pass
    auth. The skill never uses `--cookies-from-browser` — see project memory
    file `feedback_cookies_strict_file_only.md`.
    """
    if shutil.which("yt-dlp") is None:
        raise DownloadError("yt-dlp не найден в PATH. Установи через `uv sync` или `pip install yt-dlp`.")
    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "audio_%(id)s.%(ext)s")
    cmd = build_ytdlp_command(
        url=url,
        output_template=template,
        cookies_file=cookies_file,
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


def download_video(
    url: str,
    output_dir: Path,
    *,
    cookies_file: str = "",
    timeout_seconds: int = 1200,
) -> Path:
    """Download mp4 (audio+video) from URL via yt-dlp. Returns path to the mp4 file.

    Used by visual mode (--with-visuals) — Gemini multimodal needs both video frames
    and audio. `cookies_file` is the only supported auth mechanism; see
    `download_audio` for the rationale.
    """
    if shutil.which("yt-dlp") is None:
        raise DownloadError("yt-dlp не найден в PATH.")
    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "video_%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        # Single combined mp4 file (audio+video). Prefer 720p to keep size manageable
        # for Gemini File API uploads (max 2 GB, but smaller is faster).
        "-f", "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best",
        "--merge-output-format", "mp4",
        "--geo-bypass",
        "--no-playlist",
        "-o", template,
    ]
    if cookies_file:
        cmd += ["--cookies", cookies_file]
    cmd.append(url)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired:
        raise DownloadError(f"Скачивание видео превысило {timeout_seconds} сек.")

    if result.returncode != 0:
        hint = _diagnose_ytdlp_error(result.stderr or "")
        raise DownloadError(f"yt-dlp упал при скачивании mp4: {hint}\n{result.stderr}")

    # Find the resulting mp4 — yt-dlp may have produced .mp4 directly or merged from parts
    for f in output_dir.glob("video_*.mp4"):
        return f
    # Fallback: any mp4 in the dir
    for f in output_dir.glob("*.mp4"):
        return f
    raise DownloadError(f"yt-dlp finished but no mp4 found in {output_dir}")


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


def parse_yt_date(s: str | None) -> date | None:
    """yt-dlp возвращает 'YYYYMMDD' либо None."""
    if not s or len(s) != 8:
        return None
    try:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _extract_flat(
    url: str, *, cookies_file: str | None = None,
) -> dict:
    """Тонкая обёртка над yt-dlp YoutubeDL.extract_info(extract_flat=True).
    Изолирована, чтобы тесты могли мокать её точечно через patch.

    `cookies_file` — optional path to a Netscape-format cookies.txt file.
    Used for Instagram (anon → 401). The function NEVER uses
    `cookies-from-browser` — that would pull all of the user's browser
    cookies into process memory. See the project memory file
    `feedback_cookies_strict_file_only.md` for the rationale.
    """
    from yt_dlp import YoutubeDL  # импорт локальный — yt-dlp тяжёлый
    from yt_dlp.utils import DownloadError as YtDlpDownloadError
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "geo_bypass": True,
    }
    if cookies_file:
        opts["cookiefile"] = cookies_file
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


def expand_channel_or_playlist(
    url: str, limit: int, *, cookies_file: str | None = None,
) -> list[ChannelEntry]:
    """Развернуть канал/плейлист в первые N entries. Только метадата, без скачивания.

    `cookies_file` (Netscape cookies.txt) пробрасывается в yt-dlp для
    платформ, которым нужна залогиненная сессия (Instagram всегда,
    приватные TikTok-аккаунты). См. `_extract_flat` для security-обоснования
    почему ТОЛЬКО файл, не `cookies-from-browser`.
    """
    info = _extract_flat(url, cookies_file=cookies_file)
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
            upload_date=parse_yt_date(e.get("upload_date")),
            channel=info.get("title") or info.get("uploader"),
        ))
    return out


def search_videos(query: str, limit: int) -> list[ChannelEntry]:
    """YouTube search via yt-dlp `ytsearchN:query` URL.

    No YouTube Data API key needed. Returns top-N results by relevance
    (yt-dlp's default ranking — close to YouTube web search order).
    """
    if not query.strip():
        raise DownloadError("--search query is empty")
    n = max(1, int(limit))
    search_url = f"ytsearch{n}:{query.strip()}"
    info = _extract_flat(search_url)
    entries = info.get("entries") or []
    out: list[ChannelEntry] = []
    for e in entries[:n]:
        if not e or not e.get("id"):
            continue
        vid = e["id"]
        out.append(ChannelEntry(
            video_id=vid,
            url=e.get("url") or _yt_url_from_id(vid),
            title=e.get("title"),
            duration_sec=int(e["duration"]) if e.get("duration") else None,
            upload_date=parse_yt_date(e.get("upload_date")),
            channel=e.get("channel") or e.get("uploader"),
        ))
    return out
