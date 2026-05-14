"""Config loading/saving and API key handling.

Config layout (TOML):
  ~/.neurolearn/config.toml — non-secret defaults
  ~/.neurolearn/.env        — API keys (NOT committed, perms 0600)

API key precedence:
  1. process env var
  2. ~/.neurolearn/.env
  3. None (caller must handle)

v0.9 — project was renamed from `youtube-transcribe` to `neurolearn`.
On first run after upgrade, if `~/.youtube-transcribe/` exists and
`~/.neurolearn/` doesn't, we migrate the directory once (`mv`) so the
user keeps their config, cookies, .env, subscribes.toml, and history.
"""
from __future__ import annotations

import os
import sys
import tomllib  # stdlib on Python ≥3.11 (requires-python in pyproject)
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import tomli_w
from dotenv import dotenv_values

_LEGACY_CONFIG_DIR = Path.home() / ".youtube-transcribe"
CONFIG_DIR = Path.home() / ".neurolearn"


def _maybe_migrate_legacy_config_dir() -> None:
    """If a pre-v0.9 `~/.youtube-transcribe/` exists and the new
    `~/.neurolearn/` doesn't, rename the directory once. Idempotent.

    Also rewrites any absolute paths inside `config.toml` and
    `subscribes.toml` that still point at the legacy `.youtube-transcribe/`
    directory — typically the registered `cookies_file` paths.

    Prints a one-line notice to stderr so the user knows it happened.
    Failures are non-fatal — fall back to creating a fresh `.neurolearn/`.
    """
    if CONFIG_DIR.exists():
        return
    if not _LEGACY_CONFIG_DIR.exists():
        return
    try:
        _LEGACY_CONFIG_DIR.rename(CONFIG_DIR)
    except OSError as e:
        print(
            f"[neurolearn] Could not migrate {_LEGACY_CONFIG_DIR} → "
            f"{CONFIG_DIR}: {e}. Move the directory manually if needed.",
            file=sys.stderr,
        )
        return

    # Patch absolute paths inside migrated TOML files (e.g. cookies_file
    # paths stored as absolute strings still point at the legacy dir
    # because we moved the directory, not edited the contents).
    _rewrite_legacy_paths_in_toml(CONFIG_DIR)
    print(
        f"[neurolearn] Migrated config: {_LEGACY_CONFIG_DIR} → {CONFIG_DIR}",
        file=sys.stderr,
    )


def _rewrite_legacy_paths_in_toml(config_dir: Path) -> None:
    """Replace `.youtube-transcribe` substrings inside TOML config files
    with `.neurolearn` so registered absolute paths follow the rename.
    """
    legacy_str = _LEGACY_CONFIG_DIR.name  # ".youtube-transcribe"
    new_str = config_dir.name              # ".neurolearn"
    for fname in ("config.toml", "subscribes.toml"):
        f = config_dir / fname
        if not f.exists():
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue
        if legacy_str not in content:
            continue
        new_content = content.replace(legacy_str, new_str)
        try:
            f.write_text(new_content, encoding="utf-8")
        except OSError as e:
            print(
                f"[neurolearn] Could not patch legacy paths in {f}: {e}",
                file=sys.stderr,
            )


_maybe_migrate_legacy_config_dir()

CONFIG_PATH = CONFIG_DIR / "config.toml"
ENV_PATH = CONFIG_DIR / ".env"

BackendName = Literal[
    "smart", "subtitles", "whisper-local",
    "gemini", "groq", "openai", "deepgram", "assemblyai", "custom",
]
WhisperModel = Literal["turbo", "large", "medium", "small", "distil"]


