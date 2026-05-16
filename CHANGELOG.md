# Changelog

All notable changes to neurolearn will be documented here.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com/).

## [0.10.2] — 2026-05-16

### PDF report generation

New `neurolearn report <batch_dir>` subcommand. Takes an already-
transcribed batch (manifest.json + SRT + keyframes) and produces a
structured PDF report with title, executive summary, sectioned
table of contents, per-section key points, embedded keyframes, and
inline timestamps.

**How it works:**

1. **Outliner** asks an LLM (gemini / claude / openai / ollama) to
   structure the transcript + visual segments into a JSON outline
   matching the report's prompt template.
2. **Renderer** flows the outline through a Jinja2 HTML template
   (`report/data/templates/base.html` + `base.css`), downscales any
   referenced keyframes to ≤1000px via Pillow, embeds them as base64
   data URIs, and pipes everything through WeasyPrint to produce a
   self-contained, A4-paginated PDF.

**Prompt templates** (parallel to v0.10.1 vision prompts):
- Built-in: `tutorial`, `vlog`, `generic` in
  `skills/neurolearn/report/data/report_prompts_default.toml`.
- User override: `~/.neurolearn/report_prompts.toml` with the
  same `[global] prefix` / `[prompts.<type>] prompt + append_global`
  shape.
- CLI override: `--prompt-template-file <path>` for a one-off.
- Single-call for transcripts under ~15k tokens; **hierarchical**
  chunk-then-assemble for longer ones — per-chunk outlines feed a
  final assembly call for a top-level title + summary.

**Defaults that make the report do the right thing without flags:**
- Auto-detect `report_type` from the transcript via the same
  classifier that powers vision prompts (`tutorial / lecture / code
  / demo / interview / vlog / review / talking_head / generic`,
  mapped onto the three report templates).
- Auto-pick `target_language` from the video's detected language;
  interactive prompt with the detected language as default when
  stdin is a TTY (skipped with `--yes`).
- Friendly install hint if the `report` optional extra is missing —
  no crash, just one-line instructions on how to install.

**Flags** (`neurolearn report --help`):
- `--latest`, `--video-index N` — batch selection / multi-video.
- `--prompt`, `--prompt-file`, `--prompt-template-file`.
- `--report-type {auto|tutorial|vlog|generic}`.
- `--report-language en|ru|...`.
- `--backend {gemini|claude|openai|ollama}` + `--ollama-model/host`.
- `--output <path>`, `--max-images N`, `--max-image-width N`,
  `--no-screenshots`, `--keep-html`, `--yes`.

**Optional dependencies** (`uv sync --extra report`):
- `weasyprint>=62.0` (LGPL, free) for PDF.
- `jinja2>=3.1` for templating.
- `markdown>=3.6` reserved for future inline markdown in summaries.
- On macOS the bundle also requires `brew install pango cairo` for
  WeasyPrint's native libraries; the package primes
  `DYLD_FALLBACK_LIBRARY_PATH` automatically so the brew libs are
  found.

**Resilient parsing.** LLM responses are accepted even when they
arrive wrapped in markdown fences, include preamble, return a
single timestamp/list-item as a string instead of a one-element
list, or contain bracketed timestamps; an unparseable response
produces a degraded outline (so the PDF still renders) rather than
crashing the pipeline.

**Test coverage.** 50 dedicated tests across prompts loader, outliner,
renderer, orchestrator, and CLI (`tests/test_report_*.py`). Full
suite: 1032 passed, 3 skipped, no regressions.

## [0.10.1] — 2026-05-15

### Vision prompts: per-video-type templates + user customization

Replaces the single generic YouTube-flavoured prompt with **9
context-specific templates**. The right prompt is picked
automatically from the transcript; users can override it.

**Built-in types** (in `skills/neurolearn/vision/data/prompts_default.toml`):
  • `tutorial` — UI actions, click targets, before/after states
  • `lecture` — slides, diagrams, equations
  • `code` — IDE, terminal, file paths, errors
  • `demo` — product showcase, feature reveal
  • `interview` — multi-speaker, lower-thirds, B-roll
  • `vlog` — scene, activity, location
  • `review` — product, specs, comparison
  • `talking_head` — narrative monologue with minimal visuals
  • `generic` — fallback for unclassified video

Each template is 300-500 tokens with type-specific rules + a
good/bad example. The previous YouTube-flavoured generic text is
gone; templates are source-agnostic (work for YouTube / IG / TikTok
/ local files).

**Auto-detection** lives in
`skills/neurolearn/detection/video_type_detect.py`. Counts type-specific
signal phrases (e.g. "click/press/нажимаем" for tutorial;
"slide/research shows/today we'll" for lecture) per minute. Whichever
type clears its threshold wins; long videos with no positive signal
default to `talking_head`; short signal-less clips default to `generic`.

