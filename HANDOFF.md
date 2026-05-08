# Handoff guide — picking up work on a new machine

This document captures the current project state and how to continue. Read it whenever you switch machines or come back after a break.

---

## Current state

- **What's done:**
  - Design document: [`docs/specs/2026-05-08-youtube-transcribe-design.md`](docs/specs/2026-05-08-youtube-transcribe-design.md) — full spec covering 8 backends, 3 install paths, wizard, secrets, error handling, hardware tiers.
  - Implementation plan: [`docs/plans/2026-05-08-youtube-transcribe.md`](docs/plans/2026-05-08-youtube-transcribe.md) — 30 tasks across 7 phases, TDD-style, no placeholders.
- **What's pending:** All 30 tasks. **No code has been written yet.** First clone will give you only the docs above plus this handoff.
- **Execution mode chosen:** subagent-driven (one fresh subagent per task, with review between tasks).

Run `git log --oneline` after cloning to see exactly where things stand.

---

## Continuing on macOS Apple Silicon (M1/M2/M3/M4)

### Pre-requisites — install once

```bash
# Xcode Command Line Tools (for git, compilers needed by faster-whisper deps)
xcode-select --install

# Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# ffmpeg (required by yt-dlp for audio extraction)
brew install ffmpeg
ffmpeg -version  # confirm it works

# uv — installs Python and project deps (much faster than pip)
curl -LsSf https://astral.sh/uv/install.sh | sh
# Reopen terminal afterwards, then:
uv --version  # should print 0.4+
```

### Critical warnings — read before starting

1. **Python MUST be arm64 native, not x86_64 under Rosetta.**
   ```bash
   python3 -c "import platform; print(platform.machine())"
   ```
   - Must print `arm64`. If it prints `x86_64` you're running Python under Rosetta — `mlx-whisper` will not work on Apple Silicon.
   - Fix: `brew install python@3.12` and remove any system/Anaconda Python from your PATH. `uv` will pick up the right one automatically when you run `uv sync`.

2. **macOS 13.5+ is required for `mlx-whisper`.**
   - Older versions break the install with cryptic errors.
   - Check your version: System Settings → General → About → macOS version.

3. **First model run downloads ~600 MB** (`mlx-community/whisper-large-v3-turbo`) into `~/.cache/huggingface/`. Make sure you have disk space.

4. **Set git identity locally** (so commits are attributed to you):
   ```bash
   git config user.name "Your Name"
   git config user.email "your@email"
   ```

---

### Cloning

```bash
git clone https://github.com/<your-github-username>/youtube-transcribe.git
cd youtube-transcribe
```

⚠️ **Don't run `uv sync` immediately** — `pyproject.toml` doesn't exist yet. It gets created in **Task 1** of the plan.

---

### Continuing implementation in Claude Code

Open Claude Code in the cloned repo directory. Paste this prompt verbatim:

> Я продолжаю работу с этим проектом на новой машине (Mac M-series). Изучи `docs/specs/2026-05-08-youtube-transcribe-design.md` и `docs/plans/2026-05-08-youtube-transcribe.md` — это спека и план реализации. Реализация **ещё не начиналась** (ни один Task из плана не выполнен). Запусти skill `superpowers:subagent-driven-development` и начинай выполнять план с Task 1, диспатчая отдельный subagent на каждую задачу с ревью между задачами.

Claude will:
1. Read both docs.
2. Invoke the `superpowers:subagent-driven-development` skill.
3. Dispatch a subagent for Task 1 (`pyproject.toml`).
4. Review the result, then dispatch Task 2, and so on.

You stay in the driver's seat — Claude pauses for your review after each task.

---

## What if something breaks

| Symptom | Cause + fix |
|---|---|
| `uv` install fails | Install Python directly: `brew install python@3.12`, then run the `uv` install script again. |
| `uv sync` errors on `mlx-whisper` | Confirm warning #1 (arm64 Python) and warning #2 (macOS ≥13.5). |
| Tests fail in Phase 2 (foundations) | Likely deps mismatch. Try `uv sync --reinstall` and retry. |
| `yt-dlp` returns 403 / "sign in to confirm not a bot" | YouTube anti-bot rotation — covered in plan Task 7. Fix: `--cookies-from-browser chrome` (or firefox/safari). |
| `mlx-whisper.transcribe` crashes mid-run | Capture stderr; this is platform-specific and likely needs a Mac-only fix. Add a new task at the end of the plan with the fix. |
| Mac-specific bug not in the plan | Capture stdout/stderr, document in commit message, optionally add a new Task at the end of the plan. |

---

## Recovery points (for after Phase 6 / Phase 7)

These will be created during plan execution — listed here for reference:

- **Tag `v0.1.0-pre-mac`** (Task 27) — last known-good Windows state before Mac validation. Reset to this if Mac validation breaks something.
- **Tag `v0.1.0`** (Task 30) — first public release after Mac validation passes.

Reset commands (only if needed):
```bash
git reset --hard v0.1.0-pre-mac
git push --force-with-lease origin main   # only if you really need to rewind
```

---

## Working with the spec/plan when something is unclear

- **Spec questions** → re-read the relevant numbered section of `docs/specs/2026-05-08-youtube-transcribe-design.md`. Sections 1–19, indexed.
- **Task questions** → see the corresponding Task in `docs/plans/2026-05-08-youtube-transcribe.md`. Each task is self-contained with file paths, code, and tests.
- **Architectural questions** → spec Section 4 (file structure) and Section 5 (8 backends).
- **Backend-switching behavior** → spec Section 7 + plan Task 22 (SKILL.md).

Trust the spec; the plan was written from it. If they disagree, the spec is the source of truth — open an issue to fix the plan.
