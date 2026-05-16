"""Test-wide conftest.

Currently does one thing: prime macOS dyld search path so test code
that imports `weasyprint` directly (rather than via the report package)
can still find Homebrew-installed pango/cairo/gobject. The report
package does the same priming on import, but standalone test
imports go through pytest.importorskip and don't touch the package.
"""
from __future__ import annotations

import os
import platform


def _prime_macos_brew_libs() -> None:
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


_prime_macos_brew_libs()
