# Agent reference — youtube-transcribe

Reference manual for LLM agents (Claude Code, GPT-based, local) that drive this
skill. Pairs with `skills/youtube_transcribe/SKILL.md` (which is the trigger /
quick-rules layer) and the project knowledge graph in
[`graphify-out/`](../graphify-out/) (for exploration).

The goal of this file is to make an agent productive **without rereading the
codebase from scratch**: how the pieces connect, where to look for what, what
the CLI commands actually accept, and the failure modes that have already been
fixed (so you don't re-investigate them).

---

## 1. Mental model

The skill provides three roles:

1. **Transcription engine.** One URL or one local file → text + SRT. Eight
   backends, one common `Transcriber` protocol, runtime selection.
2. **Batch / channel runner.** Many URLs at once (or a YouTube channel /
   playlist / file of URLs) → one batch folder with per-video transcripts,
   `combined.md`, `manifest.json`, optional `errors.log`. This is the
   reusable core that `research` and `subscribes update` also drive.
3. **Discovery layer (v0.6+).** Topic-driven (`research`) or channel-driven
   (`subscribes`) flows that find videos, hand them to the batch runner, and
   optionally call an LLM for a post-pass analysis.

Everything else is plumbing — config, presets, quality scoring, vision,
diarization, ASR correction, history log.

---

## 2. CLI surface (full)

### `transcribe <URL_or_path> [flags]`

Single video. Bare `youtube-transcribe <URL>` (no sub-command) also routes here
for back-compat.

Key flags (full list via `--help`):

- `--backend {smart,subtitles,whisper-local,gemini,groq,openai,deepgram,assemblyai,custom}`
- `--whisper-model {turbo,large,medium,small,distil}`
- `--language <code>` (else auto-detect)
- `--preset {eco,smart,standard,premium}` — bundle of (backend, vision, detection)
- `--cookies-file <path>` — Netscape cookies.txt. Required for IG (sign-in-only), useful for YouTube age-restricted / members-only. We deliberately do NOT support `--cookies-from-browser` — it pulls the entire browser cookie store into memory. Export the cookies you want via the "Get cookies.txt LOCALLY" extension (Chrome / Firefox / Edge / Brave / etc.) and pass the file path
- `--with-visuals` / `--vision-backend {off,gemini}` — visual moments
- `--correct-asr` (+ `--correct-asr-backend`) — LLM post-fix
- `--diarize` — pyannote speaker labels
- `--translate-to <code>` (+ `--translate-backend`) — output translation

Output: `./transcripts/<slug>_<video_id>.txt` and `.srt`.

### `batch [<URLs>...] [flags]`

Many inputs. Accepts inline URLs, channel URLs, playlist URLs, or `--from-file`.

Batch-specific:

- `--limit N` — first N from channel/playlist
- `--batch-name <name>` — override default `batch_<timestamp>_<auto-slug>`
- `--no-combined` — skip the `combined.md` aggregation
- `--fail-fast` — abort on first failure (default: continue-on-error)
- `--workers N` — parallel transcription (cloud backends only)
- `--skip-existing` — skip videos whose `_<video_id>.txt` already exists under output-dir
- `--search "query"` — `ytsearchN:query` instead of (or in addition to) inputs
- Channel filters: `--since`, `--until`, `--min-duration`, `--max-duration`, `--no-shorts`
- `--then-analyze` (+ `--prompt` / `--prompt-file` + `--analyze-backend`) —
  one LLM pass over the batch after it finishes. See §4.

Output: `<output-dir>/<batch_name>/`:

```
<batch_name>/
├── combined.md           ← aggregated transcript, YAML front-matter + per-video sections
├── manifest.json         ← machine-readable: videos, files, stats, backend, source_language
├── videos/
│   ├── 01_<slug>_<video_id>.txt
│   ├── 01_<slug>_<video_id>.srt
│   └── ...
├── analysis-YYYY-MM-DD-HHMM.md   ← only if analyze ran
└── errors.log            ← only if at least one video failed
```

### `research "<query>" [flags]` (v0.7)

Pipeline: translate query per language → search YouTube with built-in `sp=`
date filter → dedupe by `video_id` → optional substring/LLM filter → optional
TTY picker → batch transcribe → optional analyze.

Key flags:

- `--languages ru,en` — search per language; cross-lingual translation via LLM
- `--query-lang sr` — override script-based detection of the source language
- `--days N` / `--since YYYY-MM-DD` / `--until YYYY-MM-DD` — date window
- `--limit N` — top-N per language *before* dedup (so up to N×len(languages) before)
- `--match "substring"` — case-insensitive substring on title
- `--filter "LLM question"` — LLM pre-screen (e.g. "is this about politics?")
- `--in-subscribes` — instead of YouTube search, use latest videos from
  channels in `~/.youtube-transcribe/subscribes.toml`
- `--group <name>` — restrict to channels in this group (only with `--in-subscribes`)
- `--yes` — skip the TTY checkpoint
- `--no-analyze` — force-skip the LLM pass (recommended when driven from chat)
- `--analyze-backend {gemini,claude,openai,ollama}` — pick LLM explicitly
- All `batch` flags (`--backend`, `--whisper-model`, `--workers`, etc.) pass through

Output: same as batch + a row in `~/.youtube-transcribe/history.toml` with
id `r-MMDD-HHMMSS`.

### `subscribes` sub-commands (v0.7)

```
subscribes add <channel-url> [--group <name>]
subscribes remove <handle-or-url>
subscribes list [--group <name>]
subscribes edit                                  # opens subscribes.toml in $EDITOR
subscribes update [flags...]                     # main loop
subscribes schedule install [--every 1d] [--platform auto|cron|launchd|systemd]
subscribes schedule uninstall
```

`subscribes update` rules:

- For each channel: fetch RSS (fast) or yt-dlp scrape (with `--no-rss`),
  filter to videos newer than `last_seen_published`, transcribe, batch-output.
- First run on a channel **without** state: require `--days N` or `--since`.
- After RSS yields entries, advance `last_seen_*` **regardless** of
  transcription success (v0.7 bootstrap fix — see §5).
- `--days` / `--since` / `--until` override the incremental window. On a
  channel that *already has state*, the override DOES NOT touch state. On a
  channel without state, the same flags initialize state (bootstrap).

### `analyze` (v0.6)

Post-hoc LLM pass on already-transcribed material. Most chat-Claude flows
don't need this — read `combined.md` directly. Useful for re-running with a
different prompt or selecting a subset.

```
analyze --transcript <file>.txt --prompt "..." --backend ollama
analyze --latest --all --prompt-file p.md --backend gemini
analyze --batch <batch_dir> --select "1,3,5-7" --prompt "..."
analyze --append-to <existing-analysis.md> --prompt "another angle"
```

### `history` (v0.7)

```
history list [--last N] [--type research|subscribes]
history show <run-id>
```

Read-only. IDs are short (`r-MMDD-HHMMSS` / `s-MMDD-HHMMSS`).

### `config` sub-commands

```
config show                # current TOML + which API keys are set (masked)
config set <key> <value>   # write to ~/.youtube-transcribe/config.toml
config set-key <backend>   # interactively store an API key in .env
config test <backend>      # sanity-check a backend's configuration
config wizard              # re-run first-run setup
```

### Hidden / experimental

- `webui` — exists, hidden from `--help`. Gradio-based, not maintained. Code
  preserved under `skills/youtube_transcribe/webui/` for future revival.

---

## 3. File and module map

For deeper navigation use [`graphify-out/graph.json`](../graphify-out/graph.json)
or `/graphify query "..."`. High-level structure:

```
skills/youtube_transcribe/
├── transcribe.py             # CLI entry point — all sub-commands, also _run_batch_pipeline
├── pipeline.py               # single-video pipeline (download → backend → write)
├── pipeline_v02.py           # v0.2+ post-pipeline stages: quality, vision, OCR
├── config.py                 # Config dataclass, TOML I/O, API key handling
├── wizard.py                 # first-run interactive setup
│
├── backends/                 # one Transcriber implementation per provider
│   ├── base.py               # Transcriber Protocol, BackendError, BackendNotConfigured
│   ├── factory.py            # build_backend(name, cfg) + smart-mode composition
│   ├── subtitles.py
│   ├── whisper_local.py      # mlx-whisper on Apple Silicon, faster-whisper elsewhere
│   ├── gemini.py / groq.py / openai_api.py / deepgram.py / assemblyai.py / custom.py
│   └── vision_base.py        # VisionBackend Protocol + VisualSegment
│
├── analyze/                  # v0.6 free-form LLM analysis
│   ├── source_resolver.py    # locate transcripts (latest / batch / explicit)
│   ├── picker.py             # questionary TUI for video selection
│   ├── prompt_builder.py     # assemble system + user + transcripts
│   ├── runner.py             # call gemini/claude/openai/ollama
│   ├── output_writer.py      # analysis-*.md + --append-to
│   ├── select_parser.py      # "1,3,5-7" → [0,2,4,5,6]
│   └── backend_resolver.py   # v0.7 — flag > config > onboarding > skip
│
├── research/                 # v0.7 topic search + transcribe
│   ├── source.py             # multi-lang yt-dlp search + SP date filter
│   ├── translator.py         # LLM query translation
│   └── pipeline.py           # run_research() orchestrator
│
├── subscribes/               # v0.7 channel watch
│   ├── store.py              # subscribes.toml CRUD
│   ├── state.py              # last_seen tracking
│   ├── rss.py                # YouTube RSS feed (urllib + xml.etree)
│   ├── channel_resolver.py   # url → channel_id, one-time at add
│   ├── group.py              # group filtering
│   ├── cli.py                # subscribes add/remove/list/edit/update + schedule
│   ├── pipeline.py           # run_subscribes_update() orchestrator
│   └── schedule.py           # cron/launchd/systemd/Task Scheduler snippet gen
│
├── history/                  # v0.7 run log
│   ├── store.py              # history.toml read/append
│   └── cli.py                # history list/show
│
├── shared/                   # cross-command helpers
│   ├── date_filter.py        # --days / --since/--until window math
│   ├── match.py              # substring filter
│   └── llm_screen.py         # LLM pre-screening
│
├── quality/                  # v0.2+ ASR scoring + correction
│   ├── heuristic_checker.py  # boh + repetition + spell + perplexity → score
│   ├── boh.py / repetition.py / spell.py / perplexity.py
│   ├── asr_corrector.py      # LLM-based correction on low-score segments
│   ├── summarizer.py         # legacy thin wrapper kept for `summarize` cmd
│   └── translator.py
│
├── detection/                # v0.2 visual moment detection
│   ├── triggers.py + triggers_cli.py
│   ├── matcher.py            # Aho-Corasick keyword matching
│   ├── frame_diff.py / scene.py
│   ├── llm_classify.py       # full-pass LLM detection
│   └── window_merge.py
│
├── vision/                   # v0.2 vision backends + frame/ocr extraction
│   ├── gemini.py / claude_vision.py / openai_vision.py
│   ├── frames.py             # ffmpeg keyframe extraction
│   ├── ocr.py                # pytesseract (opt-in)
│   └── prompts.py
│
├── presets/                  # v0.2 (eco/smart/standard/premium) — TOML data + loader
│
├── utils/
│   ├── downloader.py         # yt-dlp wrapper, URL classifiers, expand_channel/playlist
│   ├── resolver.py           # ResolvedTarget + resolve() (URL → list[ResolvedTarget])
│   ├── output_writer.py      # combined.md / manifest.json / errors.log
│   ├── transcript_loader.py  # read .txt with/without timestamps
│   └── platform_detect.py    # darwin+arm64 → mlx, else → faster-whisper
│
└── webui/                    # v0.4 Gradio UI — hidden, experimental
```

---

## 4. Analyze backend resolution (v0.7)

The single most important rule for chat-Claude:

**When you invoke `research`, `subscribes update`, or `batch --then-analyze`
from inside Claude Code, always pass `--no-analyze`. You will read
`combined.md` yourself and answer the user's question in chat. There is no
point routing transcripts through a second LLM API.**

The CLI's analyze resolution order
([`backend_resolver.py`](../skills/youtube_transcribe/analyze/backend_resolver.py)):

1. `--no-analyze` → return `None` (skip)
2. `--analyze-backend X` → return `X`
3. config `[analyze] backend = "skip"` → return `None`
4. config `[analyze] backend = X` → return `X` (one of gemini/claude/openai/ollama)
5. TTY + no preference saved → one-shot interactive prompt, save choice, return it
6. Non-TTY + no preference → return `None` (silent skip)

Claude Code drives the CLI via subprocess (non-TTY), so without an explicit
flag the analyze step is always skipped — which is the right default. The
`--no-analyze` flag in chat invocations is belt-and-braces and makes intent
obvious in logs.

Fallback chain on analyze failure: when the primary backend returns "" (quota
/ 429 / network), the chain falls through `gemini → claude → openai → ollama`,
skipping any without a configured key. Ollama is always included as the local
fallback. If the primary backend has no key, exit 4 (don't silently substitute).

---

## 5. State and storage

### Files in `~/.youtube-transcribe/`

| File | Purpose | Format |
|---|---|---|
| `config.toml` | Settings, default backend, preset, analyze.backend | TOML |
| `.env` | API keys (perms 0600 on Unix) | dotenv |
| `subscribes.toml` | Channels you follow + per-channel state | TOML (round-tripped via tomlkit, preserves comments) |
| `history.toml` | Append-only log of research/subscribes runs | TOML |
| `state.json` | yt-dlp auto-update timestamp | JSON |

Schemas live in code:

- `Config` — [`config.py`](../skills/youtube_transcribe/config.py)
- `Channel` — [`subscribes/store.py`](../skills/youtube_transcribe/subscribes/store.py)
- `RunEntry` — [`history/store.py`](../skills/youtube_transcribe/history/store.py)

### `subscribes` state semantics (v0.7 bootstrap rule)

- `last_seen_published` advances after every successful RSS fetch that yielded
  entries, regardless of subsequent transcription outcome. A one-off 429 does
  not pin the channel.
- First run on a channel **with** `--days N` (or `--since`): bootstrap path
  — initialize `last_seen_*` to the newest video seen.
- Override (`--days` / `--since`) on a channel that *already has state*:
  one-off window, state is NOT touched.
- Override on a channel **without** state: bootstrap (state IS initialized).

Failed video_ids stay in `errors.log` of each batch dir. Re-fetch them via
`research --since DATE` or `transcribe <URL>` directly.

---

## 6. Platform support

| Command | YouTube | Instagram | TikTok | Other yt-dlp sites | Local files |
|---|---|---|---|---|---|
| `transcribe <URL>` / `batch <URL>` | ✓ | ✓ (needs `--cookies-file`) | ✓ | ✓ | ✓ |
| `research "query"` | ✓ | ✗ | ✗ | ✗ | n/a |
| `subscribes` | ✓ (RSS) | ✓ (cookies + yt-dlp / instaloader fallback) | ✓ (cookies + yt-dlp) | ✗ | n/a |

Instagram URL detector lives in
[`utils/downloader.py`](../skills/youtube_transcribe/utils/downloader.py)
(`_INSTAGRAM_RE`). The friendly error message about cookies is printed
upstream in the same file.

`research` is YouTube-only because `yt-dlp ytsearchN:` only supports YouTube.

`subscribes` per-platform source dispatch lives in
[`subscribes/pipeline.py`](../skills/youtube_transcribe/subscribes/pipeline.py):
- **YouTube** — RSS feed (no cookies needed).
- **Instagram** — yt-dlp first; if its profile extractor is marked broken
  upstream (signature: `"marked as broken"` / `"unable to extract data"` /
  `"empty media response"`), falls back to **instaloader** (`[instagram]`
  optional extra). Cookies come strictly from the registered Netscape file —
  never `cookies-from-browser`. See
  [`subscribes/instagram_loader.py`](../skills/youtube_transcribe/subscribes/instagram_loader.py).
- **TikTok** — yt-dlp only (no fallback library).

Install the IG fallback with `uv sync --extra instagram`. It is intended for
occasional fetches (a few channels, infrequent updates), NOT bulk scraping —
the loader prints a one-time warning per process.

---

## 7. Common failure modes and exit codes

| Exit | Meaning | Typical hint |
|---|---|---|
| 0 | Success | — |
| 1 | Generic error | check stderr |
| 2 | Bad user input (mutex flags, missing prompt for analyze, validation fail) | re-read the CLI help |
| 3 | TTY required but not available (questionary picker without `--yes`) | pass `--yes` or `--all` / `--select` |
| 4 | Backend not configured / API key missing / analyze unavailable | `config set-key <backend>` |

Examples that exit 2:
- `research` with `--prompt` AND `--prompt-file`
- `research --days N --since YYYY-MM-DD` (mutex)
- `subscribes update` on a channel with no state, without `--days` / `--since`
- `analyze` with neither `--all` nor `--select` in a non-TTY

---

## 8. Important invariants

- **Skill kebab-name, package snake_name.** The plugin / CLI is
  `youtube-transcribe`; the Python package is `youtube_transcribe`.
- **Cross-OS markers.** `mlx-whisper` is gated by `sys_platform == 'darwin'
  and platform_machine == 'arm64'`. `faster-whisper` is the symmetric marker
  (`not(...)` via De Morgan). Never import these unconditionally — see
  [`utils/platform_detect.py`](../skills/youtube_transcribe/utils/platform_detect.py).
- **`uv.lock` not committed.** Cross-platform skill, every platform resolves
  its own. Same for `.python-version`.
- **Tests are pure unit-tests by default.** End-to-end smoke tests live
  behind `RUN_E2E_SMOKE=1`. Don't accidentally enable that env in CI without
  secrets.
- **`--backend` is the canonical dest name.** Click options for `--backend`
  and `--language` MUST use the bare dest (no `_opt` rename) — see
  [v0.7 fix `5551a5e`](https://github.com/nekith78/youtube-transcribe/commit/5551a5e)
  for the bug they hide. The `_run_batch_pipeline` reads
  `opts.get("backend")`, not `opts.get("backend_opt")`.

---

## 9. How to add a new backend

Concrete checklist (see existing implementations under
[`backends/`](../skills/youtube_transcribe/backends/) for examples).

1. Create `backends/<name>.py` exposing a class that implements the
   `Transcriber` protocol from `backends/base.py`. Required methods:
   `is_configured() -> tuple[bool, str | None]` and
   `transcribe(audio_path, language) -> TranscriptionResult`.
2. Register in `backends/factory.py`'s `build_backend()`.
3. If it has an API key, add the env var name to `_BACKEND_ENV_VAR` in
   `config.py`. Add field to `Config` dataclass if user-tunable.
4. Add to the `BackendName` Literal in `config.py` and to `BACKEND_CHOICES`
   in `transcribe.py`.
5. Add `Backend not configured` and key-hint messages.
6. Write unit tests that mock the SDK — backend tests live at
   `tests/test_backends_*.py` and run against the Protocol, not the SDK.
7. Update README's "Backends overview" table and add a usage example.

---

## 10. How to query this graph as an agent

```bash
/graphify query "How does the analyze pipeline work?"
/graphify path "research_cmd" "Transcriber"
/graphify explain "_run_batch_pipeline"
```

The graph is built from `skills/youtube_transcribe/` only (tests, docs/, .venv
excluded). Re-build it after touching code:

```bash
/graphify --update                # incremental, code-only changes are LLM-free
/graphify .                       # full rebuild
```

The committed `graphify-out/graph.json` and `GRAPH_REPORT.md` are the
"fresh clone" baseline.