**User overrides** at `~/.neurolearn/prompts.toml`. Same shape as the
shipped TOML:

```toml
[global]
prefix = "..."          # universal rules, prepended to every type

[prompts.tutorial]
prompt = "..."          # full per-type instruction
append_global = true    # default; set false to use ONLY this prompt

# Brand-new mode — define your own type:
[prompts.cooking-show]
prompt = "Focus on ingredients, utensils, cooking actions."
append_global = false
```

**New CLI flags** (transcribe + batch):
  • `--video-type <name>` — pin a specific type (skips auto-detect)
  • `--no-global-prefix` — with `--vision-prompt`, drop the global prefix

### Gemini API improvements

- **Caching the right thing**. Previous build cached only the system
  prompt (~150 tokens) which falls below the 1024-token cache
  minimum and never activated. v0.10.1 caches `[uploaded_video,
  system_instruction]` together — the video easily clears the
  minimum, so the bundle qualifies. Per-window calls now reference
  the cache and pay only 25% of the rate on the cached tokens (which
  are the dominant cost). Expected savings: 70-75% of vision tokens
  on multi-window videos.
- **Skip caching when N<2 windows**. For a 1-window video, the
  setup + storage cost outweighs the single cached call. Now we
  bypass cache creation entirely in that case.
- **Adaptive concurrency by Gemini tier**. New `gemini_tier` config
  field: `"free"` (default) → `max_concurrent=3` (under the 5 RPM
  free-tier limit); `"paid"` → 10; `"paid-tier2"` → 20; `"paid-tier3"`
  → 50. Override per-call via constructor `max_concurrent` if needed.
- **Honor server-side retryDelay**. 429 RESOURCE_EXHAUSTED responses
  include `"retryDelay": "31s"` — we now parse and sleep exactly
  that long instead of using the hard-coded `[3, 6, 12]` backoffs
  which previously missed the per-minute quota reset.

### Tests

- 12 new tests in `test_video_type_detect.py` — every type recognised
  on representative transcripts; lecture rejected from tutorial-style
  text; talking_head for long signal-less videos
- 16 new tests in `test_vision_prompts_loader.py` — built-in types
  load, user overrides replace, global prefix prepend, custom types,
  CLI inline template, broken TOML falls back, format_prompt substitution
- 12 new tests in `test_gemini_caching_concurrency.py` — tier mapping,
  retryDelay parsing, cache-skip-on-N=1, cache-with-video-on-N≥2,
  cached-call omits video, cache failure fall-back
- Updated `test_custom_vision_prompt.py` to the new `_resolve_vision_prompt`
  contract (was `_load_vision_prompt`)

Total: 972 passed, 3 skipped.

---

## [0.10.0] — 2026-05-15

### Visual pipeline optimization — 9 improvements

Based on a production-guide audit of our Gemini Flash vision pipeline.
On a typical 10-minute tutorial video, total Gemini cost drops ~12×
and end-to-end visual stage runs ~10× faster.

#### Cost wins

- **MEDIA_RESOLUTION_LOW** for Gemini video uploads — 66 tokens/sec
  instead of 258 (4× cheaper). UI tutorials and most lecture content
  remain legible at LOW; only 4K-detail content would benefit from
  HIGH. (`vision/gemini.py`)
- **Prompt caching** — system instruction is cached once per video,
  reused across all per-window calls. ~75% off input tokens after
  the first window. Falls back gracefully (per-call inclusion) when
  caching is unavailable.
- **Frame downscaling + quality cap** — ffmpeg output frames are
  capped at 1280px wide and JPEG quality 80%. Same description
  accuracy, ~5× smaller file size → fewer image tokens.

#### Quality wins

- **Structured output via response_schema** — Gemini cannot return
  invalid JSON anymore. New schema includes `confidence` (0-1) and
  `needs_refinement` (bool) signals.
- **temperature=0.2 + max_output_tokens=300** — determinism and
  capped output cost.
- **Tutorial preset with asymmetric frame offsets** —
  `-1.5s / +0.3s / +2.0s` relative to the speech event captures
  before-state, the click moment (motor-lag from speech to action
  is ~300ms), and the UI-settled-after state. Far more useful for
  step-by-step UI tutorials than evenly-spaced frames.
- **Claude fallback on low-confidence segments** — when Gemini
  reports `confidence < 0.7` or `needs_refinement=True` (typically
  10-20% of windows), the same windows are re-processed through
  Claude Vision. Better accuracy on small UI text / similar
  elements; only pays Claude pricing on the subset that needs it.
  Requires `ANTHROPIC_API_KEY`; silently skipped if absent.

