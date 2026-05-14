"""Load preset values: built-in defaults < user config.toml < external --config < CLI flags."""
from __future__ import annotations

import tomllib
from importlib.resources import files
from pathlib import Path
from typing import Any

from skills.neurolearn.presets.registry import REGISTRY

DEFAULT_USER_CONFIG = Path.home() / ".neurolearn" / "config.toml"


def _load_builtin() -> dict:
    text = (
        files("skills.neurolearn.presets.data")
        .joinpath("presets_default.toml")
        .read_text(encoding="utf-8")
    )
    return tomllib.loads(text)


def _load_toml(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def list_preset_names() -> list[str]:
    return list(_load_builtin().get("presets", {}).keys())


def load_preset_values(
    preset_name: str,
    *,
    user_config_path: Path | None = None,
    external_config_path: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve final values for `preset_name`. Priority (lowest to highest):
      1. registry defaults
      2. built-in presets_default.toml [presets.<name>]
      3. user ~/.neurolearn/config.toml [presets.<name>] (or external if given)
      4. CLI overrides
    """
    builtin = _load_builtin()
    presets = builtin.get("presets", {})
    if preset_name not in presets:
        raise KeyError(f"Unknown preset: {preset_name}. Known: {list(presets.keys())}")

    # 1. registry defaults
    values: dict[str, Any] = {f.key: f.default for f in REGISTRY}

    # 2. built-in preset overrides
    values.update(presets[preset_name])

    # 3. user config OR external --config
    config_path = (
        external_config_path
        if external_config_path
        else (user_config_path or DEFAULT_USER_CONFIG)
    )
    user_data = _load_toml(config_path)
    user_preset = user_data.get("presets", {}).get(preset_name, {})
    values.update(user_preset)

    # 4. CLI overrides
    if cli_overrides:
        for k, v in cli_overrides.items():
            if v is not None:
                values[k] = v

    return values


def resolve_with_env_checks(
    preset_name: str,
    *,
    user_config_path: Path | None = None,
    external_config_path: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Same as load_preset_values, but applies silent fallbacks for missing API keys.

    Returns (values, info_messages). Info messages should be printed to stderr
    so user knows why visual mode is off.
    """
    from skills.neurolearn.config import get_api_key

    values = load_preset_values(
        preset_name,
        user_config_path=user_config_path,
        external_config_path=external_config_path,
        cli_overrides=cli_overrides,
    )
    info: list[str] = []

    vb = values.get("vision_backend")
    _VISION_KEY_MAP = {
        "gemini": ("gemini", "GEMINI_API_KEY"),
        "claude": ("anthropic", "ANTHROPIC_API_KEY"),
        "openai": ("openai", "OPENAI_API_KEY"),
    }
    if vb in _VISION_KEY_MAP:
        backend_key, env_var = _VISION_KEY_MAP[vb]
        if not get_api_key(backend_key):
            values["vision_backend"] = "off"
            info.append(
                f"ℹ Visual mode disabled: {env_var} not set. "
                f"Add to ~/.neurolearn/.env to enable."
            )

    return values, info
