# Changelog

All notable changes to youtube-transcribe will be documented here.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com/).

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
