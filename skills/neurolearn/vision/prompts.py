"""Vision-LLM prompt templates: built-in types + user overrides.

Resolution order (highest priority first):
  1. CLI `--prompt-file <path>` — loaded as the full template, with
     optional global prefix prepended (`--no-global-prefix` to suppress).
  2. CLI `--video-type <name>` — uses prompts.<name> from user TOML
     (or built-in TOML if user TOML omits this type).
  3. Preset-driven type (e.g. tutorial preset → prompts.tutorial).
  4. Auto-detect from transcript (see detection/video_type_detect.py).
  5. Default: prompts.generic.

User customizations live in `~/.neurolearn/prompts.toml`. Same structure
as the shipped `vision/data/prompts_default.toml`:

    [global]
    prefix = "..."

    [prompts.<type>]
    prompt = "..."
    append_global = true   # default; set false to use ONLY this prompt

User TOML overrides built-in types one-for-one. New types (not in the
shipped TOML) are also accepted — useful for custom workflows.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

_USER_PROMPTS_PATH = Path.home() / ".neurolearn" / "prompts.toml"
# All built-in video-type identifiers. CLI / config layers validate
# against this list so typos fail loudly instead of falling back to
# generic silently. Custom types defined in the user TOML are accepted
# in addition.
BUILTIN_VIDEO_TYPES = (
    "tutorial",
    "lecture",
    "code",
    "demo",
    "interview",
    "vlog",
    "review",
    "talking_head",
    "generic",
)
DEFAULT_VIDEO_TYPE = "generic"


@dataclass
class PromptSpec:
    """Resolved prompt template ready for `format_prompt(...)`."""
    video_type: str
    template: str           # full text with placeholders, ready to .format()
    used_global_prefix: bool
    source: str             # "builtin" | "user_override" | "cli_file" — for debug logging


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_prompt(
    video_type: str = DEFAULT_VIDEO_TYPE,
    *,
    user_path: Path | None = None,
    custom_template: str | None = None,
    use_global_prefix: bool = True,
) -> PromptSpec:
    """Resolve a prompt template for the given video type.

    Priority:
      • custom_template wins outright (CLI --prompt-file). Optionally
        prepends the global prefix unless use_global_prefix is False.
      • Otherwise, look up `prompts.<video_type>` in the user TOML
        (~/.neurolearn/prompts.toml or `user_path`); fall back to
        built-in TOML; finally fall back to the generic type.

    Returns a PromptSpec with the .format()-ready template string.
    """
    builtin = _load_builtin()
    user = _load_user(user_path)

    global_prefix = _resolve_global_prefix(builtin, user)

    if custom_template is not None:
        # CLI --prompt-file mode. Honor use_global_prefix for users who
        # explicitly want their custom prompt to inherit the global rules.
        template = (
            global_prefix + "\n\n" + custom_template
            if use_global_prefix and global_prefix
            else custom_template
        )
        return PromptSpec(
            video_type="custom",
            template=template,
            used_global_prefix=bool(use_global_prefix and global_prefix),
            source="cli_file",
        )

    # Look up by type, falling through user → builtin → generic.
    entry, source = _resolve_type_entry(builtin, user, video_type)

    type_prompt = entry["prompt"]
    type_appends_global = bool(entry.get("append_global", True))
    used_prefix = type_appends_global and use_global_prefix and bool(global_prefix)
    template = (
        global_prefix + "\n\n" + type_prompt
        if used_prefix
        else type_prompt
    )
    return PromptSpec(
        video_type=video_type,
        template=template,
        used_global_prefix=used_prefix,
        source=source,
    )


def format_prompt(
    template: str,
    *,
    language: str,
    transcript_snippet: str,
    start_sec: float,
    end_sec: float,
) -> str:
    """Substitute runtime values into a resolved prompt template."""
    return template.format(
        language=language,
        transcript_snippet=transcript_snippet,
        start_sec=start_sec,
        end_sec=end_sec,
    )


def list_known_types(*, user_path: Path | None = None) -> list[str]:
    """All recognized video types — built-in plus any user-defined."""
    builtin = _load_builtin()
    user = _load_user(user_path)
    types = set(builtin.get("prompts", {}).keys())
    types.update(user.get("prompts", {}).keys())
    return sorted(types)


# Backward-compat alias: existing imports `from prompts import DEFAULT_PROMPT`
# (legacy v0.10 callers) still get a usable template via the new loader.
# Loaded lazily on first access so test fixtures can patch the TOML.


def _legacy_default_prompt() -> str:
    return load_prompt("generic").template


class _LegacyDefaultPromptProxy:
    """Compatibility shim — old code that does
    `from skills.neurolearn.vision.prompts import DEFAULT_PROMPT`
    still works, but the value resolves from the new TOML on first use.
    """
    def __str__(self) -> str:
        return _legacy_default_prompt()

    def format(self, **kw):
        return _legacy_default_prompt().format(**kw)


DEFAULT_PROMPT = _LegacyDefaultPromptProxy()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_builtin() -> dict:
    """Read the shipped prompts_default.toml from package data."""
    text = (
        files("skills.neurolearn.vision.data")
        .joinpath("prompts_default.toml")
        .read_text(encoding="utf-8")
    )
    return tomllib.loads(text)


def _load_user(user_path: Path | None) -> dict:
    """Read user prompts.toml — empty dict when missing."""
    path = user_path or _USER_PROMPTS_PATH
    if path is None or not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        # Bad user TOML shouldn't break the pipeline — fall back silently.
        return {}


def _resolve_global_prefix(builtin: dict, user: dict) -> str:
    """User's [global] prefix wins over built-in. Empty string means
    'no global prefix configured' (we just won't prepend anything)."""
    user_prefix = (user.get("global") or {}).get("prefix")
    if isinstance(user_prefix, str) and user_prefix.strip():
        return user_prefix
    builtin_prefix = (builtin.get("global") or {}).get("prefix", "")
    return builtin_prefix if isinstance(builtin_prefix, str) else ""


def _resolve_type_entry(
    builtin: dict, user: dict, video_type: str,
) -> tuple[dict, str]:
    """Find the [prompts.<video_type>] section. User TOML wins.
    Falls back to generic when the requested type is unknown."""
    user_entry = (user.get("prompts") or {}).get(video_type)
    if isinstance(user_entry, dict) and "prompt" in user_entry:
        return user_entry, "user_override"

    builtin_entry = (builtin.get("prompts") or {}).get(video_type)
    if isinstance(builtin_entry, dict) and "prompt" in builtin_entry:
        return builtin_entry, "builtin"

    # Unknown type → fall back to generic. Should never happen via CLI
    # because we validate against list_known_types(), but defensive.
    generic = (builtin.get("prompts") or {}).get(DEFAULT_VIDEO_TYPE, {})
    return generic, "builtin"
