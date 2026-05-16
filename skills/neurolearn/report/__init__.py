"""Report generation — transcript + visuals → structured PDF.

Layered architecture mirroring the rest of the project:

  • `prompts.py`  — built-in report-mode prompt templates + user override
  • `outliner.py` — LLM-driven structured outline (sectioning, hierarchical
                    summarization for long videos, final assembly)
  • `renderer.py` — Jinja2 HTML templates → WeasyPrint PDF
  • `cli.py`      — `neurolearn report <batch_dir>` sub-command

Public entry point: `generate_report(batch_dir, ...)` orchestrates the
three layers and returns a Path to the rendered PDF.

WeasyPrint + Jinja2 + markdown are opt-in via `uv sync --extra report`.
We probe for them at runtime and surface a friendly install hint when
they're missing rather than failing on import at module load — this
keeps the base install lean for users who never touch reporting.
"""
from __future__ import annotations

import os
import platform
from importlib import import_module


def _prime_native_libs_for_weasyprint() -> None:
    """macOS+Apple Silicon: WeasyPrint can't find Homebrew-installed
    pango / cairo / gobject because brew puts them under /opt/homebrew/lib
    which isn't on the system dyld search path. We prepend it to
    DYLD_FALLBACK_LIBRARY_PATH so `import weasyprint` succeeds without
    the user having to wrap commands in env vars. No-op on other OSes
    and when /opt/homebrew/lib doesn't exist."""
    if platform.system() != "Darwin":
        return
    for brew_lib in ("/opt/homebrew/lib", "/usr/local/lib"):
        if not os.path.isdir(brew_lib):
            continue
        existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        if brew_lib not in existing.split(":"):
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                brew_lib + (":" + existing if existing else "")
            )


# Prime before any submodule imports weasyprint.
_prime_native_libs_for_weasyprint()


# ---------------------------------------------------------------------------
# On-demand dependency detection
# ---------------------------------------------------------------------------


_REPORT_DEPS = ("weasyprint", "jinja2", "markdown")


def check_report_deps() -> list[str]:
    """Return the list of missing optional dependencies for the report
    pipeline, or [] when everything is available."""
    missing: list[str] = []
    for name in _REPORT_DEPS:
        try:
            import_module(name)
        except ImportError:
            missing.append(name)
    return missing


def require_report_deps_or_exit() -> None:
    """Raise SystemExit(4) with a friendly install hint when any of the
    optional report dependencies are missing. Designed to be called at
    the top of the CLI command so the user sees the hint before any
    work starts."""
    missing = check_report_deps()
    if not missing:
        return
    import sys
    msg = (
        "[neurolearn] PDF report generation requires extra packages "
        f"({', '.join(missing)}).\n\n"
        "Install them once with:\n"
        "  uv sync --extra report\n\n"
        "Or with pip:\n"
        "  pip install 'neurolearn[report]'\n\n"
        "On macOS you may also need:\n"
        "  brew install pango\n"
        "On Debian/Ubuntu:\n"
        "  sudo apt install libpango-1.0-0 libpangoft2-1.0-0\n"
    )
    print(msg, file=sys.stderr)
    sys.exit(4)