#### Speed wins

- **Async parallelism** in `GeminiVisionBackend.annotate_segments` —
  `asyncio.Semaphore(10)` concurrent window calls. The sync facade
  is preserved; callers don't need to be async. On 18-window TED Talk
  this drops from ~5 minutes sequential to ~30 seconds.

#### Observability

- **BudgetTracker module** (`skills/neurolearn/budget.py`) — per-call
  token accounting with per-provider USD pricing. Aggregates totals
  by stage (vision_gemini, vision_claude, analyze, asr_correction,
  translate, filter, research_translate). Wired into manifest.json
  so users see what each batch cost without spelunking through
  provider dashboards.

#### New `tutorial` preset + auto-detection

- New built-in preset `tutorial` in `presets/data/presets_default.toml`:
  whisper-local transcribe, gemini vision, keywords_only detection,
  asymmetric frames, Claude fallback.
- **Auto-promotion from smart**: after transcription, when running
  the `smart` preset without explicit `--preset` override, we count
  tutorial-action triggers (click / press / нажимаем / выбираем /
  open / save / select / type / ...) in the transcript. Density
  above 1.5/min auto-promotes to the tutorial preset; a one-line
  notice tells the user. Disable with `--preset smart` explicitly
  or set `auto_tutorial_detect = false`.
- Detector lives in `skills/neurolearn/detection/tutorial_detect.py`
  with hardcoded action regex for ru/en (separate from user-editable
  triggers.toml — this is feature detection, not personalisation).

#### Schema

- `VisualSegment` gained `confidence: float` and `needs_refinement: bool`
  fields. Backward compatible — both default to safe values for old
  callers/test fixtures.

### Tests

- 6 new tests in `test_budget.py` — token math + cost edge cases
- 6 new tests in `test_tutorial_detect.py` — density heuristic in
  ru + en, lecture rejection, short-clip safeguard
- 5 new tests in `test_claude_fallback.py` — refinement triggering,
  Claude error keeps original, empty-list short-circuit
- Updated `test_vision_gemini.py` to match new defensive cache path

Total: 924 passed, 3 skipped.

---

## [0.9.0] — 2026-05-14

### Renamed
- **Project renamed from `youtube-transcribe` to `neurolearn`.**
  Scope:
  - Python package: `skills/youtube_transcribe/` → `skills/neurolearn/`
  - PyPI / CLI binary: `youtube-transcribe` → `neurolearn`
  - Config directory: `~/.youtube-transcribe/` → `~/.neurolearn/`
  - Claude Code plugin name: `youtube-transcribe` → `neurolearn`
  - GitHub repository: github.com/nekith78/youtube-transcribe → github.com/nekith78/neurolearn
    (the old URL keeps redirecting for ~3 months per GitHub policy)
  - Scheduler identifiers: `youtube-transcribe-subscribes` →
    `neurolearn-subscribes` (cron / launchd / systemd / Task Scheduler
    snippets). Any previously installed scheduler entries with the old
    label need to be reinstalled — `neurolearn subscribes schedule
    install` prints the new snippets.

### Auto-migration on first run
- If `~/.youtube-transcribe/` exists and `~/.neurolearn/` doesn't, the
  CLI renames the directory once on first invocation and prints a
  one-line notice to stderr. Idempotent. All API keys, cookies,
  subscribes.toml, history.toml, and triggers.toml carry over without
  user action.

### Why the rename
- The skill outgrew its original scope. v0.7+ added research, subscribes,
  and analyze; v0.8 added Instagram and TikTok. "youtube-transcribe" no
  longer described what the tool does. `neurolearn` better reflects the
  current focus: learning from videos across platforms — transcribe,
  analyze, research a topic, follow channels over time.

---

## [0.8.0] — 2026-05-14

### Added
- **Instagram & TikTok in `subscribes`** — `subscribes add` accepts
  IG profile URLs and TikTok user URLs. Per-platform fetch dispatch
  in `subscribes/pipeline.py`: YouTube via RSS (no cookies), Instagram
  and TikTok via yt-dlp with the user's registered Netscape
  `cookies.txt`. `subscribes update --platform {youtube|instagram|tiktok}`
  filters to a single platform.
