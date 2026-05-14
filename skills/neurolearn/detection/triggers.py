"""Trigger config loading and phrase entry parsing.

Phrase entries:
  "phrase"            → weight 1.0
  ["phrase", 1.5]     → weight 1.5

Sections:
  [triggers.universal] phrases = [...]
  [triggers.raw] phrases = [...]
  [triggers.languages.<lang>] soft = [...] strict = [...]
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

DEFAULT_USER_PATH = Path.home() / ".neurolearn" / "triggers.toml"


def parse_phrase_entry(entry) -> tuple[str, float]:
    """Returns (phrase, weight) or raises ValueError."""
    if isinstance(entry, str):
        if not entry:
            raise ValueError("phrase cannot be empty")
        return entry, 1.0
    if isinstance(entry, list) and len(entry) == 2:
        phrase, weight = entry
        if not isinstance(phrase, str) or not isinstance(weight, (int, float)):
            raise ValueError(f"Invalid phrase entry types: {entry}")
        return phrase, float(weight)
    raise ValueError(f"Phrase must be 'string' or ['string', number], got: {entry!r}")


def _parse_phrases_list(items) -> dict[str, float]:
    out: dict[str, float] = {}
    for entry in items or []:
        phrase, weight = parse_phrase_entry(entry)
        out[phrase] = weight
    return out


@dataclass
class LanguageTriggers:
    soft: dict[str, float] = field(default_factory=dict)
    strict: dict[str, float] = field(default_factory=dict)


@dataclass
class TriggerConfig:
    default_language: str = "en"
    universal_match_method: str = "semantic"
    universal_match_threshold: float = 0.65

    universal: dict[str, float] = field(default_factory=dict)
    raw: dict[str, float] = field(default_factory=dict)
    languages: dict[str, LanguageTriggers] = field(default_factory=dict)


def _load_toml(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _load_builtin() -> dict:
    text = files("skills.neurolearn.detection.data").joinpath(
        "triggers_default.toml"
    ).read_text(encoding="utf-8")
    return tomllib.loads(text)


def _build_config(raw: dict) -> TriggerConfig:
    cfg = TriggerConfig(
        default_language=raw.get("default_language", "en"),
        universal_match_method=raw.get("universal_match_method", "semantic"),
        universal_match_threshold=raw.get("universal_match_threshold", 0.65),
    )
    triggers = raw.get("triggers", {})
    cfg.universal = _parse_phrases_list(triggers.get("universal", {}).get("phrases"))
    cfg.raw = _parse_phrases_list(triggers.get("raw", {}).get("phrases"))
    for lang, sect in (triggers.get("languages") or {}).items():
        cfg.languages[lang] = LanguageTriggers(
            soft=_parse_phrases_list(sect.get("soft")),
            strict=_parse_phrases_list(sect.get("strict")),
        )
    return cfg


def _merge(builtin: TriggerConfig, user: TriggerConfig) -> TriggerConfig:
    """User extends builtin (default). User wins on conflicts (overrides weight)."""
    out = TriggerConfig(
        default_language=user.default_language or builtin.default_language,
        universal_match_method=user.universal_match_method,
        universal_match_threshold=user.universal_match_threshold,
        universal={**builtin.universal, **user.universal},
        raw={**builtin.raw, **user.raw},
    )
    # Per-language merge
    all_langs = set(builtin.languages) | set(user.languages)
    for lang in all_langs:
        b = builtin.languages.get(lang, LanguageTriggers())
        u = user.languages.get(lang, LanguageTriggers())
        out.languages[lang] = LanguageTriggers(
            soft={**b.soft, **u.soft},
            strict={**b.strict, **u.strict},
        )
    return out


def load_triggers(
    user_path: Path | None = DEFAULT_USER_PATH,
    *,
    force_replace: bool = False,
) -> TriggerConfig:
    """Load merged config: built-in defaults + user overrides.

    If user file has `mode = "replace"` at top level, builtin is skipped.
    `force_replace=True` (CLI `--no-default-triggers`) skips builtin even
    when the user file doesn't set mode.
    """
    user_raw = _load_toml(user_path) if user_path else {}

    if force_replace:
        # User-only config (or empty if no user file).
        return _build_config(user_raw) if user_raw else TriggerConfig()

    builtin_cfg = _build_config(_load_builtin())
    if not user_raw:
        return builtin_cfg

    user_cfg = _build_config(user_raw)
    if user_raw.get("mode") == "replace":
        return user_cfg
    return _merge(builtin_cfg, user_cfg)
