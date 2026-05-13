# Changelog

All notable changes to youtube-transcribe will be documented here.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com/).

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
  registered file at `~/.youtube-transcribe/<platform>-cookies.txt`
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
  binary has always been `youtube-transcribe`; `yt-tr` was never an
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
  subscribes runs in `~/.youtube-transcribe/history.toml`.
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
  `youtube-transcribe batch` preserved byte-for-byte (all 614 v0.6
  tests stay green).

### Dependencies
- No new runtime dependencies. RSS via stdlib `xml.etree.ElementTree`
  + `urllib.request`. Everything else already in v0.2/v0.6 deps.

## [0.6.0] — 2026-05-12

### Added
- `youtube-transcribe analyze [SOURCE]` — free-form LLM analysis over
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

- **`youtube-transcribe summarize <transcript-path>`** — standalone
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
- **Web UI** via Gradio (`youtube-transcribe webui`). URL/file input,
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
  patterns ("спасибо что смотрели", "до новых встреч", "всем пока",
  "напишите в комментариях"), and goodbye variants.

### Tests
- 402 unit tests green (was 393 in v0.2.1; +7 cache tests).

## [0.2.1] — 2026-05-11

### Closed Important issues from final code review of v0.2.0

- **Step 1**: `keywords_only` / `semantic` / `hybrid` / `llm_full_pass` теперь
  по-настоящему различаются. `match_segment` принимает `mode=` kwarg.
  `keywords_only` больше не загружает 118MB MiniLM — экономит память
  на pure-keyword прогонах.
- **Step 2**: `detect_frame_changes_in_window` интегрирован в pipeline.
  В `hybrid`/`llm_full_pass` пустые (talking-head) окна дропаются,
  визуально-богатые окна получают score-boost x1.3.
- **Step 3**: `llm_full_pass` теперь делает реальный LLM-classify pass.
  Один text-only Gemini call на видео, парсит JSON timecodes, возвращает
  до 10 окон с reason="llm_full_pass:<why>".
- **Step 4**: kirpich F (perplexity) реализован. Заменили `kenlm` на
  `lmppl` (использует transformers, уже установлен через
  sentence-transformers). English через GPT-2 small. Penalty в score
  до 0.25 за полностью аномальный текст. Opt-in через
  `enable_perplexity=True` (или `quality_perplexity=true` в presets).

### Changed
- `[project.optional-dependencies] perplexity` теперь требует `lmppl>=0.3.0`
  вместо `kenlm>=0.2.0`. KenLM требовал pre-built ARPA модели
  (непрактично для конечных пользователей).

### Tests
- 390 unit-тестов зелёные (было 346 в v0.2.0; +44 теста).

## [0.2.0] — 2026-05-11

### Added
- Visual mode (`--with-visuals`) — multimodal анализ видео через Gemini
  (фреймы + аудио). Embedded screenshots в combined.md.
- Quality check для транскриптов (smart-режим автоматически выбирает между
  готовыми субтитрами и whisper).
- Multilingual triggers через локальные embeddings (paraphrase-multilingual-MiniLM-L12-v2).
- Triggers CLI tool: `triggers init/add/list/remove/reset/edit/test/weight`.
- Dynamic presets (eco/smart/standard/premium) с единым реестром опций.
- `--config` flag для альтернативных config-файлов.
- `--ocr` opt-in флаг для извлечения текста с keyframes.

### Changed
- `BatchVideoStatus` расширен полями `quality` и `visual_segments`.
- `manifest.json` теперь содержит quality breakdown и visual_segments.
- `combined.md` содержит секцию `### Visual moments` с inline-скриншотами.

### Migration v0.1.x → v0.2
- Auto-migration существующего `~/.youtube-transcribe/config.toml` в формат
  `[presets.custom_legacy]` с сохранением всех настроек пользователя.
- Если есть `GEMINI_API_KEY` → visual mode silent-on в smart-преcете. Иначе
  поведение полностью совместимо с v0.1.

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
- **`packages = ["skills"]`** in `[tool.hatch.build.targets.wheel]` so editable install resolves `skills.youtube_transcribe.*` correctly. Without this fix the entry-point script failed with `ModuleNotFoundError`.
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
- Bare-URL routing: `youtube-transcribe https://youtu.be/X` lands on `transcribe` via `_BareURLGroup`.

### Output
- Single: `<output-dir>/<slug>_<id>.txt` (with timestamps) + `.srt`.
- Batch: `<output-dir>/batch_<timestamp>_<slug>/{combined.md, manifest.json, videos/, errors.log?}`.
- `combined.md` has YAML frontmatter + per-video sections (flat text, no timestamps) — designed to be read by Claude in a chat.

### Distribution
- Three install paths: Claude Code plugin, personal skill folder, `uv tool install`.
- `install.ps1` (Windows) and `install.sh` (Mac/Linux) bootstrap fallback if `uv` is missing.

### Privacy
- `whisper-local` and `subtitles` never send audio to third parties.
- API keys live in `~/.youtube-transcribe/.env` (mode `0600` on Unix); they are never echoed back unmasked.

### Tests
- 207 unit tests + 2 e2e smoke tests gated by `RUN_E2E_SMOKE=1`.
- mlx-whisper validated end-to-end on a real 19-second public-domain YouTube video on M-series.
