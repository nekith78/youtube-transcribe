# Handoff guide — picking up work on a new machine

This document captures the current project state and how to resume.
Read it whenever you switch machines or come back after a break.

---

## Current state (2026-05-14)

- **Version:** `v0.8.0` — shipped: `transcribe`, `batch`, `analyze`,
  `research`, `subscribes` (YouTube + Instagram + TikTok), `history`,
  visual mode, ASR correction, speaker diarization.
- **Tests:** 898 passing, 3 skipped, 0 failures.
- **What's documented:**
  - [`README.md`](README.md) — user-facing overview, install,
    quick start, every command with examples.
  - [`CHANGELOG.md`](CHANGELOG.md) — per-version history.
  - [`docs/agent-reference.md`](docs/agent-reference.md) — full CLI
    surface, file map, exit codes, invariants for AI agents driving
    the tool.
  - [`CLAUDE.md`](CLAUDE.md) — project-level instructions for Claude
    Code sessions opening this repo.
- **What's in flight:** see `## Roadmap` in README (next: PyPI
  publication, chunking videos > 2h for cloud backends).

Run `git log --oneline -10` after cloning to see recent work.

---

## First-time setup on macOS Apple Silicon

### Pre-requisites — install once

```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh   # reopen terminal afterwards
uv --version   # should print 0.4+
```

### Critical warnings

1. **Python MUST be arm64 native.**
   ```bash
   python3 -c "import platform; print(platform.machine())"
   ```
   Must print `arm64`. If it prints `x86_64`, you're under Rosetta —
   `mlx-whisper` will not work. Fix: `brew install python@3.12` and
   remove any Anaconda Python from your PATH.

2. **macOS 13.5+ required** for `mlx-whisper` wheels.

3. **First Whisper-large run downloads ~600 MB** into
   `~/.cache/huggingface/`. Make sure you have disk space.

### Install the project

```bash
git clone https://github.com/nekith78/youtube-transcribe.git
cd youtube-transcribe
uv sync                          # base install
uv sync --extra dev              # + pytest, coverage
uv sync --extra instagram        # + instaloader (IG profile fallback)
uv sync --extra diarization      # + pyannote.audio (speaker labels)
uv sync --extra webui            # + gradio (experimental UI)
uv sync --extra ocr              # + pytesseract / easyocr
```

You can pass multiple `--extra` flags together.

### Configure backends

```bash
uv run youtube-transcribe config wizard   # first-time setup, asks for keys
uv run youtube-transcribe config show     # see current state + masked keys
```

Or set keys directly:

```bash
uv run youtube-transcribe config set-key gemini   # prompts for key
uv run youtube-transcribe config set-key groq
# ... openai / deepgram / assemblyai / anthropic
```

Keys are stored in `~/.youtube-transcribe/.env` with mode 0600.

---

## First-time setup on Windows / Linux

Same as Mac except:

- `ffmpeg` install: `choco install ffmpeg` (Windows), `apt install ffmpeg` (Ubuntu).
- `mlx-whisper` is **not installed** on these platforms — PEP 508 markers
  route to `faster-whisper` instead (CPU or CUDA, depending on hardware).
- Windows: `irm https://astral.sh/uv/install.ps1 | iex` for uv.

---

## Cookies setup (Instagram / TikTok)

Both platforms need cookies for profile listing. Export from your
browser using the "Get cookies.txt LOCALLY" Chrome/Firefox extension,
then:

```bash
uv run youtube-transcribe subscribes cookies set instagram /path/to/ig-cookies.txt
uv run youtube-transcribe subscribes cookies set tiktok    /path/to/tt-cookies.txt
uv run youtube-transcribe subscribes cookies show
```

The file is copied to `~/.youtube-transcribe/<platform>-cookies.txt`
with mode 0600.

**Strict file-only.** We do NOT support `--cookies-from-browser` —
that flag reads the entire browser cookie store into process memory.
Export the specific cookies you want; never grant blanket access.

---

## Common dev tasks

```bash
uv run pytest                              # full test suite (~25s)
uv run pytest tests/test_factory.py -v     # one file
uv run pytest -k smart -v                  # by keyword
bash scripts/qa.sh phase8a                 # manual phase regression
RUN_E2E_SMOKE=1 uv run pytest -v           # include real-network e2e (rare)
```

```bash
uv run youtube-transcribe --help           # see all commands
uv run youtube-transcribe transcribe       # interactive prompt
uv run youtube-transcribe batch            # interactive multi-URL prompt
uv run youtube-transcribe research         # interactive query prompt
```

---

## Architecture invariants — don't break these

1. **Skill name `youtube-transcribe` (kebab); Python package
   `youtube_transcribe` (snake).** Both. Use by context.
2. **Cookies file-only**, never `cookies-from-browser`.
3. **`uv.lock` and `.python-version` are NOT committed** — each
   platform resolves its own.
4. **`mlx-whisper` gated by `sys_platform == 'darwin' and
   platform_machine == 'arm64'`.** `faster-whisper` is the symmetric
   marker. Never `import` them unconditionally.
5. **All user-facing CLI strings in English** (v0.8 migration).
   Comments/docstrings also English.
6. **`smart` backend downloads audio before falling back** (v0.8 fix).
   Non-subtitles backends can't accept URLs.

---

## Working with the spec/plan when something is unclear

Original design: `docs/specs/2026-05-08-youtube-transcribe-design.md`
(v0.1 baseline). v0.2 through v0.8 added features per their own
spec/plan docs in the same directory.

For runtime behavior, prefer reading the code over the spec — v0.8
diverges from v0.1's design in several places (cookies-file-only,
interactive prompts, smart backend download).

---

## Pre-push contract

Before `git push origin main`:
- `uv run pytest` — must be green.
- For features that touch security/IO: invoke the global skill
  `git-cross-os` (it runs `code-reviewer` + `security-review`).
