from pathlib import Path
import os
from unittest.mock import patch

import pytest

import skills.youtube_transcribe.config as config_module
from skills.youtube_transcribe.config import (
    Config,
    load_config,
    save_config,
    get_api_key,
    set_api_key,
    mask_key,
    DEFAULT_CONFIG,
)


def test_default_config_has_whisper_local_default():
    assert DEFAULT_CONFIG.default_backend == "whisper-local"
    assert DEFAULT_CONFIG.fallback_backend == "whisper-local"


def test_save_and_load_roundtrip(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg = Config(
        default_backend="gemini",
        fallback_backend="whisper-local",
        whisper_model="large",
        gemini_model="gemini-2.5-pro",
        groq_model="whisper-large-v3-turbo",
        openai_model="whisper-1",
        deepgram_model="nova-3",
        assemblyai_model="best",
        custom_base_url="",
        custom_model="",
        whisper_device="auto",
        whisper_compute_type="auto",
        beam_size=5,
        vad=True,
        language="auto",
        timestamps=True,
        srt=True,
        output_dir="./transcripts",
        keep_audio=False,
        yt_dlp_auto_update=True,
        cookies_file="",
        fast_path_enabled=True,
    )
    save_config(cfg, cfg_path)
    loaded = load_config(cfg_path)
    assert loaded == cfg


def test_load_missing_file_returns_default(tmp_path: Path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg == DEFAULT_CONFIG


def test_get_api_key_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-value")
    assert get_api_key("gemini", env_path=tmp_path / ".env") == "env-value"


def test_get_api_key_from_env_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("GROQ_API_KEY=file-value\n")
    assert get_api_key("groq", env_path=env_path) == "file-value"


def test_set_api_key_writes_env(tmp_path: Path):
    env_path = tmp_path / ".env"
    set_api_key("openai", "sk-test", env_path=env_path)
    content = env_path.read_text()
    assert "OPENAI_API_KEY=sk-test" in content


def test_mask_key_short():
    assert mask_key("ab") == "***"


def test_mask_key_long():
    masked = mask_key("sk-1234567890abcdef")
    assert masked.startswith("sk-")
    assert masked.endswith("cdef")
    assert "*" in masked


def test_set_api_key_rejects_newline(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "ENV_PATH", tmp_path / ".env")
    with pytest.raises(ValueError, match="newline"):
        config_module.set_api_key("openai", "abc\ndef")


def test_load_config_raises_on_malformed_toml(tmp_path):
    bad = tmp_path / "config.toml"
    bad.write_text("not = valid = toml = [[[", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed TOML"):
        config_module.load_config(bad)
