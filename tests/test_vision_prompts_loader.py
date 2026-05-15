"""Tests for vision.prompts loader: built-in + user override + global prefix.

Covers the loader contract from prompts_default.toml + user TOML
merge logic, used by the vision pipeline to pick a system prompt per
video type.
"""
from pathlib import Path

import pytest

from skills.neurolearn.vision.prompts import (
    BUILTIN_VIDEO_TYPES, load_prompt, list_known_types, format_prompt,
)


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------


def test_all_builtin_types_load():
    """Every type in BUILTIN_VIDEO_TYPES has a non-empty prompt."""
    for t in BUILTIN_VIDEO_TYPES:
        spec = load_prompt(t)
        assert spec.template, f"{t} has empty template"
        assert spec.source == "builtin"


def test_global_prefix_prepended_by_default():
    spec = load_prompt("tutorial")
    assert spec.used_global_prefix is True
    # Global prefix has a distinctive opening line.
    assert "Output language" in spec.template


def test_use_global_prefix_false_drops_prefix():
    spec = load_prompt("tutorial", use_global_prefix=False)
    assert spec.used_global_prefix is False
    assert "Output language" not in spec.template


def test_unknown_type_falls_back_to_generic():
    """A type that isn't in the TOML returns the generic template."""
    spec = load_prompt("nonsense-type-2030")
    # Falls back to generic — same distinctive opening as generic prompt.
    assert "Browser DevTools network tab" in spec.template
    assert spec.source == "builtin"


# ---------------------------------------------------------------------------
# User override
# ---------------------------------------------------------------------------


def test_user_override_replaces_builtin(tmp_path: Path):
    """User TOML supplies a custom prompt for `tutorial` → it's used
    instead of the shipped one."""
    user_toml = tmp_path / "prompts.toml"
    user_toml.write_text("""
[prompts.tutorial]
prompt = "MY OWN tutorial focus on Photoshop only"
append_global = true
""", encoding="utf-8")
    spec = load_prompt("tutorial", user_path=user_toml)
    assert "MY OWN tutorial focus on Photoshop only" in spec.template
    assert "Output language" in spec.template  # global still appended
    assert spec.source == "user_override"


def test_user_override_can_disable_global_prefix(tmp_path: Path):
    user_toml = tmp_path / "prompts.toml"
    user_toml.write_text("""
[prompts.tutorial]
prompt = "STANDALONE custom prompt"
append_global = false
""", encoding="utf-8")
    spec = load_prompt("tutorial", user_path=user_toml)
    assert spec.template == "STANDALONE custom prompt"
    assert spec.used_global_prefix is False


def test_user_can_define_new_video_type(tmp_path: Path):
    """User TOML can introduce a custom video type unknown to the built-in."""
    user_toml = tmp_path / "prompts.toml"
    user_toml.write_text("""
[prompts.cooking-show]
prompt = "Focus on ingredients, utensils, and cooking actions."
append_global = false
""", encoding="utf-8")
    spec = load_prompt("cooking-show", user_path=user_toml)
    assert "ingredients" in spec.template
    types = list_known_types(user_path=user_toml)
    assert "cooking-show" in types


def test_user_global_prefix_overrides_builtin(tmp_path: Path):
    user_toml = tmp_path / "prompts.toml"
    user_toml.write_text("""
[global]
prefix = "Reply in Russian. Be brief."
""", encoding="utf-8")
    spec = load_prompt("generic", user_path=user_toml)
    assert "Reply in Russian." in spec.template
    # Built-in "Output language" string from the default global prefix
    # should NOT be present — user replaced it.
    assert "Output language" not in spec.template


def test_broken_user_toml_falls_back_silently(tmp_path: Path):
    """Bad user TOML doesn't crash the pipeline."""
    user_toml = tmp_path / "prompts.toml"
    user_toml.write_text("this is not valid toml [[[", encoding="utf-8")
    spec = load_prompt("tutorial", user_path=user_toml)
    # Falls back to built-in.
    assert spec.source == "builtin"
    assert spec.template, "must still load some template"


# ---------------------------------------------------------------------------
# Custom inline template (CLI --prompt-file)
# ---------------------------------------------------------------------------


def test_custom_inline_template_used_with_global(tmp_path: Path):
    """CLI --prompt-file path content → wins. Global prefix prepended."""
    spec = load_prompt(
        "generic",
        custom_template="VERY SPECIFIC custom for one run",
        use_global_prefix=True,
    )
    assert "VERY SPECIFIC custom for one run" in spec.template
    assert "Output language" in spec.template
    assert spec.source == "cli_file"


def test_custom_inline_template_can_skip_global():
    spec = load_prompt(
        "generic",
        custom_template="ONLY this and nothing else",
        use_global_prefix=False,
    )
    assert spec.template == "ONLY this and nothing else"
    assert spec.used_global_prefix is False


# ---------------------------------------------------------------------------
# format_prompt — substitution
# ---------------------------------------------------------------------------


def test_format_prompt_substitutes_placeholders():
    template = "lang={language}; snippet={transcript_snippet}; t={start_sec:.1f}-{end_sec:.1f}"
    result = format_prompt(
        template,
        language="ru", transcript_snippet="hello world",
        start_sec=10.5, end_sec=15.0,
    )
    assert result == "lang=ru; snippet=hello world; t=10.5-15.0"