- **Instagram fallback via instaloader** — when yt-dlp's IG profile
  extractor is marked broken upstream (which happens periodically),
  we fall back to instaloader for profile listing. Opt-in extra:
  `uv sync --extra instagram`. Prints a one-time per-process warning
  on first fallback ("intended for occasional fetches, not bulk
  scraping"). See `subscribes/instagram_loader.py`.
- **Interactive URL/query prompts** — `transcribe`, `batch`,
  `subscribes add`, and `research` accept an empty positional and
  prompt instead. Lets users paste long URLs after running the
  command (keeps them out of shell command lines / shell history).
  Non-TTY callers without args exit 2 with a clear message so CI
  scripts fail fast. See `shared/prompts.py`.
- **Spinner progress for single-video `transcribe`** — `rich.status`
  spinner with stage labels (Downloading audio... / Transcribing via
  X... / Post-processing...). `--verbose` switches to plain dim
  print lines so raw yt-dlp / SDK output stays readable. Non-TTY
  degrades automatically. See `shared/progress.py`.
- **Cookies onboarding wizard** — `subscribes cookies set <platform>`
  with interactive `questionary.path()` prompt (Tab-completion +
  drag-and-drop). Validates Netscape format before saving. Stores
  registered file at `~/.neurolearn/<platform>-cookies.txt`
  with mode 0600. See `subscribes/cookies_onboarding.py`.

### Changed
- **Security: strict file-only cookies.** All paths that previously
  accepted `--cookies-from-browser` now require an explicit Netscape
  `cookies.txt` file (`--cookies-file <path>` for transcribe/batch;
  `subscribes cookies set <platform> <path>` for IG/TT). Rationale:
  `cookies-from-browser` reads the user's entire browser cookie store
  into process memory — even on macOS where Keychain prompts, an
  "Always Allow" grant silently leaks all unrelated cookies. We
  refuse to take that risk; the cost is one manual cookies-export
  step.
- **All user-facing CLI strings migrated to English.** Wizard, error
  messages, status lines, prompts, help text — previously a Russian /
  English mix, now English-only. Industry standard for CLIs with a
  global audience.
- **`smart` backend fallback now downloads audio.** Previously
  `transcribe URL --backend smart` failed with "Audio file not found:
  <url>" when subtitles fast-path didn't succeed (e.g. YouTube
  IpBlocked on TimedText). All non-subtitles backends require a local
  audio file; `run_smart` now downloads into a temp directory before
  invoking the fallback backend.
- **yt-dlp broken-extractor diagnostic.** `_diagnose_ytdlp_error` now
  checks for "Unable to extract data" / "marked as broken" at the
  TOP of the hint ladder, before generic geo/country/auth heuristics
  could win on misleading sub-strings of the same stderr. Without
  this, the subscribes pipeline's broken-extractor detection never
  fired for IG and the instaloader fallback was silent.
- **Stale `yt-tr` references removed from README.** The real CLI
  binary has always been `neurolearn`; `yt-tr` was never an
  alias. 18 occurrences corrected.

### Dependencies
- `instaloader>=4.13` — new optional extra `[instagram]`.

### Fixed
- `subscribes` pipeline now propagates broken-extractor exceptions
  from `_fetch_via_yt_dlp` instead of swallowing them. Enables the
  instaloader fallback to actually fire for Instagram.

---

## [0.7.0] — 2026-05-12

### Added
- `research "query"` — broad topic discovery: multi-language YouTube
  search (LLM-translates query into each `--languages`), date window
  (`--days N` or `--since/--until`), substring `--match` and LLM
  `--filter` pre-screens, optional TTY checkpoint, batch transcribe,
  optional analyze. Also supports `--in-subscribes` to source from
  your subscribed channels instead of global search.
- `subscribes` command group (`add`/`remove`/`list`/`edit`/`update`)
  for tracking favourite channels. Stateful incremental updates
  (`last_seen_video_id` per channel in subscribes.toml). Override
  with `--days`/`--since`/`--until` runs ad-hoc without disturbing
  state. RSS-first discovery (~10× faster than yt-dlp scraping);
  `--no-rss` forces yt-dlp fallback (not yet implemented in v0.7).
- `subscribes schedule install --every <interval>` — generates cron /
  launchd / systemd / Windows Task Scheduler snippet + install
  instructions. Does NOT install automatically.
- `history list` / `history show` — persistent log of research and
  subscribes runs in `~/.neurolearn/history.toml`.
- Web UI tab builders — `build_research_tab(gr)` and
  `build_subscribes_tab(gr)`. (Default `build_ui()` still ships the
  v0.5 transcribe form; call the new builders from your custom
  Gradio Blocks if needed.)
- Channel groups in subscribes.toml (`group = "ai-research"`).
  `subscribes list --group X` and `subscribes update --group X`.

### Changed
- `batch_cmd` refactored: post-args-resolution core extracted as
  `_run_batch_pipeline(targets, cfg, opts)` so research/subscribes
  pipelines reuse it without duplication. External behavior of
  `neurolearn batch` preserved byte-for-byte (all 614 v0.6
  tests stay green).

### Dependencies
- No new runtime dependencies. RSS via stdlib `xml.etree.ElementTree`
  + `urllib.request`. Everything else already in v0.2/v0.6 deps.

