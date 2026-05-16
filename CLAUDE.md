# CLAUDE.md

Instructions for Claude Code (and any other AI agent) working in this
repository.

## Repository state

`neurolearn` is a mature CLI tool: v0.10.2, ~1030 unit tests
passing, in active use. Shipped commands: `transcribe`, `batch`,
`analyze`, `research`, `subscribes` (YouTube / Instagram / TikTok),
`report` (PDF generation, v0.10.2), `history`, `config`, `webui`
(hidden).

The source of truth for behavior is the code. Design documents in
`docs/specs/` and plan documents in `docs/plans/` capture the original
intent at each version boundary but diverge from runtime reality in
places (v0.8 in particular added security migrations, interactive
prompts, and smart-backend fixes that postdate the v0.7 spec).

Start any work by reading recent commits:

```bash
git log --oneline -15
```

Then read the relevant code path, not the spec.

## How to continue work

Standard execution mode is **subagent-driven**: dispatch one fresh
subagent per task, review between tasks. Before starting:

1. `git status` and `git log --oneline -5` — understand where things stand.
2. `uv run pytest -q` — confirm the baseline is green.
3. For first-time setup on a fresh machine, see [`HANDOFF.md`](HANDOFF.md).

## Common commands

```bash
uv sync                            # install base deps
uv sync --extra dev                # + pytest, coverage
uv sync --extra instagram          # + instaloader fallback
uv sync --extra diarization        # + pyannote
uv sync --extra webui              # + gradio
uv sync --extra ocr                # + pytesseract, easyocr
uv sync --extra report             # + weasyprint, jinja2, markdown (PDF reports)

uv run pytest                      # full suite (~25s, ~1030 tests)
uv run pytest tests/test_X.py -v   # one file
uv run pytest -k keyword -v        # filter by keyword
RUN_E2E_SMOKE=1 uv run pytest -v   # enable network-touching e2e

uv run neurolearn --help   # see all commands
```

## Architecture invariants

These are load-bearing — breaking them silently breaks the tool.

**Naming.** The Claude Code plugin / CLI binary is `neurolearn`
(kebab-case). The Python package is `skills/neurolearn/`
(snake_case). Both forms appear in the codebase and docs — use them
by context. **`yt-tr` is not a valid alias** and never was; if you
see it in any doc, fix it to `neurolearn`.

**Cookies are strict file-only (v0.8 security migration).** All paths
that previously accepted `--cookies-from-browser` now require an
explicit Netscape `cookies.txt` file. Rationale: browser-cookie
access reads the entire cookie store into process memory — even on
macOS where Keychain prompts, an "Always Allow" grant silently leaks
all cookies. This is non-negotiable.

- `transcribe` / `batch` — flag is `--cookies-file <path>`
- `subscribes` (IG / TikTok) — register once via
  `subscribes cookies set <platform> <path>`; stored at
  `~/.neurolearn/<platform>-cookies.txt` with mode 0600.

**Backend abstraction.** `backends/base.py` defines `Transcriber`
(Protocol) and `TranscriptionResult` (dataclass). All 8 backends
(`subtitles`, `whisper-local`, `gemini`, `groq`, `openai`, `deepgram`,
`assemblyai`, `custom`) are interchangeable implementations. Tests run
against the interface; SDKs are mocked. To add a backend:
implement `Transcriber` + register in `backends/factory.py::build_backend`.

**`smart` is composition, not a backend.** When `default_backend ==
"smart"`, the flow is: try `subtitles` if the URL is YouTube and
`fast_path_enabled`, otherwise (or on subtitles failure) download
audio and fall back to `cfg.fallback_backend` (default `whisper-local`).
The smart composer is in `backends/factory.run_smart`; it's
responsible for downloading audio when the input is a URL because
non-subtitles backends call `Path(audio).exists()` and reject URLs.
(v0.8 fix `4e1afcf`.)

**Whisper-local: two physical implementations.** On macOS arm64 we use
`mlx-whisper`; everywhere else `faster-whisper`. The choice is
automatic via `utils/platform_detect.py`. PEP 508 markers gate the
installs:

- `mlx-whisper`: `sys_platform == 'darwin' and platform_machine == 'arm64'`
- `faster-whisper`: `sys_platform != 'darwin' or platform_machine != 'arm64'`

Never `import` either unconditionally — both modules will be absent
on the wrong platform.

**Config and secrets.**
- `~/.neurolearn/config.toml` — settings (TOML, `tomli` to
  read, `tomli-w` to write, `tomlkit` for comment-preserving edits).
- `~/.neurolearn/.env` — API keys, mode 0600 on Unix.
- Load order: process env > `.env` > error with instructions.
- API keys are masked when printed (`sk-***...XYZ`). Never log full keys.

## Cross-OS specifics

The skill is cross-platform: macOS arm64 (mlx-whisper), Windows / Linux
/ Intel-Mac (faster-whisper). Always check that new code works on both
sides. The `.gitattributes` file pins EOL: `*.py *.md *.toml` → LF,
`*.ps1 *.bat *.cmd` → CRLF. Don't override.

`uv.lock` and `.python-version` are deliberately NOT committed — each
platform resolves its own versions.

When suggesting commands to the user, prefer cross-platform forms.
If a feature is OS-specific, say so explicitly.

## Tests

Three levels:

1. **Unit (default)** — fast, mock SDKs and `subprocess`. Should be
   green on any OS without API keys or network. Run by `uv run pytest`.
2. **E2E smoke (opt-in)** — `RUN_E2E_SMOKE=1` flag enables tests that
   hit real YouTube. Don't enable in CI without secrets.
3. **Manual phase regression** — `bash scripts/qa.sh phase8a` etc.
   Wraps end-to-end flows (cookies workflow, subscribes update, etc.)
   into ~12-step assertion lists with user-state restore.

TDD style for new code: failing test → minimal impl → pass → commit.

## Documentation languages

Project docs, code, CLI strings, and agent guides are **English only**.
User chat-language preferences (e.g. Russian) live in the user's own
global rules — outside this repo.

If you find any user-facing string in Russian inside this repo,
migrate it to English. (v0.8 commit `5a1a71b` did the bulk of this;
new strings should land in English from the start.)

## Pre-push contract

Before `git push` to `main`:

1. `uv run pytest` green.
2. For security/IO-touching changes: invoke the global skill
   `git-cross-os`, which runs `code-reviewer` + `security-review`
   sub-agents before push.

## Report mode (v0.10.2)

`neurolearn report <batch_dir>` produces a structured PDF from any
transcribed batch. Architecture is parallel to vision prompts from
v0.10.1:

- `skills/neurolearn/report/prompts.py` — TOML loader with global
  prefix + per-type templates + user override
  (`~/.neurolearn/report_prompts.toml`).
- `skills/neurolearn/report/outliner.py` — single-call vs
  hierarchical routing; resilient JSON parsing.
- `skills/neurolearn/report/renderer.py` — Jinja2 HTML + WeasyPrint
  PDF + Pillow downscale (≤1000px, base64 data URIs).
- `skills/neurolearn/report/orchestrator.py` — manifest + SRT →
  outline → PDF glue.

Optional deps via `uv sync --extra report` (weasyprint + jinja2 +
markdown). On macOS the package primes `DYLD_FALLBACK_LIBRARY_PATH`
so `brew install pango cairo` libs are picked up automatically.

## Out of scope for v0.10.2 (currently)

Chunking videos > 2h, PyPI publication, Web UI revival (Gradio tabs
re-do). These are tracked in README `## Roadmap`; add new requests
there before coding.
