"""Tests for --vision-prompt custom template loading.

Renamed loader: `_load_vision_prompt` → `_resolve_vision_prompt(cfg, video_type)`
in v0.10.1. The new loader supports type-based prompts plus optional
global-prefix prepending, but the contract for `--vision-prompt`
custom-file paths is preserved.
"""
from skills.neurolearn.pipeline_v02 import _resolve_vision_prompt


def _is_generic_template(text: str) -> bool:
    """The built-in generic prompt has distinctive phrasing. Used as
    a stable marker for 'fell back to the default'.

    The example string "Browser DevTools network tab" comes from the
    generic prompt's GOOD/BAD example block. It's a one-line phrase
    that survives TOML triple-quote line wrapping intact.
    """
    return "Browser DevTools network tab" in text


def test_no_path_returns_default_for_video_type():
    assert _is_generic_template(_resolve_vision_prompt({}, "generic"))
    assert _is_generic_template(_resolve_vision_prompt({"vision_prompt_path": ""}, "generic"))
    assert _is_generic_template(_resolve_vision_prompt({"vision_prompt_path": "   "}, "generic"))


def test_valid_path_returns_file_content_with_global_prefix(tmp_path):
    p = tmp_path / "prompt.txt"
    p.write_text(
        "Describe in {language}: {transcript_snippet} {start_sec} {end_sec}",
        encoding="utf-8",
    )
    cfg = {"vision_prompt_path": str(p)}
    result = _resolve_vision_prompt(cfg, "generic")
    assert "Describe in {language}" in result
    # Global prefix prepended by default.
    assert "Output language" in result


def test_no_global_prefix_uses_only_custom_template(tmp_path):
    p = tmp_path / "prompt.txt"
    custom = "ONLY THIS in {language}: {transcript_snippet}"
    p.write_text(custom, encoding="utf-8")
    cfg = {"vision_prompt_path": str(p), "no_global_prefix": True}
    result = _resolve_vision_prompt(cfg, "generic")
    assert result == custom


def test_missing_file_falls_back_to_default(tmp_path):
    cfg = {"vision_prompt_path": str(tmp_path / "nonexistent.txt")}
    result = _resolve_vision_prompt(cfg, "generic")
    assert _is_generic_template(result)


def test_tilde_path_expanded(tmp_path, monkeypatch):
    """`~/...` paths should expand on all OSes.

    On Windows `Path.expanduser()` reads USERPROFILE / HOMEDRIVE+HOMEPATH
    first, not HOME — so we set both for cross-OS portability.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    p = tmp_path / "p.txt"
    p.write_text("custom prompt", encoding="utf-8")
    cfg = {"vision_prompt_path": "~/p.txt", "no_global_prefix": True}
    assert _resolve_vision_prompt(cfg, "generic") == "custom prompt"


def test_tutorial_type_uses_tutorial_template():
    """When video_type='tutorial' and no custom path, return the
    built-in tutorial prompt (distinctive phrasing about UI actions)."""
    text = _resolve_vision_prompt({}, "tutorial")
    assert "UI tutorial" in text or "UI action" in text


def test_talking_head_template_loads():
    """Talking_head has its own prompt with distinct language."""
    text = _resolve_vision_prompt({}, "talking_head")
    assert "talking-head" in text or "talking head" in text