## [0.6.0] — 2026-05-12

### Added
- `neurolearn analyze [SOURCE]` — free-form LLM analysis over
  one or more existing transcripts. Supports `--prompt`/`--prompt-file`,
  `--backend gemini|claude|openai|ollama`, `--latest`, `--all`,
  `--select "1,3,5-7"`, `--append-to <md>`, `--output <path>`,
  `--no-stdout`, `--max-chars`.
- Interactive `questionary` checkbox picker for video selection when
  SOURCE is a folder and no `--all`/`--select`/`--latest` is given.
- `batch --then-analyze --prompt "..."` runs analyze on the produced
  batch folder immediately after the batch completes.

### Changed
- `summarize` now routes through `analyze.runner` internally (same
  hardcoded TL;DR + key points + notable quotes template; same exit
  codes; same output file format). No user-visible behavior change.

### Dependencies
- New: `questionary>=2.0` (powers the analyze picker).

## [0.5.2] — 2026-05-11

Course-correct: revert / refactor v0.5.1 additions that drifted from spec.

### Removed

- **VTT output format.** Was an invented addition not in any spec.
  `--output-format vtt` choice and `write_vtt()` function removed.
- **Auto-summary `--summary` flag in `transcribe` / `batch`.** Spec
  explicitly said summarization is done by Claude in chat reading
  `combined.md`, not by the skill in v0.x. Auto-trigger removed.
- **`summary` field on `TranscriptionResult`** + `summary` param in
  `write_json()` — no longer populated by pipeline.

### Added

- **`neurolearn summarize <transcript-path>`** — standalone
  sub-command. User invokes explicitly on an existing
  transcript file (`.txt` / `.json` / `.srt`). Backend picked via
  `--backend gemini|claude|openai|ollama`. Output: `<file>.summary.md`
  next to the source (or `--output PATH`).
- **`utils/transcript_loader.py`** — reads `.txt` / `.json` / `.srt`
  back into `list[Segment]`. Used by the `summarize` command.

### Tests
- 544 unit tests green (was 533 in v0.5.1; -7 from VTT removal,
  +16 from new loader + summarize).

## [0.5.1] — 2026-05-11

Power-user polish.

### Added

- **`--summary` flag** — generates a Markdown auto-summary (`## TL;DR`,
  `## Key points`, `## Notable quotes`) alongside the transcript via a
  single cheap LLM call (gemini / claude / openai / ollama).
  `<basename>.summary.md` is written when transcript completes.
- **`--output-format {txt,srt,vtt,json,all}` (repeatable)** — choose any
  combination of output files. Defaults to `txt` + `srt` for backward
  compatibility. JSON includes full transcript + quality + visuals +
  summary — drop-in for tooling/automation.
- **`--vision-prompt FILE`** — provide a custom vision-LLM template
  file. Placeholders: `{language}`, `{transcript_snippet}`,
  `{start_sec}`, `{end_sec}`. Tutorial authors can tune the description
  style without forking the package.

### Changed

- `TranscriptionResult` gains a `summary: str = ""` field. Backward-
  compatible with v0.5.0 callers.
- `write_json()` and `write_vtt()` added to `utils/output_writer.py`.
  JSON uses `ensure_ascii=False` so Cyrillic and other scripts stay
  readable in the file.

### Tests
- 533 unit tests green (was 510 in v0.5.0; +23).

## [0.5.0] — 2026-05-11

Local-LLM + multi-speaker + multi-language.

### Added

- **Ollama backend for ASR correction** (`--correct-asr-backend ollama`).
  Local llama3.2:3b by default — no API key, no cloud round-trip.
  POSTs to http://localhost:11434/api/generate via stdlib urllib.
  Two new registry fields: `ollama_model` (default `llama3.2:3b`) and
  `ollama_host` (default `http://localhost:11434`).
- **Speaker diarization** via pyannote.audio (`--diarize`). Prepends
  each segment's text with `[SPEAKER_NN]`. Opt-in `[diarization]` extra,
  requires HF_TOKEN env var + license at
  https://huggingface.co/pyannote/speaker-diarization-3.1.
  `diarize_num_speakers` field constrains the model when known
  (0 = auto-detect).
- **Auto-translate** (`--translate-to <lang>`). Translates each segment's
  text via cheap LLM (gemini-flash / claude-haiku / gpt-4o-mini / local
  Ollama) while preserving timestamps + speaker labels. Backend chosen
  via `--translate-backend` (default `gemini`).

### Tests
- 510 unit tests green (was 484 in v0.4.1; +26 v0.5 tests).

## [0.4.1] — 2026-05-11

### Added