@dataclass
class Config:
    default_backend: BackendName = "whisper-local"
    fallback_backend: BackendName = "whisper-local"

    whisper_model: WhisperModel = "turbo"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    beam_size: int = 5
    vad: bool = True

    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "whisper-large-v3-turbo"
    openai_model: str = "whisper-1"
    deepgram_model: str = "nova-3"
    assemblyai_model: str = "best"
    custom_base_url: str = ""
    custom_model: str = ""

    language: str = "auto"
    timestamps: bool = True
    srt: bool = True
    output_dir: str = "./transcripts"

    keep_audio: bool = False
    # Auto-update of yt-dlp via `yt-dlp -U` is opt-IN since v0.8. Reason:
    # silent supply-chain widening (a `curl | sh`-installed yt-dlp could
    # get opportunistically upgraded). When you do hit YouTube extractor
    # breakage, run `neurolearn update-deps` manually instead.
    yt_dlp_auto_update: bool = False
    # Path to a Netscape cookies.txt file used by yt-dlp for YouTube
    # downloads that require sign-in (age-restricted, member-only, etc.).
    # By design we DO NOT support `--cookies-from-browser` — that flag
    # pulls every cookie from your browser into the process. Export only
    # the cookies you want via an extension like "Get cookies.txt LOCALLY"
    # and register the file with `neurolearn config set-key …`.
    cookies_file: str = ""
    fast_path_enabled: bool = True

    # === v0.7+ analyze defaults ===
    # User's choice for the LLM that processes transcripts in `research` /
    # `subscribes update` / `batch --then-analyze` when no `--analyze-backend`
    # flag is given. Values: None (not yet chosen — onboarding will prompt),
    # "skip" (never auto-analyze; emit combined.md and let the chat-side LLM
    # do it), or one of {gemini, claude, openai, ollama}.
    analyze_backend: str | None = None

    # === v0.8+ per-platform cookies for subscribes (IG/TikTok) ===
    # Path to a Netscape-format cookies.txt file the user explicitly
    # exported from their browser (e.g. via "Get cookies.txt LOCALLY"
    # extension). Empty = no cookies, try anonymous (works for TikTok
    # public videos, fails on Instagram).
    #
    # This is deliberately a FILE path, not a browser-name. The skill
    # NEVER reads cookies directly from the user's browser at runtime
    # (no `--cookies-from-browser`) — that would pull ALL the user's
    # browser cookies into process memory. See
    # ~/.claude/projects/.../feedback_cookies_strict_file_only.md
    instagram_cookies_file: str = ""
    tiktok_cookies_file: str = ""


DEFAULT_CONFIG = Config()


_BACKEND_ENV_VAR = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
    "assemblyai": "ASSEMBLYAI_API_KEY",
    "custom": "CUSTOM_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",       # v0.4: Claude vision backend
}


def _to_toml_dict(cfg: Config) -> dict:
    """Pack Config into nested dict matching the spec layout."""
    d = asdict(cfg)
    return {
        "default_backend": d["default_backend"],
        "fallback_backend": d["fallback_backend"],
        "whisper-local": {
            "model": d["whisper_model"],
            "device": d["whisper_device"],
            "compute_type": d["whisper_compute_type"],
            "beam_size": d["beam_size"],
            "vad": d["vad"],
        },
        "gemini": {"model": d["gemini_model"]},
        "groq": {"model": d["groq_model"]},
        "openai": {"model": d["openai_model"]},
        "deepgram": {"model": d["deepgram_model"]},
        "assemblyai": {"model": d["assemblyai_model"]},
        "custom": {"base_url": d["custom_base_url"], "model": d["custom_model"]},
        "output": {
            "language": d["language"],
            "timestamps": d["timestamps"],
            "srt": d["srt"],
            "output_dir": d["output_dir"],
        },
        "behavior": {
            "keep_audio": d["keep_audio"],
            "yt_dlp_auto_update": d["yt_dlp_auto_update"],
            "cookies_file": d["cookies_file"],
            "fast_path_enabled": d["fast_path_enabled"],
        },
        "analyze": {
            "backend": d["analyze_backend"] or "",
        },
        "instagram": {
            "cookies_file": d["instagram_cookies_file"],
        },
        "tiktok": {
            "cookies_file": d["tiktok_cookies_file"],
        },
    }


