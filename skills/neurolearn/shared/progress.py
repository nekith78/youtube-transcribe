"""Spinner-style progress indicator for single-video pipelines.

The single-video `transcribe` flow has multi-second silent stages
(yt-dlp download, backend inference, optional vision). A bare command
without any feedback feels frozen. This wrapper shows a Rich spinner
with a stage label that the caller updates at each phase boundary.

Behavior:
  • verbose=True → no spinner; each `.update(msg)` becomes a `[dim]· msg[/dim]`
    print so the verbose-mode raw stdout/stderr stays readable.
  • verbose=False, TTY → Rich `console.status()` spinner.
  • non-TTY → Rich's status() degrades to plain text writes automatically.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Protocol

from rich.console import Console


class StageHandle(Protocol):
    """The narrow surface callers depend on. Lets us swap rich.Status
    for a plain-print stub in verbose mode without touching call sites."""

    def update(self, msg: str) -> None: ...


class _PrintStage:
    """Verbose-mode fallback: each stage transition prints a dim line."""

    def __init__(self, console: Console) -> None:
        self._console = console

    def update(self, msg: str) -> None:
        self._console.print(f"[dim]· {msg}[/dim]")


@contextmanager
def stage_progress(
    console: Console,
    *,
    verbose: bool,
    initial: str = "Working...",
) -> Iterator[StageHandle]:
    """Yield an object with `.update(msg)` that drives the spinner.

    Use as a context manager around a sequence of timed operations:

        with stage_progress(console, verbose=opts.verbose,
                            initial="Downloading audio...") as stage:
            audio = download_audio(...)
            stage.update("Transcribing via gemini...")
            result = backend.transcribe(...)
    """
    if verbose:
        stage = _PrintStage(console)
        stage.update(initial)
        yield stage
        return

    with console.status(initial, spinner="dots") as status:
        yield status