- **`--correct-asr` CLI flag** for both `transcribe` and `batch`
  sub-commands. Auto-enables `--check-quality` (correction triggers
  off the quality recommendation). Honored by `--no-quality-check`
  if user explicitly overrides.
- **`--correct-asr-backend gemini|claude|openai`** picks the LLM
  provider for ASR correction.
- **Rich Live progress bar in batch_cmd.** Spinner + progress bar +
  `ok=N fail=N` counters + elapsed time. Auto-disabled with
  `--verbose` or when only one video is being processed.

### Tests
- 484 unit tests green (was 480 in v0.4.0; +4 CLI ASR flag tests).

## [0.4.0] — 2026-05-11

Multimodal alternatives + post-processing + Instagram + Web UI.

### Added

- **Claude Sonnet vision backend** (`--vision-backend claude`). Images-only,
  reuses ffmpeg keyframes. Default model: claude-sonnet-4-6. Needs
  `ANTHROPIC_API_KEY`.
- **OpenAI GPT-4o vision backend** (`--vision-backend openai`). Images-only,
  base64 data URLs. Default model: gpt-4o.
- **ASR error correction** (`correct_asr: true` in preset, or future CLI
  flag). When quality check flags a transcript as fallback / low_quality,
  one cheap LLM call (gemini-flash / claude-haiku / gpt-4o-mini) fixes
  garbled/truncated words. Best-effort: returns original on any error.
  Provider via `correct_asr_backend` registry option.
- **Instagram URL recognition.** `is_instagram_url`,
  `extract_instagram_shortcode` for `/p/`, `/reel/`, `/tv/`, `/reels/`
  patterns. yt-dlp handles the downloading; tailored error message hints
  to `--cookies-from-browser` when login required.
- **Web UI** via Gradio (`neurolearn webui`). URL/file input,
  preset/backend selectors, visual + ASR-correct toggles. Output tabbed:
  Transcript / Visual moments / Quality. Local-only by default
  (127.0.0.1:7860). Opt-in via `[webui]` extra.

### Changed

- `vision_backend` choices now `["off", "gemini", "claude", "openai"]`.
- `_BACKEND_ENV_VAR` now includes `anthropic` → `ANTHROPIC_API_KEY`.
- `core deps` adds `anthropic>=0.40.0` (small; comparable to existing
  openai/groq SDKs).
- `_VISION_KEY_MAP` in presets/loader.py honors all three vision
  backends with their respective env vars for silent fallback.

### Tests
- 480 unit tests green (was 437 in v0.3.1; +43 v0.4 tests).

## [0.3.1] — 2026-05-11

### Added

- **Russian perplexity support.** `quality/perplexity.py` `_LANG_MODELS` now
  maps `ru` → `sberbank-ai/rugpt3small_based_on_gpt2` (~550 MB lazy
  download). Calibration constants (50 baseline / 150 divisor) shared
  with English — may need per-language tuning on real data.
- **README v0.3 documentation.** New `Batch power-flags (v0.3)` section
  with examples for `--since/--until/--min-duration/--max-duration/--no-shorts`,
  `--skip-existing`, `--workers N`, `--search "query"`, plus a flag
  reference table.

### Fixed

- `test_version_bumped` was hard-coded to `0.2.` prefix — fails on
  every minor bump. Now uses `int(major) >= 0 and int(minor) >= 2`.

### Tests
- 437 unit tests green (was 434 in v0.3.0; +3 Russian-perplexity tests).

## [0.3.0] — 2026-05-11

Major batch features.

### Added

- **`--since YYYY-MM-DD` / `--until YYYY-MM-DD`** — filter channel/playlist/search
  results by upload date.
- **`--min-duration SECONDS` / `--max-duration SECONDS`** — filter by duration.
- **`--no-shorts`** — skip YouTube Shorts (videos ≤ 60s heuristic).
- **`--skip-existing`** — skip videos already transcribed in `output_dir`
  (rglob `*.txt`, dedup by video_id suffix). Useful for incremental
  channel re-fetches.
- **`--workers N`** — parallel batch processing via ThreadPoolExecutor.
  Cloud backends benefit; whisper-local saturates serially. Output may
  interleave; incompatible with `--fail-fast`.
- **`--search "query"`** — YouTube search via yt-dlp `ytsearchN:`. No API
  key needed. Combines with inline URLs / `--from-file` if also set.

### Changed

- `ResolverFilters` gained `search_query` field; `Source` Literal
  extended with `"search"`.

### Tests

- 434 unit tests green (was 402 in v0.2.2; +32 v0.3 tests).

## [0.2.2] — 2026-05-11

### Real-validation fixes (v0.2.1 features broken under live testing)