def _from_toml_dict(d: dict) -> Config:
    wl = d.get("whisper-local", {})
    out = d.get("output", {})
    beh = d.get("behavior", {})
    analyze = d.get("analyze", {})
    raw_analyze_backend = analyze.get("backend", "")
    ig = d.get("instagram", {})
    tt = d.get("tiktok", {})
    return Config(
        default_backend=d.get("default_backend", DEFAULT_CONFIG.default_backend),
        fallback_backend=d.get("fallback_backend", DEFAULT_CONFIG.fallback_backend),
        whisper_model=wl.get("model", DEFAULT_CONFIG.whisper_model),
        whisper_device=wl.get("device", DEFAULT_CONFIG.whisper_device),
        whisper_compute_type=wl.get("compute_type", DEFAULT_CONFIG.whisper_compute_type),
        beam_size=wl.get("beam_size", DEFAULT_CONFIG.beam_size),
        vad=wl.get("vad", DEFAULT_CONFIG.vad),
        gemini_model=d.get("gemini", {}).get("model", DEFAULT_CONFIG.gemini_model),
        groq_model=d.get("groq", {}).get("model", DEFAULT_CONFIG.groq_model),
        openai_model=d.get("openai", {}).get("model", DEFAULT_CONFIG.openai_model),
        deepgram_model=d.get("deepgram", {}).get("model", DEFAULT_CONFIG.deepgram_model),
        assemblyai_model=d.get("assemblyai", {}).get("model", DEFAULT_CONFIG.assemblyai_model),
        custom_base_url=d.get("custom", {}).get("base_url", ""),
        custom_model=d.get("custom", {}).get("model", ""),
        language=out.get("language", DEFAULT_CONFIG.language),
        timestamps=out.get("timestamps", DEFAULT_CONFIG.timestamps),
        srt=out.get("srt", DEFAULT_CONFIG.srt),
        output_dir=out.get("output_dir", DEFAULT_CONFIG.output_dir),
        keep_audio=beh.get("keep_audio", DEFAULT_CONFIG.keep_audio),
        yt_dlp_auto_update=beh.get("yt_dlp_auto_update", DEFAULT_CONFIG.yt_dlp_auto_update),
        # Backward-compat: pre-v0.8 configs may still have `cookies_browser`
        # — silently drop it (we no longer support `--cookies-from-browser`).
        cookies_file=beh.get("cookies_file", DEFAULT_CONFIG.cookies_file),
        fast_path_enabled=beh.get("fast_path_enabled", DEFAULT_CONFIG.fast_path_enabled),
        # Empty string in TOML means "not chosen yet" — preserve None semantics.
        analyze_backend=raw_analyze_backend if raw_analyze_backend else None,
        instagram_cookies_file=ig.get("cookies_file", ""),
        tiktok_cookies_file=tt.get("cookies_file", ""),
    )


def migrate_v01_to_v02(path: Path = CONFIG_PATH) -> None:
    """Migrate v0.1.x config.toml to v0.2 format.

    Preserves user's existing settings as `[presets.custom_legacy]` and
    sets `default_preset = "custom_legacy"` so behavior remains identical.

    No-op if file doesn't exist or already has `default_preset` key.
    """
    if not path.exists():
        return

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if "default_preset" in raw:
        return  # already v0.2

    # Build legacy preset from v0.1 fields
    legacy: dict = {}
    if "default_backend" in raw:
        legacy["transcribe_backend"] = raw["default_backend"]
    if "fallback_backend" in raw:
        legacy["fallback_backend"] = raw["fallback_backend"]
    # Preserve nested whisper-local, gemini, etc. by appending v0.2 sections

    new_text = path.read_text(encoding="utf-8")
    new_text = 'default_preset = "custom_legacy"\n\n' + new_text
    new_text += "\n[presets.custom_legacy]\n"
    for k, v in legacy.items():
        new_text += f'{k} = "{v}"\n'

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return DEFAULT_CONFIG
    try:
        migrate_v01_to_v02(path)   # ← auto-upgrade on load
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(
            f"Malformed TOML in {path}: {e}. "
            f"Restore from backup or run `neurolearn config wizard`."
        ) from e
    return _from_toml_dict(raw)


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = tomli_w.dumps(_to_toml_dict(cfg)).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def get_api_key(backend: str, env_path: Path = ENV_PATH) -> str | None:
    var = _BACKEND_ENV_VAR.get(backend)
    if not var:
        return None
    # 1. process env
    val = os.environ.get(var)
    if val:
        return val
    # 2. ~/.neurolearn/.env
    if env_path.exists():
        values = dotenv_values(env_path)
        v = values.get(var)
        if v:
            return v
    return None


def set_api_key(backend: str, value: str, env_path: Path = ENV_PATH) -> None:
    if "\n" in value or "\r" in value:
        raise ValueError("API key value cannot contain newline characters")
    var = _BACKEND_ENV_VAR.get(backend)
    if not var:
        raise ValueError(f"Unknown backend for env var: {backend}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if env_path.exists():
        existing = dict(dotenv_values(env_path))
    existing[var] = value

    lines = [f"{k}={v}" for k, v in existing.items() if v is not None]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    if os.name != "nt":
        # Atomic create-or-truncate with mode 0600 from the start, closing
        # the TOCTOU window between write_text() and chmod() where another
        # local user could read the freshly-written API key. On Windows
        # mode bits don't apply (NTFS ACLs do), so fall back to write_text.
        fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
    else:
        env_path.write_bytes(payload)


def mask_key(key: str) -> str:
    """sk-1234567890abcdef → sk-1***cdef"""
    if not key or len(key) < 8:
        return "***"
    return key[:4] + "***" + key[-4:]
