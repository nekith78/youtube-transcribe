# NEUROLEARN

Universal audio/video transcription — YouTube, Instagram (posts / reels / IGTV), TikTok, Vimeo, Twitter, Twitch, local files. 8 interchangeable backends. Offline-by-default.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code Plugin](https://img.shields.io/badge/Claude_Code-plugin-7C3AED.svg)](#install)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](https://www.python.org/downloads/)

![neurolearn demo](assets/demo.gif)

<sub>Demo regenerated from [`assets/demo.tape`](assets/demo.tape) via [`vhs`](https://github.com/charmbracelet/vhs). No network calls — runs against the bundled `qa-out/v0101-smoke` batch.</sub>

---

## What it does

Pass a video URL or local file → get `.txt` (with/without timestamps) and `.srt`. By default, transcription runs **fully offline** on your machine using Whisper. Cloud backends (Gemini / Groq / OpenAI / Deepgram / AssemblyAI / any OpenAI-compatible) are opt-in.

Works as:
- A **Claude Code skill** — paste a URL in the chat, get analysis.
- A **standalone CLI** — `neurolearn transcribe <URL>` from any terminal.
- A **slash command** in Claude Code — `/transcribe <URL>`.

---

## Status

v0.10.2 — production-ready:

| Feature | Since | State |
|---|---|---|
| 8 transcription backends (subtitles, whisper-local, gemini, groq, openai, deepgram, assemblyai, custom) | v0.1 | Working |
| Smart preset (subtitles fast-path → whisper-local fallback + visual moments) | v0.1 / v0.2 | Working |
| Batch / channel / playlist | v0.1 | Working |
| First-run wizard with hardware auto-detect | v0.1 | Working |
| CLI (`transcribe`, `batch`, `config`) | v0.1 | Working |
| Slash command `/transcribe` | v0.1 | Working |
| macOS Apple Silicon (mlx-whisper) | v0.1 | Working |
| Windows/Linux + NVIDIA (faster-whisper) | v0.1 | Working |
| Visual moments (vision-LLM annotation, keyframes, OCR) | v0.2 | Working |
| Triggers (custom phrases drive visual analysis) | v0.2 | Working |
| Presets (eco / smart / standard / premium) | v0.2 | Working |
| Channel filters (--since/--until, --min/max-duration, --no-shorts, --skip-existing, --workers, --search) | v0.3 | Working |
| ASR correction via LLM (`--correct-asr`) | v0.4 | Working |
| Speaker diarization (`--diarize`, pyannote) | v0.5 | Working |
| `analyze` sub-command — free-form LLM over a batch | v0.6 | Working |
| `research` — find videos by topic on YouTube | v0.7 | Working |
| `subscribes` — channel watch with RSS + incremental update | v0.7 | Working |
| `history` — log past research/subscribes runs | v0.7 | Working |
| YouTube SP date filter (`--days N` → server-side prefilter) | v0.7 | Working |
| `schedule` — cross-OS scheduler snippet generator (cron/launchd/systemd/Task Scheduler) | v0.7 | Working |
| Visual pipeline v2 — per-video-type vision prompts (9 templates, auto-detected) + cost tracking | v0.10 / v0.10.1 | Working |
| `report` — PDF report generation (Jinja2 + WeasyPrint) with TOC, sections, embedded keyframes | v0.10.2 | Working |
| Web UI (Gradio) | v0.4 | **Experimental, hidden** — code preserved, not maintained |

---

## Install

### Option A — Claude Code plugin via marketplace (recommended)

Inside Claude Code:

```
/plugin marketplace add nekith78/neurolearn
```

```
/plugin install neurolearn@neurolearn
```

Then in your shell:

```bash
uv sync
```

```bash
neurolearn config wizard
```

To upgrade later: `/plugin update neurolearn` inside Claude Code, then `uv sync` again.

### Option B — Claude Code plugin via manual clone

```bash
git clone https://github.com/nekith78/neurolearn ~/.claude/plugins/neurolearn
cd ~/.claude/plugins/neurolearn
uv sync
```

Then run `neurolearn config wizard` to set up. Reload Claude Code if needed.

### Option C — Personal skill folder

```bash
git clone https://github.com/nekith78/neurolearn /tmp/yt-transcribe
cp -r /tmp/yt-transcribe/skills/neurolearn ~/.claude/skills/
cd ~/.claude/skills/neurolearn && uv sync
```

### Option D — Standalone CLI (no Claude needed)

```bash
uv tool install git+https://github.com/nekith78/neurolearn
```

**No `uv`?** Install it first: `curl -LsSf https://astral.sh/uv/install.sh | sh` (Mac/Linux) or `irm https://astral.sh/uv/install.ps1 | iex` (Windows PowerShell). Alternatively use `pip install git+https://github.com/nekith78/neurolearn` with a regular virtualenv.

**System requirements:**
- Python 3.11+
- `ffmpeg` — required for audio extraction. Install: `brew install ffmpeg` (Mac), `choco install ffmpeg` (Windows), `apt install ffmpeg` (Ubuntu).
- macOS 13.5+ for Apple Silicon path.

**Optional extras:**

```bash
uv sync --extra instagram       # instaloader fallback for IG profile listing when yt-dlp's extractor is broken upstream
uv sync --extra diarization     # pyannote.audio for speaker labels (HF token + model license required)
uv sync --extra webui           # Gradio web UI
uv sync --extra ocr             # OCR on keyframes (pytesseract + easyocr)
uv sync --extra dev             # pytest, coverage
```

---

## Quick start

```bash
# Interactive — run the command, then paste the URL when prompted
neurolearn transcribe --language en
# → "Paste URL or file path:"  <paste & Enter>

# Or pass URL inline (good for scripts):
neurolearn transcribe https://youtu.be/dQw4w9WgXcQ --language en

# Fastest: pull YouTube's own subtitles (no GPU needed)
neurolearn transcribe https://youtu.be/dQw4w9WgXcQ --backend subtitles

# Use cloud backend
neurolearn transcribe video.mp4 --backend gemini

# Local file
neurolearn transcribe /path/to/lecture.mp4 --language ru

# In Claude chat
"Transcribe this: https://youtu.be/abc"
"Use gemini for this one: <URL>"
"Run through groq and write a short summary"

# Slash command
/transcribe https://youtu.be/xyz
```

Output goes to `./transcripts/` — one `.txt` (plain text with timestamps) and one `.srt` per video.

### Progress UI (v0.8)

Single-video `transcribe` shows a spinner with stage labels while it works:

```
⠋ Downloading audio...
⠙ Transcribing via gemini...
⠹ Post-processing...
✓ gemini | language=en | duration=58.8s
```

Modes:
- **Default** — rich.status spinner. Compact, non-disruptive.
- **`--verbose`** — spinner OFF; raw yt-dlp / SDK output + dim stage
  lines (`· Downloading audio...`). Use for debugging.
- **Non-TTY** (pipe, CI, Claude Code subprocess) — auto-degrades to
  plain text writes.

`batch`, `research`, `subscribes update` use a per-video `rich.Progress`
bar with `ok=N fail=M` counters (different UI, same idea — you always
see the pipeline is alive).

### FAQ: "HF_TOKEN" warning on first run

You may see:

```
Warning: You are sending unauthenticated requests to the HF Hub.
Please set a HF_TOKEN to enable higher rate limits and faster downloads.
```

`sentence-transformers` (used for trigger-phrase detection) downloads
its model from Hugging Face on first run. Anonymous downloads work fine
but with rate limits. The warning is harmless — it does not stop
transcription. Two ways to silence it:

1. **Ignore** — the model is cached after first run; the warning
   never affects output.
2. **Register a free token** — make an account at
   [huggingface.co](https://huggingface.co), Settings → Access Tokens
   → New token (read-only), then add to `~/.neurolearn/.env`:
   ```
   HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxx
   ```

---

## Visual mode (v0.2)

Pass `--with-visuals` to get a transcript plus a description of the
key visual moments with embedded screenshots in `combined.md`. Useful
for tutorial videos: you get a markdown walkthrough with pictures.

```bash
neurolearn https://youtube.com/watch?v=... --with-visuals
```

Requires `GEMINI_API_KEY` (free tier ~1500 RPD is enough for ~75
videos/day). If the key isn't set, visual analysis is silently
disabled and you get a plain transcript.

### Triggers — control where visual analysis fires

```bash
# Create a user triggers.toml
neurolearn triggers init

# Add phrases (separator: ;)
neurolearn triggers add --universal "look here; for example; demo"

# Per-language strict (exact match)
neurolearn triggers add --strict --lang ru "баг; PR"

# Bump the weight of an important phrase
neurolearn triggers weight set --universal "function" 1.5

# Check which triggers fire on a specific phrase
neurolearn triggers test "look at this code right here"
```

### Presets

A preset bundles several settings (transcribe backend, fallback, visual analysis,
keyframe detection, quality check) under one name. Pick with `--preset <name>` or
set `default_preset` in `~/.neurolearn/config.toml`.

| Preset | Transcribe | Quality check | Vision (visual moments) | Detection method |
|---|---|---|---|---|
| `eco` | subtitles → fallback | off | off | keywords only |
| `smart` (default) | subtitles → quality check → fallback | on | gemini | hybrid |
| `standard` | whisper-local | on | gemini | hybrid |
| `premium` | whisper-large | on | gemini | LLM full pass |

**Heads-up about `smart`:** it enables Gemini visual analysis by default
(`vision_backend = "gemini"`). If you don't want any cloud calls, pick `eco`
explicitly or set `vision_backend = "off"` in your config. The `smart`
preset trades a small Gemini cost for cross-referenced keyframes + visual
context in `combined.md`.

```bash
neurolearn URL --preset eco              # nothing leaves the machine
neurolearn URL --preset standard         # whisper-local + visual moments
neurolearn URL --preset smart --frames-per-window 5
```

---

## Batch / channels

Transcribe a list of URLs, a whole channel, or a playlist with one
command. The skill writes everything to a single directory
(`combined.md` + `manifest.json` + `videos/`) which Claude in chat then
reads end-to-end and turns into a note or summary.

```bash
# Interactive — paste URLs one per line, empty line to finish
neurolearn batch
# → "Paste URLs (one per line, empty line to finish):"
#    > https://youtu.be/AAA
#    > https://youtu.be/BBB
#    > <Enter>

# Inline (good for scripts):
neurolearn batch https://youtu.be/AAA https://youtu.be/BBB

# Whole channel (top-10 recent videos), fast path via YouTube subtitles
neurolearn batch https://youtube.com/@anthropicai --limit 10 --backend subtitles

# From a file (1 URL per line, # — comment)
neurolearn batch --from-file ~/learn/claude-videos.txt --backend gemini

# Playlist, 5 videos via local Whisper
neurolearn batch https://youtube.com/playlist?list=PLxxx --limit 5 \
    --backend whisper-local --whisper-model turbo
```

**Defaults:** `--limit 10`, sequential (not parallel), `continue-on-error`
(if one video fails, the remaining 9 still run). Stop on first failure
with `--fail-fast`.

**Output layout:**

```
./transcripts/batch_2026-05-09_15-30-12_anthropicai/
├── combined.md       ← one file with all transcripts + metadata (for Claude chat)
├── manifest.json     ← machine-readable copy
├── videos/           ← per-video .txt + .srt
└── errors.log        ← only if at least one video failed
```

> **Tip for big channels:** add `--backend subtitles`. 50 videos × subtitles
> ≈ 1 minute, vs ~2 hours on whisper-local. Quality is whatever YouTube
> auto-recognized — usually good enough for a summary.

**From Claude chat:**

```
"Pull the latest 10 videos from @anthropicai via subtitles and write a topic summary"
```

Claude will invoke `batch --limit 10 --backend subtitles`, read
`combined.md`, and write the summary. The skill itself **does not**
produce a summary — that's the LLM's job once `combined.md` is ready.

### Batch power-flags (v0.3)

```bash
# Channel filters — date and duration window
neurolearn batch https://youtube.com/@anthropicai \
    --since 2026-01-01 --until 2026-12-31 \
    --min-duration 300 --max-duration 3600 \
    --no-shorts --limit 20

# Incremental re-fetch: skip videos already transcribed
neurolearn batch https://youtube.com/@anthropicai --skip-existing --limit 50

# Run 4 videos in parallel (useful for cloud backends with large RPM
# budgets; whisper-local won't gain — CPU/GPU bound)
neurolearn batch <playlist> --workers 4 --backend gemini

# Search YouTube by topic — no API key needed
neurolearn batch --search "claude code tutorial" --limit 10

# Combination: search + filters + parallelism
neurolearn batch --search "transformer architecture" \
    --since 2025-01-01 --no-shorts --min-duration 600 \
    --limit 20 --workers 4 --backend gemini --with-visuals
```

| Flag | Meaning |
|---|---|
| `--since YYYY-MM-DD` | Only videos uploaded on or after this date |
| `--until YYYY-MM-DD` | Only videos uploaded on or before this date |
| `--min-duration N` / `--max-duration N` | Filter by duration in seconds |
| `--no-shorts` | Skip YouTube Shorts (≤60s) |
| `--skip-existing` | Don't re-transcribe a video if `_<video_id>.txt` already exists under `output-dir` |
| `--workers N` | Process N videos in parallel; incompatible with `--fail-fast` |
| `--search "query"` | YouTube search via yt-dlp (no API key needed) |

---

## Analyze — free-form LLM analysis over transcripts (v0.6)

The skill produces transcripts; analysis is an explicit second step you
trigger when you want it. `analyze` packages one or more existing
transcripts together with your own free-form prompt and sends them to
the LLM of your choice.

```bash
# Analyze a single transcript
neurolearn analyze ./transcripts/x.txt \
  --prompt "Extract the main argument and counter-examples." \
  --backend gemini

# Analyze the most recent batch (skips picker)
neurolearn analyze --latest \
  --prompt-file my-prompt.md --backend claude

# Pick a subset of videos in a folder interactively
neurolearn analyze ./transcripts/batch_2026-05-11_claude/ \
  --prompt "Compare how each speaker frames the problem." \
  --backend openai

# Append a new analysis block to an existing combined.md
neurolearn analyze --latest \
  --prompt "Now extract every URL mentioned." \
  --append-to ./transcripts/batch_X/notes.md

# Local LLM, no API keys
neurolearn analyze ./transcripts/x.json \
  --prompt "Summarize for a 12-year-old." \
  --backend ollama --ollama-model llama3.2:3b
```

Output is written to `<batch>/analysis-YYYY-MM-DD-HHMM.md` (or rendered
next to the source file for single-file mode), and the response is also
printed to stdout so it's visible inline when invoked from Claude Code.

`batch --then-analyze` chains a batch with an immediate analyze pass:

```bash
neurolearn batch https://www.youtube.com/@channel --limit 5 \
  --backend smart \
  --then-analyze --prompt "Bullet the main takeaways from each video." \
  --analyze-backend gemini
```

---

## Report — PDF generation from a transcribed batch (v0.10.2)

Take any batch produced by `transcribe` / `batch` (with or without
visual moments) and turn it into a structured PDF report: title,
executive summary, table of contents, sectioned content with bullet
key-points, inline timestamps, and embedded keyframes.

```bash
# Install the optional report extra once
uv sync --extra report
# macOS only: brew install pango cairo   # WeasyPrint native deps

# Render from the most-recent batch, ask language interactively
neurolearn report --latest

# Render a specific batch, force tutorial layout, English
neurolearn report ~/.neurolearn/out/<batch_dir>/ \
  --report-type tutorial --report-language en --yes

# Narrow scope with a user filter — keeps only matching sections
neurolearn report --latest \
  --prompt "Only sections about authentication and error handling."

# Text-only (no screenshots), keep the intermediate HTML for inspection
neurolearn report --latest --no-screenshots --keep-html

# Use a local LLM instead of Gemini
neurolearn report --latest --backend ollama --ollama-model qwen3:8b
```

**Three built-in layouts** — auto-picked by re-running the v0.10.1
type detector on the transcript, or pinned with `--report-type`:

- `tutorial` — step-by-step format, imperative section titles, code
  blocks verbatim. Used for tutorial / code / demo videos.
- `vlog` — highlights-only: surfaces moments where the creator
  explicitly shows information (prices, products, on-screen graphics).
  Skips pure narration.
- `generic` — section-by-section outline by topic shifts. Fallback
  for anything else.

**Custom prompts** override the built-in per-type templates the same
way vision prompts do in v0.10.1:

```toml
# ~/.neurolearn/report_prompts.toml
[global]
prefix = "Always reply in concise English. Use [HH:MM:SS] for timestamps."

[prompts.tutorial]
prompt = "Step-by-step layout, but always end with a 'Common pitfalls' section."
append_global = true

# Brand-new custom type
[prompts.cooking-recipe]
prompt = "Extract ingredients, steps, timings. Keep measurements verbatim."
append_global = false
```

Then `neurolearn report --latest --report-type cooking-recipe`.

Long videos (>~15k transcript tokens) automatically switch to a
hierarchical chunk-then-assemble pass — per-chunk outlines feed a
final assembly call for a top-level title + executive summary.

---

## Research a topic (v0.7)

Discover and analyze new videos on a topic in one command. YouTube
ranking decides relevance, you decide period + analysis angle.

> **About the analyze step.** By default, on the first interactive run
> `research` / `subscribes update` / `batch --then-analyze` asks once
> which LLM to use for the analyze pass (skip / gemini / claude / openai
> / ollama) and persists the choice in `~/.neurolearn/config.toml`.
> Override per-call with `--analyze-backend X`. In a non-TTY context
> (Claude Code subprocess, CI, piped run) the prompt is skipped and the
> analyze pass is silently skipped — `combined.md` is the output and the
> chat-side LLM does the analysis. Force-skip with `--no-analyze`.

```bash
# Interactive — run the command, paste the query when asked
neurolearn research \
  --prompt "Outline the key ideas" \
  --analyze-backend gemini
# → "Enter search query:" <type & Enter>

# Default — last 30 days, ru+en search, top 20 results
neurolearn research "Claude updates" \
  --prompt "Outline the key ideas" \
  --analyze-backend gemini

# Narrower: 7 days, single language, fewer videos
neurolearn research "AI agents 2026" \
  --days 7 --languages en --limit 10 \
  --prompt "Compare design choices"

# Historical: specific window
neurolearn research "LangChain release" \
  --since 2024-06-01 --until 2024-08-31 \
  --prompt "What's new"

# Substring + LLM filter combo
neurolearn research "machine learning" \
  --match "tutorial" --filter "beginner-friendly tutorials" \
  --prompt "What's in common, what's unique"

# Just transcripts, no analyze
neurolearn research "AI news 2026" --no-analyze

# Cross-pollination: only from my subscribed channels
neurolearn research "Claude" --in-subscribes --group ai-research \
  --days 14 --prompt "Recent updates"
```

## Subscribes — channels you follow (v0.7)

```bash
# Add a channel — interactive (run, then paste the URL)
neurolearn subscribes add --group ai
# → "Paste channel URL:"

# Or inline:
neurolearn subscribes add https://www.youtube.com/@anthropic-ai --group ai
neurolearn subscribes add https://www.youtube.com/@lexfridman --group philosophy

# List (optionally by group)
neurolearn subscribes list
neurolearn subscribes list --group ai

# Edit subscribes.toml manually (cross-OS $EDITOR)
neurolearn subscribes edit

# Remove
neurolearn subscribes remove @anthropic-ai

# Update: incremental (stateful per channel)
neurolearn subscribes update --prompt "What was discussed"

# Update: force window
neurolearn subscribes update --days 7 --group ai \
  --filter "only about new models" \
  --prompt "Compare approaches"

# Generate scheduler snippet (no automatic install)
neurolearn subscribes schedule install --every 1h --prompt "your usual prompt"
# → prints launchd/cron/systemd/Task Scheduler snippet + install instructions

# View past runs
neurolearn history list
neurolearn history list --type research --last 5
neurolearn history show <run-id>
```

The `subscribes` store lives at `~/.neurolearn/subscribes.toml`
and is safe to hand-edit; CLI mutations preserve your comments via
`tomlkit`.

### Instagram & TikTok subscribes (v0.8)

Both platforms need cookies (no anonymous access for profile listing):

```bash
# Export cookies.txt from your browser via the
# "Get cookies.txt LOCALLY" extension, then:
neurolearn subscribes cookies set instagram /path/to/ig-cookies.txt
neurolearn subscribes cookies set tiktok    /path/to/tt-cookies.txt
```

Add channels:

```bash
neurolearn subscribes add https://www.instagram.com/natgeo/   --group walk-ig
neurolearn subscribes add https://www.tiktok.com/@anthropic    --group dev
```

Update only one platform at a time:

```bash
neurolearn subscribes update --platform instagram --days 7 \
  --backend whisper-local --yes --no-analyze
```

**Instagram fallback.** yt-dlp's IG profile extractor is periodically
broken upstream. When that happens we automatically fall back to
`instaloader` — install it once:

```bash
uv sync --extra instagram
```

You'll see a one-time per-process warning when the fallback activates,
with rate-limit guidance. It's intended for occasional fetches — IG
will flag accounts that scrape aggressively.

**Cookies are strict file-only.** We deliberately do NOT support
`--cookies-from-browser` — it reads your entire browser cookie store
into process memory. Export the IG/TT cookies you want via a browser
extension and register that single file.

---

## Hardware guide

Pick a backend based on your hardware:

| Hardware | Recommended backend | One hour of video = | Notes |
|---|---|---|---|
| Anything (YouTube subtitles available) | `subtitles` | 2–10 s | Mediocre quality, instant |
| RTX 4090/4080/5090 (16+ GB VRAM) | `whisper-local turbo` | 30–60 s | float16, ideal |
| RTX 4070/3080/4060 Ti (12 GB VRAM) | `whisper-local turbo` | 1–2 min | float16 |
| RTX 3060/4060 (8–12 GB VRAM) | `whisper-local turbo` | 2–4 min | float16 |
| RTX 2060 / GTX 1660 Ti (6 GB VRAM) | `whisper-local turbo` | 5–10 min | int8_float16 |
| GTX 1060/1050 Ti (3–6 GB VRAM) | `whisper-local medium` | 15–30 min | Borderline |
| M3 Max / M4 Pro | `whisper-local turbo` | 30–45 s | mlx-whisper |
| M2 Pro / M3 / M4 | `whisper-local turbo` | 1–2 min | mlx-whisper |
| M1 / M2 base (8 GB) | `whisper-local turbo` | 2–4 min | mlx-whisper |
| CPU only, Ryzen 7 / i7 | `whisper-local small` | 30–45 min | Very slow |
| Weak hardware / no dedicated GPU | `gemini` or `groq` | 30–120 s | Cloud, needs internet + key |

**Recommendation:**
- ✅ Ideal: NVIDIA RTX 30/40/50-series (≥6 GB VRAM) or Apple Silicon M1+.
- 🟡 Fine for short videos: GTX 16-series, older RTX 20-series.
- 🔴 Better to use `subtitles` or `gemini`/`groq`: integrated graphics, laptops without a dedicated GPU.
- ⛔ Avoid `whisper-local`: machines with <8 GB RAM. Use cloud backends.

---

## Backends overview

| Backend | Speed (1 h of video) | Quality | Cost | API key | Sends data over the network |
|---|---|---|---|---|---|
| `subtitles` | 2–10 s | Mediocre (YouTube ASR) | Free | No | No (only a YouTube request) |
| `whisper-local` | 30 s – 45 min (GPU-dependent) | Excellent | Free | No | No (fully offline) |
| `gemini` | 30–120 s | Excellent | Free (flash) / paid (pro) | `GEMINI_API_KEY` | Yes, Google |
| `groq` | 5–20 s | Excellent | Free tier, then paid | `GROQ_API_KEY` | Yes, Groq |
| `openai` | 30–60 s | Excellent | ~$0.006/min of audio | `OPENAI_API_KEY` | Yes, OpenAI |
| `deepgram` | 15–60 s | Excellent + precise timestamps | $200 free start | `DEEPGRAM_API_KEY` | Yes, Deepgram |
| `assemblyai` | 30–90 s | Excellent | Free tier | `ASSEMBLYAI_API_KEY` | Yes, AssemblyAI |
| `custom` | Depends on provider | Depends | Depends | Configurable | Yes, your provider |

**Smart mode** (`--backend smart`, default): tries `subtitles` for
YouTube URLs; if subtitles aren't available it falls back to
`whisper-local`. Automatic, no user input required.

---

## Switching backends in chat (3 levels)

### Level 1 — per-call

Claude sees an explicit backend mention and uses it for one request:

| Phrase in chat | What happens |
|---|---|
| "transcribe this via gemini: &lt;URL&gt;" | `--backend gemini` for this call |
| "run it through groq" | `--backend groq` |
| "local whisper large" | `--backend whisper-local --whisper-model large` |
| "pull the YouTube subtitles" | `--backend subtitles` |
| "gemini, but pro instead of flash" | `--backend gemini --gemini-model gemini-2.5-pro` |

### Level 2 — per-session

"Use groq for the rest of this conversation" — Claude remembers the
choice for the current session and adds the flag to every subsequent
call.

### Level 3 — persistent

Change the default via CLI or from chat:

```bash
neurolearn config show
neurolearn config set backend groq
neurolearn config set whisper-model turbo
neurolearn config set language ru
neurolearn config set-key gemini       # interactive key entry
neurolearn config test groq            # verify the key works
neurolearn config wizard               # re-run the setup wizard
```

From chat: "switch the default to groq" → Claude runs
`neurolearn config set backend groq`.

---

## Common errors

### "Sign in to confirm you're not a bot" (yt-dlp 403)

YouTube periodically updates its anti-bot defences, breaking yt-dlp
for 1–3 months at a time worldwide. **This is not a bug in this tool.**
Fix:

1. `neurolearn update-deps` — pulls the latest yt-dlp release.
2. If that doesn't help — register a cookies file:
   ```bash
   # Install the "Get cookies.txt LOCALLY" extension in any browser
   # (Chrome / Firefox / Edge / Brave — same Netscape cookies.txt format).
   # Open youtube.com (logged in) → click the extension → Export.

   neurolearn config set-cookies ~/Downloads/youtube_cookies.txt
   ```
   After that `transcribe` / `batch` pick up the cookies automatically.
   You can also pass them per-call:
   `neurolearn transcribe <URL> --cookies-file ~/path/file.txt`.
3. If it still doesn't work — open an issue; fixes usually land within
   a few days.

> **Why not `--cookies-from-browser`?** That yt-dlp flag pulls EVERY
> cookie for every domain from your browser store into process memory
> (domain filtering only happens when HTTP requests are sent). It
> violates principle of least privilege. We support ONLY an explicit
> Netscape `cookies.txt` file.

> **Context:** YouTube tightens its protection regularly. You may also
> need the PO Token plugin (`bgutil-ytdlp-pot-provider`) — watch
> [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases).

### Missing API key

```
Error: GEMINI_API_KEY not set. Run: neurolearn config set-key gemini
```

Run `neurolearn config set-key <backend>` — it prompts for the
key interactively and stores it in `~/.neurolearn/.env` with
mode `0600`.

### `distil` model on Mac

```
Error (exit code 4): Model 'distil' is not available on Apple Silicon (mlx-whisper).
Use: turbo, large, medium, or small.
```

`distil-large-v3` is implemented only in `faster-whisper` (Windows/Linux).
On Mac use `turbo` — comparable speed.

### Missing `ffmpeg`

```
Error: ffmpeg not found. Install: brew install ffmpeg (Mac) / choco install ffmpeg (Windows)
```

ffmpeg is required to extract audio from video before transcription.

### CUDA not found / GPU crashes

```bash
neurolearn transcribe <URL> --device cpu --compute-type int8
```

Or switch to a different backend: `subtitles` / `gemini` / `groq`.

### No subtitles on `subtitles` backend

For a video without subtitles (auto or manual) in the requested
language the skill returns an error. In smart mode it falls back to
`whisper-local` automatically.

### Gemini Files API limits

Gemini Files API accepts files up to ~2 GB and videos up to ~1 hour
reliably. For videos > 1 hour use `whisper-local` or `assemblyai`.

---

## Privacy

| Backend | Does audio leave the machine? |
|---|---|
| `whisper-local` | Never |
| `subtitles` | No — but YouTube sees the request |
| `gemini` | Yes, Google |
| `groq` | Yes, Groq |
| `openai` | Yes, OpenAI |
| `deepgram` | Yes, Deepgram |
| `assemblyai` | Yes, AssemblyAI |
| `custom` | Yes, your provider |

API keys are never printed in full to logs — they're masked as
`sk-***...XYZ`. `config show` masks them too.

---

---

## Architecture (for developers)

### Project layout

```
neurolearn/
├── .claude-plugin/
│   └── plugin.json                       # Claude Code plugin metadata
├── skills/
│   └── neurolearn/               # Python package (snake_case)
│       ├── SKILL.md                      # Triggers + rules for Claude
│       ├── transcribe.py                 # CLI entry point
│       ├── wizard.py                     # First-run setup wizard
│       ├── config.py                     # config.toml + .env
│       ├── backends/
│       │   ├── base.py                   # Transcriber Protocol + TranscriptionResult
│       │   ├── subtitles.py
│       │   ├── whisper_local.py          # faster-whisper / mlx-whisper
│       │   ├── gemini.py
│       │   ├── groq.py
│       │   ├── openai_api.py
│       │   ├── deepgram.py
│       │   ├── assemblyai.py
│       │   └── custom.py
│       ├── utils/
│       │   ├── platform_detect.py        # OS/GPU/VRAM auto-detection
│       │   ├── downloader.py             # yt-dlp wrapper
│       │   └── output_writer.py          # .txt + .srt
│       └── tests/
├── commands/
│   └── transcribe.md                     # /transcribe slash command
└── pyproject.toml
```

### Transcriber Protocol

`backends/base.py` defines the contract:

```python
class Transcriber(Protocol):
    name: str
    supports_url: bool          # subtitles — yes, others go through the downloader
    supports_local_file: bool

    def is_configured(self) -> tuple[bool, str | None]:
        """Is the backend ready? Returns (ok, reason_if_not)."""

    def transcribe(
        self, audio_path: Path | str, *, language: str, **opts
    ) -> TranscriptionResult:
        ...

@dataclass
class TranscriptionResult:
    text: str
    segments: list[Segment]        # for .srt and timestamped .txt
    language_detected: str | None
    backend_name: str
    duration_seconds: float
```

All 8 backends are interchangeable implementations of the same
`Transcriber` Protocol. Tests run against the interface; external SDKs
are mocked.

### Smart mode — composition, not a backend

When `default_backend = "smart"`:
1. URL → YouTube? → try `subtitles`.
2. Success → return the result.
3. No subtitles / not YouTube / `--no-fast-path` → use
   `fallback_backend` (default: `whisper-local`).

The logic lives at the top level; backends don't know about each
other.

### Whisper-local — two implementations, one interface

`platform_detect.py` inspects the environment and returns `label` /
`backend_impl` / `device` / `vram`. `whisper_local.py` uses the result
to pick:
- macOS arm64 → `mlx-whisper`
- Windows/Linux + NVIDIA → `faster-whisper` (float16 or int8_float16 depending on VRAM)
- CPU only → `faster-whisper` with `device="cpu"`, `compute_type="int8"`

### Config and secrets

- `~/.neurolearn/config.toml` — settings (TOML).
- `~/.neurolearn/.env` — API keys, mode `0600` on Unix.
- Priority: process env vars > `.env` > error with instructions.

---

## Adding a new backend

1. Create `skills/neurolearn/backends/my_provider.py`.
2. Implement the `Transcriber` Protocol (see `backends/base.py`).
3. Register it in the factory (`backends/__init__.py`):
   ```python
   from .my_provider import MyProviderTranscriber
   REGISTRY["my-provider"] = MyProviderTranscriber
   ```
4. Add to the `--backend` choices in `transcribe.py`.
5. Write a unit test with a mocked SDK in `tests/test_backends.py`.

That's it. The rest of the code (smart mode, output writer, config,
CLI) doesn't change.

---

## Whisper model comparison

| Parameter | `turbo` (default) | `large` | `medium` | `small` | `distil` |
|---|---|---|---|---|---|
| Base model | large-v3-turbo | large-v3 | medium | small | distil-large-v3 |
| VRAM (float16) | ~6 GB | ~10 GB | ~5 GB | ~2 GB | ~6 GB |
| Accuracy | Excellent | Maximum | Good | Mediocre | Excellent (EN) |
| Speed | Fast | Slow | Medium | Very fast | Fastest |
| When to use | Most tasks | Legal / medical recordings | Weak hardware | Drafts | faster-whisper only, EN |
| macOS (mlx) | Yes | Yes | Yes | Yes | No |

---

## Roadmap

**Shipped** (v0.1 → v0.7):
- v0.3 — channel filters (--since/--until/--min/max-duration/--no-shorts), --skip-existing, --workers, --search
- v0.4 — `--correct-asr` (LLM post-processing on low-quality transcripts)
- v0.5 — `--diarize` (pyannote-audio speaker labels)
- v0.6 — `analyze` sub-command, `batch --then-analyze`
- v0.7 — `research`, `subscribes`, `history`, YouTube SP date filter, cross-OS scheduler

**v0.8 (in progress):**
- **Instagram / TikTok subscribes** — `subscribes add` accepts an IG profile
  or TikTok user. Cookies are required (registered via `subscribes cookies set
  <platform> <netscape-cookies.txt>`); we never read browser cookies. For
  Instagram, yt-dlp is primary; when its profile extractor is marked broken
  upstream (which happens periodically), we fall back to **instaloader**
  (`uv sync --extra instagram`). Intended for occasional fetches, not bulk
  scraping — the loader prints a one-time warning per process.
- **Cross-OS scheduler installer** for `subscribes update` (cron / launchd /
  Task Scheduler).

**v0.9 candidates** (not started, ordered by likely value):
- **Chunking videos > 2h** for cloud backends with payload limits.
- **PyPI publication.**
- **Web UI revival** — currently hidden as experimental; if there's demand we'll
  re-do the Gradio tabs properly.

Not planned: search/`research` for Instagram or TikTok (their search is too noisy
to be useful), platforms beyond {YouTube, Instagram, TikTok} for `subscribes`.

---

## For AI agents

If you're an LLM driving this skill, start here:

- [`skills/neurolearn/SKILL.md`](skills/neurolearn/SKILL.md) — when to invoke, which command to pick, the `--no-analyze` rule for chat-driven use.
- [`docs/agent-reference.md`](docs/agent-reference.md) — full CLI surface, file/module map, exit codes, state semantics, how to add a backend.
- [`graphify-out/GRAPH_REPORT.md`](graphify-out/GRAPH_REPORT.md) — top god-nodes, hyperedges (subscribes flow, analyze pipeline, detection pipeline, vision backends), suggested questions.
- [`graphify-out/graph.json`](graphify-out/graph.json) — queryable via `/graphify query "..."`.

---

## License

MIT — see [LICENSE](LICENSE).