- **Frame_diff dropped strong-signal windows.** LLM-classifier returned
  a valid window for an elephant zoo video (`score=0.9, "elephants visual"`),
  but `refine_with_frame_diff` dropped it as static talking-head. Same
  applied to user-defined raw / strict triggers — explicit intent that
  shouldn't be overridden by perceptual hashing. Now refinement skips
  windows whose `reason` starts with `raw` / `strict:` / `llm_full_pass:`.

- **Perplexity brick was non-functional.** `lmppl 0.3.x` is incompatible
  with current `transformers` (uses deprecated `use_auth_token` kwarg →
  `TypeError` at LM init). Replaced with direct `transformers` usage
  (already pulled by sentence-transformers). `[perplexity]` extra is now
  a no-op marker.
- **Perplexity score recalibration.** Old formula `mean_ppl / 500` barely
  fired even on garbled text. New: `max((mean_ppl - 50) / 150, 0)` capped
  at 1.0. Normal English speech (PPL 30-80) → ~0 penalty. PPL 125 → 0.5.
  PPL 200+ → 1.0 saturated.

### Polish

- **Aho-Corasick automaton caching.** Previously rebuilt on every
  `match_segment` call — 1500-segment video = 1500 × C-level
  `make_automaton()`. Now cached via `lru_cache(maxsize=16)` by
  hashable `(phrase, weight)` tuple. Identical phrase sets across
  configs share the same automaton.

- **Bag-of-Hallucinations expanded** from 22 to 59 phrases. Added more
  Whisper-typical loops ("turn on notifications", "ring the bell",
  "amara.org", "yandex subtitles", "auto-generated by"), more Russian
  goodbye patterns (kept verbatim because they are detection-list
  samples), and "subscribe + ring bell" variants.

### Tests
- 402 unit tests green (was 393 in v0.2.1; +7 cache tests).

## [0.2.1] — 2026-05-11

### Closed Important issues from final code review of v0.2.0

- **Step 1**: `keywords_only` / `semantic` / `hybrid` / `llm_full_pass`
  are now actually distinct. `match_segment` accepts a `mode=` kwarg.
  `keywords_only` no longer loads the 118MB MiniLM model — saves memory
  on pure-keyword runs.
- **Step 2**: `detect_frame_changes_in_window` integrated into the
  pipeline. In `hybrid`/`llm_full_pass`, empty (talking-head) windows
  are dropped; visually-rich windows get a score boost of ×1.3.
- **Step 3**: `llm_full_pass` now runs a real LLM classify pass. One
  text-only Gemini call per video, parses JSON timecodes, returns up to
  10 windows with `reason="llm_full_pass:<why>"`.
- **Step 4**: brick F (perplexity) implemented. Replaced `kenlm` with
  `lmppl` (uses transformers, already pulled in via
  sentence-transformers). English via GPT-2 small. Penalty in score up
  to 0.25 for fully anomalous text. Opt-in via
  `enable_perplexity=True` (or `quality_perplexity=true` in presets).

### Changed
- `[project.optional-dependencies] perplexity` now requires
  `lmppl>=0.3.0` instead of `kenlm>=0.2.0`. KenLM required pre-built
  ARPA models (impractical for end users).

### Tests
- 390 unit tests green (was 346 in v0.2.0; +44 tests).

## [0.2.0] — 2026-05-11

### Added
- Visual mode (`--with-visuals`) — multimodal video analysis via Gemini
  (frames + audio). Embedded screenshots in combined.md.
- Quality check for transcripts (smart mode picks between
  ready-made subtitles and whisper automatically).
- Multilingual triggers via local embeddings (paraphrase-multilingual-MiniLM-L12-v2).
- Triggers CLI tool: `triggers init/add/list/remove/reset/edit/test/weight`.
- Dynamic presets (eco/smart/standard/premium) backed by a single
  options registry.
- `--config` flag for alternative config files.
- `--ocr` opt-in flag for OCR on keyframes.

### Changed
- `BatchVideoStatus` extended with `quality` and `visual_segments` fields.
- `manifest.json` now includes a quality breakdown and visual_segments.
- `combined.md` contains a `### Visual moments` section with inline screenshots.

### Migration v0.1.x → v0.2
- Auto-migration of an existing `~/.neurolearn/config.toml` into
  the `[presets.custom_legacy]` shape, preserving every user setting.
- When `GEMINI_API_KEY` is set, visual mode is silently enabled in
  the smart preset. Otherwise behaviour is fully v0.1-compatible.

### Dependencies (new)
- core: pyspellchecker, pyahocorasick, langdetect, sentence-transformers,
  lemminflect, pymorphy3, tomlkit, scenedetect, imagehash
- optional: pytesseract+easyocr (extra `ocr`), kenlm (extra `perplexity`)

