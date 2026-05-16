"""Report-mode prompt templates: built-in + user override.

Architecture mirrors `vision/prompts.py` from v0.10.1, but the prompts
themselves operate on different inputs (transcript + visual_segments
JSON, not raw video) and produce a different output (structured
outline JSON, not per-moment description).

Resolution order (highest priority first):
  1. CLI `--prompt-file <path>` — full template; optional global prefix.
  2. User `~/.neurolearn/report_prompts.toml` — `[prompts.<type>]`.
  3. Built-in `report/data/report_prompts_default.toml`.
  4. Fall through to `generic` for unknown types.

User TOML shape mirrors the built-in. Same `[global]` prefix mechanism,
same `append_global` per-type flag, same support for brand-new custom
types (e.g. `[prompts.cooking-recipe]`).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


_USER_REPORT_PROMPTS_PATH = Path.home() / ".neurolearn" / "report_prompts.toml"

# Built-in types — kept tight in v0.10.2 (tutorial / vlog / generic).
# More types can be added by editing the TOML or via user overrides
# without code changes.
BUILTIN_REPORT_TYPES = (
    "tutorial",
    "vlog",
    "generic",
)
DEFAULT_REPORT_TYPE = "generic"

# Tutorial template is reused for `code` videos — v0.10.1 auto-detect
# treats them separately at annotation time, but for the written REPORT
# they share the same step-by-step structure. The renderer picks the
# template by report type, not by underlying video_type.
_VIDEO_TYPE_TO_REPORT_TYPE = {
    "tutorial": "tutorial",
    "code": "tutorial",
    "demo": "tutorial",        # demos are tutorial-shaped writeups
    "vlog": "vlog",
    "lecture": "generic",
    "interview": "generic",
    "review": "generic",
    "talking_head": "generic",
    "generic": "generic",
}


def map_video_type_to_report_type(video_type: str | None) -> str:
    """Translate the v0.10.1 video-type taxonomy onto our 3 report
    templates. Unknown types fall through to generic."""
    if not video_type:
        return DEFAULT_REPORT_TYPE
    return _VIDEO_TYPE_TO_REPORT_TYPE.get(video_type, DEFAULT_REPORT_TYPE)


@dataclass
class ReportPromptSpec:
    """Resolved report-mode prompt template ready for `format_report_prompt`."""
    video_type: str
    template: str
    used_global_prefix: bool
    source: str    # "builtin" | "user_override" | "cli_file"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_report_prompt(
    video_type: str = DEFAULT_REPORT_TYPE,
    *,
    user_path: Path | None = None,
    custom_template: str | None = None,
    use_global_prefix: bool = True,
) -> ReportPromptSpec:
    """Resolve a report-mode prompt template for the given video type."""
    builtin = _load_builtin()
    user = _load_user(user_path)

    global_prefix = _resolve_global_prefix(builtin, user)

    if custom_template is not None:
        template = (
            global_prefix + "\n\n" + custom_template
            if use_global_prefix and global_prefix
            else custom_template
        )
        return ReportPromptSpec(
            video_type="custom",
            template=template,
            used_global_prefix=bool(use_global_prefix and global_prefix),
            source="cli_file",
        )

    entry, source = _resolve_type_entry(builtin, user, video_type)

    type_prompt = entry["prompt"]
    type_appends_global = bool(entry.get("append_global", True))
    used_prefix = type_appends_global and use_global_prefix and bool(global_prefix)
    template = (
        global_prefix + "\n\n" + type_prompt
        if used_prefix
        else type_prompt
    )
    return ReportPromptSpec(
        video_type=video_type,
        template=template,
        used_global_prefix=used_prefix,
        source=source,
    )


def format_report_prompt(
    template: str,
    *,
    target_language: str,
    user_filter: str = "",
    transcript_excerpt: str = "",
    visual_segments_excerpt: str = "",
) -> str:
    """Substitute runtime values into a resolved report-mode template.

    Placeholders: {target_language}, {user_filter}, {transcript_excerpt},
    {visual_segments_excerpt}. Missing placeholders in a template are
    fine — Python's `.format()` only substitutes what's present.
    """
    # Use a defensive format_map so templates that don't reference all
    # placeholders don't blow up; missing ones become empty strings.
    class _SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    values = _SafeDict(
        target_language=target_language,
        user_filter=user_filter,
        transcript_excerpt=transcript_excerpt,
        visual_segments_excerpt=visual_segments_excerpt,
    )
    return template.format_map(values)


def list_known_report_types(*, user_path: Path | None = None) -> list[str]:
    """All recognized report types — built-in plus any user-defined."""
    builtin = _load_builtin()
    user = _load_user(user_path)
    types = set(builtin.get("prompts", {}).keys())
    types.update(user.get("prompts", {}).keys())
    return sorted(types)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_builtin() -> dict:
    """Read the shipped report_prompts_default.toml from package data."""
    text = (
        files("skills.neurolearn.report.data")
        .joinpath("report_prompts_default.toml")
        .read_text(encoding="utf-8")
    )
    return tomllib.loads(text)


def _load_user(user_path: Path | None) -> dict:
    """Read user report_prompts.toml — empty dict when missing / malformed.

    A broken user TOML must NOT crash the pipeline — we silently fall
    back to the built-in. The user gets a heads-up via the loader
    source (`builtin` instead of `user_override`)."""
    path = user_path or _USER_REPORT_PROMPTS_PATH
    if path is None or not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _resolve_global_prefix(builtin: dict, user: dict) -> str:
    """User's [global] prefix wins over built-in when present."""
    user_prefix = (user.get("global") or {}).get("prefix")
    if isinstance(user_prefix, str) and user_prefix.strip():
        return user_prefix
    builtin_prefix = (builtin.get("global") or {}).get("prefix", "")
    return builtin_prefix if isinstance(builtin_prefix, str) else ""


def _resolve_type_entry(
    builtin: dict, user: dict, video_type: str,
) -> tuple[dict, str]:
    """User TOML wins. Falls back to built-in. Unknown types → generic."""
    user_entry = (user.get("prompts") or {}).get(video_type)
    if isinstance(user_entry, dict) and "prompt" in user_entry:
        return user_entry, "user_override"

    builtin_entry = (builtin.get("prompts") or {}).get(video_type)
    if isinstance(builtin_entry, dict) and "prompt" in builtin_entry:
        return builtin_entry, "builtin"

    generic = (builtin.get("prompts") or {}).get(DEFAULT_REPORT_TYPE, {})
    return generic, "builtin"
