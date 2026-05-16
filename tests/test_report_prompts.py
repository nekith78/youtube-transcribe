"""Tests for report.prompts loader: built-in + user override + global prefix.

Mirrors the vision/prompts loader contract from v0.10.1 — same shape,
different content. Report prompts run AT REPORT TIME (post-pipeline,
on the produced batch_dir) and consume already-generated visual
segments + transcript to produce a structured outline.
"""
from pathlib import Path

import pytest

# Note: this import will fail until Phase 2 implementation lands —
# that's the point of TDD. Run with `-x` to stop at first failure
# while writing the loader.
from skills.neurolearn.report.prompts import (
    BUILTIN_REPORT_TYPES, load_report_prompt, list_known_report_types,
    format_report_prompt,
)


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------


def test_all_builtin_types_load():
    """Every type in BUILTIN_REPORT_TYPES has a non-empty prompt."""
    for t in BUILTIN_REPORT_TYPES:
        spec = load_report_prompt(t)
        assert spec.template, f"{t} has empty template"
        assert spec.source == "builtin"


def test_global_prefix_prepended_by_default():
    """Built-in [global] rules are prepended to every type."""
    spec = load_report_prompt("tutorial")
    assert spec.used_global_prefix is True
    # Distinctive line from the universal report rules.
    assert "structured outline" in spec.template.lower()


def test_use_global_prefix_false_drops_prefix():
    spec = load_report_prompt("tutorial", use_global_prefix=False)
    assert spec.used_global_prefix is False
    assert "structured outline" not in spec.template.lower()


def test_unknown_type_falls_back_to_generic():
    """Requested type that isn't in the TOML returns generic template."""
    spec = load_report_prompt("nonsense-2099")
    # generic prompt has its own distinctive section about "section outline"
    assert "generic" in spec.template.lower() or "section" in spec.template.lower()
    assert spec.source == "builtin"


# ---------------------------------------------------------------------------
# User override
# ---------------------------------------------------------------------------


def test_user_override_replaces_builtin(tmp_path: Path):
    """User TOML supplies a custom report-prompt for `tutorial`."""
    user_toml = tmp_path / "report_prompts.toml"
    user_toml.write_text("""
[prompts.tutorial]
prompt = "MY CUSTOM tutorial report — only commands for CI/CD."
append_global = true
""", encoding="utf-8")
    spec = load_report_prompt("tutorial", user_path=user_toml)
    assert "MY CUSTOM tutorial report" in spec.template
    assert "structured outline" in spec.template.lower()   # global still appended
    assert spec.source == "user_override"


def test_user_override_can_disable_global_prefix(tmp_path: Path):
    user_toml = tmp_path / "report_prompts.toml"
    user_toml.write_text("""
[prompts.tutorial]
prompt = "STANDALONE custom prompt — only this and nothing else."
append_global = false
""", encoding="utf-8")
    spec = load_report_prompt("tutorial", user_path=user_toml)
    assert spec.template == "STANDALONE custom prompt — only this and nothing else."
    assert spec.used_global_prefix is False


def test_user_can_define_new_report_type(tmp_path: Path):
    """User TOML can add a brand-new type unknown to built-ins."""
    user_toml = tmp_path / "report_prompts.toml"
    user_toml.write_text("""
[prompts.cooking-recipe]
prompt = "Extract recipes — ingredients list, steps, timings."
append_global = false
""", encoding="utf-8")
    spec = load_report_prompt("cooking-recipe", user_path=user_toml)
    assert "Extract recipes" in spec.template
    types = list_known_report_types(user_path=user_toml)
    assert "cooking-recipe" in types


def test_user_global_prefix_overrides_builtin(tmp_path: Path):
    user_toml = tmp_path / "report_prompts.toml"
    user_toml.write_text("""
[global]
prefix = "MY GLOBAL — reply in Russian, be brief."
""", encoding="utf-8")
    spec = load_report_prompt("generic", user_path=user_toml)
    assert "MY GLOBAL" in spec.template


def test_broken_user_toml_falls_back_silently(tmp_path: Path):
    """Malformed user TOML doesn't crash the pipeline."""
    user_toml = tmp_path / "report_prompts.toml"
    user_toml.write_text("this is not valid [[[ toml", encoding="utf-8")
    spec = load_report_prompt("tutorial", user_path=user_toml)
    assert spec.source == "builtin"


# ---------------------------------------------------------------------------
# Custom inline template (CLI --prompt-file)
# ---------------------------------------------------------------------------


def test_custom_inline_template_used_with_global(tmp_path: Path):
    """CLI --prompt-file path content → wins. Global prefix prepended
    unless explicitly disabled."""
    spec = load_report_prompt(
        "tutorial",
        custom_template="VERY SPECIFIC user prompt for this single run",
        use_global_prefix=True,
    )
    assert "VERY SPECIFIC user prompt" in spec.template
    assert "structured outline" in spec.template.lower()
    assert spec.source == "cli_file"


def test_custom_inline_template_can_skip_global():
    spec = load_report_prompt(
        "tutorial",
        custom_template="ONLY this and nothing else",
        use_global_prefix=False,
    )
    assert spec.template == "ONLY this and nothing else"


# ---------------------------------------------------------------------------
# format_report_prompt — substitution
# ---------------------------------------------------------------------------


def test_format_report_prompt_substitutes_placeholders():
    template = (
        "lang={target_language}; user_filter={user_filter}; "
        "transcript={transcript_excerpt}"
    )
    result = format_report_prompt(
        template,
        target_language="en",
        user_filter="focus on commands",
        transcript_excerpt="hello world",
    )
    assert result == (
        "lang=en; user_filter=focus on commands; transcript=hello world"
    )