---

## [v0.1.1] — 2026-05-09 (planned hotfix)

### Fixed
- **`resolver.resolve()` now collect-and-continue per spec §5.** Previously raised `UnresolvableInput` on the first inline URL probe failure, aborting the whole batch. Now returns `(targets, failures)` tuple — bad URLs are logged in `errors.log` (stage `resolve`), good URLs continue. Both `transcribe` (single) and `batch` sub-commands updated.
- **`wizard.py` API key prompt now hides input** (`password=True`). Previously the entered key echoed visibly to the terminal.
- **PEP 508 marker for `faster-whisper`** uses de-Morgan form `sys_platform != 'darwin' or platform_machine != 'arm64'` (hatchling rejects `not (...)` syntax).
- **`packages = ["skills"]`** in `[tool.hatch.build.targets.wheel]` so editable install resolves `skills.neurolearn.*` correctly. Without this fix the entry-point script failed with `ModuleNotFoundError`.
- **`config.save_config` is atomic** (write-temp-then-rename) so a killed process doesn't leave a truncated TOML file.
- **`config.set_api_key` rejects `\n`/`\r` in values** to prevent newline-injection into `.env`.
- **`config.load_config` wraps malformed TOML errors** into a friendly `ValueError` pointing at the wizard.
- **`downloader.download_audio` checks `yt-dlp` BEFORE `mkdir`** so a missing binary doesn't leave debris.
- **`downloader._extract_flat` wraps `yt_dlp.utils.DownloadError`** into our own `DownloadError` so callers don't deal with foreign exception types.

### Updated
- **`google-genai>=1.0.0`** (was `>=0.3.0`). The 0.x API was unstable; our backend uses the GA `Client`/`files.upload`/`models.generate_content` pattern.
- **`deepgram-sdk>=7.0.0`** (was `>=3.7.0`). The 7.x API rewrote the request path; older versions are no longer compatible with `backends/deepgram.py`.

### Known issues / backlog
- `batch` exits 0 even when some videos fail. Smart-mode would prefer non-zero exit if `failures > 0` while at least one video succeeded; v0.2.
- Boundary tests deferred: 6144 MB VRAM (NVIDIA threshold), `parse_yt_date` malformed inputs, `_fmt_duration` ≥1 hour branch.
- `_BareURLGroup` works in `uv run`; not yet validated for `uv tool install` from scratch.
- Cloud backends (gemini, groq, openai, deepgram, assemblyai, custom) are tested via mocks only — no live API call has been exercised in CI yet.

---

## [v0.1.0] — 2026-05-09

First public release.

### Architecture
- 8 interchangeable backends behind a single `Transcriber` Protocol:
  - `subtitles` — youtube-transcript-api 1.x (instance API).
  - `whisper-local` — `mlx-whisper` on macOS arm64, `faster-whisper` everywhere else (auto-selected by `platform_detect`).
  - `gemini` — Google AI Studio (google-genai 2.x).
  - `groq` — Groq Whisper API.
  - `openai` — OpenAI Whisper API.
  - `deepgram` — Deepgram Nova-3 (sdk 7.x), word-level → segment grouping.
  - `assemblyai` — AssemblyAI (`best`/`nano`), ms→s conversion.
  - `custom` — generic OpenAI-compatible endpoint.
- `smart` is a composition (subtitles fast-path → fallback), not a backend.
- `Resolver` translates inline URLs / channel-URLs / `--from-file` lists into `ResolvedTarget`s with dedup by `video_id`.
- Single (`transcribe`) and batch (`batch`) sub-commands share a single `run_pipeline()` core (single = batch of 1).
- Bare-URL routing: `neurolearn https://youtu.be/X` lands on `transcribe` via `_BareURLGroup`.

### Output
- Single: `<output-dir>/<slug>_<id>.txt` (with timestamps) + `.srt`.
- Batch: `<output-dir>/batch_<timestamp>_<slug>/{combined.md, manifest.json, videos/, errors.log?}`.
- `combined.md` has YAML frontmatter + per-video sections (flat text, no timestamps) — designed to be read by Claude in a chat.

### Distribution
- Three install paths: Claude Code plugin, personal skill folder, `uv tool install`.
- `install.ps1` (Windows) and `install.sh` (Mac/Linux) bootstrap fallback if `uv` is missing.

### Privacy
- `whisper-local` and `subtitles` never send audio to third parties.
- API keys live in `~/.neurolearn/.env` (mode `0600` on Unix); they are never echoed back unmasked.

### Tests
- 207 unit tests + 2 e2e smoke tests gated by `RUN_E2E_SMOKE=1`.
- mlx-whisper validated end-to-end on a real 19-second public-domain YouTube video on M-series.
