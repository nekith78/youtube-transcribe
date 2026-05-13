---
name: youtube-transcribe
description: |
  Transcribe YouTube / Instagram / TikTok / local-file videos via 8 interchangeable backends
  (local Whisper, YouTube subtitles, Gemini, Groq, OpenAI Whisper API, Deepgram, AssemblyAI,
  OpenAI-compatible custom). Also: RESEARCH a topic ("найди свежие видео по теме X" →
  finds, transcribes, returns), SUBSCRIBES to channels ("следи за этими каналами" → RSS
  watch + transcribe new uploads), HISTORY of past runs.
  Use this skill when the user pastes a video URL with intent to read/analyze content,
  asks to "transcribe", "расшифровать", "сделать текст из видео", "розшифрувати",
  "get a transcript", "subtitles", "what's in this video", "о чём это видео";
  asks to find/research videos by topic ("найди видео про X", "сделай ресерч по теме",
  "что нового про Claude features", "research AI agents this week");
  asks to follow a channel ("подпишись на канал X", "следи за @AnthropicAI",
  "что нового на этом канале", "watch this channel for new videos");
  provides a YouTube channel/playlist URL ("весь канал", "последние N видео", "вот плейлист");
  or provides a local media file. Use for explicit backend switching ("через gemini",
  "локально whisper large", "use groq").
  DO NOT use for: general questions about transcription technology, requesting video
  recommendations without source URLs, recording/creating videos, or operating on
  already-existing transcripts.
  Works in Russian, English, Ukrainian, Kazakh, German, Spanish, French.
---

# youtube-transcribe Skill

## Trigger conditions

**Use this skill when** any of these are true in the user's message:

### Single (one input)
- A YouTube URL (`youtube.com/watch?v=...`, `youtu.be/...`, `youtube.com/shorts/...`) appears, with or without surrounding words.
- Any video URL (TikTok, Vimeo, Twitter/X video, Twitch VOD, etc.) appears with intent to extract content.
- A local file path ending in `.mp3 / .mp4 / .wav / .m4a / .mkv / .webm / .opus / .flac` appears with intent to extract speech.
- Direct request: "транскрибируй", "расшифруй", "сделай текст", "transcribe", "get transcript", "розшифруй", "yazıya geçir".
- Request for subtitles: ".srt", "сделай субтитры", "make subtitles", "give me subs".
- Content-question about a linked video: "о чём это видео", "what's in this video", "что говорят".
- Request to summarize/analyze a video by URL (transcribe first, then Claude analyzes).
- Request for timestamps, quotes, or time-coded references in a video.
- Backend switching: "через gemini", "локально whisper", "use groq", "switch to subtitles".

### Batch (multiple inputs)
- The message contains **2 or more YouTube/video URLs**.
- A YouTube channel URL (`youtube.com/@name`, `youtube.com/c/...`, `youtube.com/channel/UC...`).
- A YouTube playlist URL (`youtube.com/playlist?list=...`).
- Phrases: "прогони пачку видео", "расшифруй все эти ссылки", "вот несколько ссылок", "несколько видео разом".
- Phrases: "весь канал", "последние N видео с канала", "all videos from this channel", "все видео с @channel".
- Phrases: "возьми этот плейлист", "всё из этого плейлиста", "the whole playlist".
- A path to a `.txt` file containing URLs ("вот файл со ссылками").

### Research (find videos by topic — no URL provided)
- Phrases: "найди видео про X", "найди ролики по теме", "сделай ресерч по X",
  "что нового про Claude features", "research AI agents this week",
  "что говорят про <тема> в этом месяце", "find recent videos about X".
- The user wants Claude to discover videos on a topic. NO URL is given.
- Optional language hints: "только на русском", "ru + en", "за неделю", "за месяц",
  "топ-10", "первые 5".

### Subscribes (channel watch — follow uploads over time)
- Phrases: "подпишись на канал X", "следи за этим каналом", "watch this channel",
  "subscribe to @name", "что нового на канале X", "проверь подписки",
  "обнови подписки", "update subscriptions", "новые видео с моих каналов".
- The user provides a channel URL/handle and wants automatic follow-up over time.
- Group-based phrasing: "канал в группу AI", "all AI channels", "subscribes group ai-research".

**Do NOT use this skill when:**

- The chat already contains a transcript and the user is asking about the *text* (not the source).
- The question is conceptual: "what is whisper", "how does transcription work", "compare models".
- The user wants a *recommendation* of a video (no source URL provided).
- The user wants to *create*, *record*, or *edit* video content.
- The user is asking about installing/configuring this skill itself ("how do I install", "show me your code").

## Languages

The description above is multilingual on purpose. Triggering happens by semantic match — Russian, English, Ukrainian, Kazakh, German, Spanish, French phrasings all work. Always pass `--language ru` (or whatever the user's language is) explicitly when you can detect it; otherwise omit and let Whisper auto-detect.

## How to invoke

Run the CLI from the user's shell. The CLI is installed globally (Claude Code plugin path or `uv tool install`).

### Single

```
youtube-transcribe transcribe <URL_or_path> [flags]
```

A bare `youtube-transcribe <URL>` (no sub-command) is also accepted for back-compat — it routes to `transcribe`.

### Batch

```
youtube-transcribe batch <URL1> <URL2> ... [--limit N] [flags]
youtube-transcribe batch <channel-or-playlist-URL> --limit 10 [flags]
youtube-transcribe batch --from-file urls.txt [flags]
```

**Recommendation for big channels:** add `--backend subtitles` for the whole batch. A 50-video channel through `whisper-local` takes hours; through subtitles it's a couple of minutes. Quality is "what YouTube auto-recognized" — but enough for a summary/note. If subtitles fail on a video, individual fallback is up to the user (not the skill in v0.1).

### Research (find videos by topic)

```
youtube-transcribe research "<query>" [--languages ru,en] [--days 30] [--limit 20] \
    [--match "substring"] [--filter "LLM-вопрос для пре-скрининга"] \
    [--backend subtitles] [--no-analyze] [--yes] [--output-dir <path>]
```

**Default behavior:** search YouTube via the user's query (translated to each language
in `--languages` if multi-lang), filter by date (`--days N` → uses YouTube's built-in
`sp=` filter for 1d/1w/1mo/1y presets, falls back to client-side refine), dedupe by
video_id, transcribe with the chosen backend, write to `<output-dir>/research_<auto-slug>/`.

**Critical for Claude:** ALWAYS pass `--no-analyze` when invoking `research` from chat.
You are the LLM that will analyze the transcripts — there is no point routing them
through Gemini/Claude/OpenAI via the CLI's `--analyze-backend`. After the command
returns, read `<batch_dir>/combined.md` yourself and answer the user's actual question.

### Subscribes (channel watch + incremental update)

```
youtube-transcribe subscribes add "<channel-url>" [--group <name>]
youtube-transcribe subscribes list [--group <name>]
youtube-transcribe subscribes remove "<channel-url-or-handle>"
youtube-transcribe subscribes edit
youtube-transcribe subscribes update [--group <name>] [--days N] [--no-rss] \
    [--match "..."] [--filter "..."] [--no-analyze] [--yes] [--output-dir <path>]
youtube-transcribe subscribes schedule install [--every 1d] [--platform auto]
youtube-transcribe subscribes schedule uninstall
```

**Add a channel:** stores in `~/.youtube-transcribe/subscribes.toml`. Resolves
`@handle` URLs to stable `channel_id` once at add-time, so subsequent updates
don't need to re-resolve. Group is optional — used for `--group` filtering later.

**Update flow:** for each channel, fetch its YouTube RSS feed (fast), filter to
videos newer than `last_seen_published`, transcribe, write to a fresh batch dir.
After successful run, advance `last_seen_*` so the next `update` is incremental.
On first run for a channel, `--days N` or `--since YYYY-MM-DD` is required to
bootstrap the window.

**Critical for Claude:** same rule as research — ALWAYS pass `--no-analyze` and
read `combined.md` yourself in chat. Do not pipe through `--analyze-backend`.

### History (past runs)

```
youtube-transcribe history list [--last N] [--type research|subscribes]
youtube-transcribe history show <run-id>
```

IDs have the form `r-MMDD-HHMMSS` (research) or `s-MMDD-HHMMSS` (subscribes). The
full timestamp is also in the `When` column. Reading `history show <id>` returns
the original query, output path, prompt preview, and status — handy when the user
asks "что я делал на прошлой неделе" or "open the AI agents research I ran".

### Analyze (post-hoc on already-transcribed batch)

```
youtube-transcribe analyze --latest --all --prompt "..." --backend gemini
youtube-transcribe analyze --batch <batch_dir> --select "1,3,5-7" --prompt-file p.md
```

Used after a transcription run if you want one LLM pass over selected transcripts.
Most Claude-in-chat flows don't need this — just read `combined.md` directly.

### Default behavior

- No flags → uses configured default backend (usually `whisper-local`).
- First-run automatically launches `wizard` (interactive setup).
- Single output: `./transcripts/<name>.txt` and `<name>.srt`.
- Batch output: `./transcripts/batch_<timestamp>_<auto-slug>/` with `videos/`, `combined.md`, `manifest.json`, optional `errors.log`.

### Backend switching (3 levels)

**Per-call** — when the user explicitly mentions a backend in their message, add `--backend <name>`:

| User says | Append to command |
|---|---|
| «через gemini», "use gemini" | `--backend gemini` |
| «через groq», "use groq" | `--backend groq` |
| «локально whisper large» | `--backend whisper-local --whisper-model large` |
| «возьми субтитры», "use subtitles" | `--backend subtitles` |
| «через openai» | `--backend openai` |
| «deepgram», "use Nova-3" | `--backend deepgram` |
| «assemblyai» | `--backend assemblyai` |
| «через custom», "use my custom api" | `--backend custom` |
| «gemini pro» | `--backend gemini --gemini-model gemini-2.5-pro` |

**Session-level** — when the user says "until I say otherwise, use X" or "for this whole conversation use Y", remember the choice and apply `--backend X` to ALL subsequent invocations in this session. Honor it until the user changes it.

**Persistent (changes config file)** — when the user says "переключи дефолт на groq" / "set default to gemini" / "always use whisper-local", run:

```
youtube-transcribe config set backend <name>
```

This writes to `~/.youtube-transcribe/config.toml` and affects all future sessions.

### Other useful sub-commands

- `youtube-transcribe config show` — list current settings + which API keys are configured
- `youtube-transcribe config set-key <backend>` — interactively set an API key
- `youtube-transcribe config test <backend>` — sanity-check a backend's configuration
- `youtube-transcribe config wizard` — re-run the first-run wizard

## Platform support — what works where

| Command | YouTube | Instagram | TikTok | Other yt-dlp sites | Local files |
|---|---|---|---|---|---|
| `transcribe <URL>` / `batch <URL>` | ✓ | ✓ (cookies) | ✓ | ✓ | ✓ |
| `research "query"` | ✓ | ✗ | ✗ | ✗ | n/a |
| `subscribes` | ✓ | ✗ (roadmap) | ✗ (roadmap) | ✗ | n/a |

- **Instagram** requires cookies (register a `cookies.txt` via `yt-tr subscribes cookies set instagram <path>`) —
  IG blocks anonymous requests. Mention this if a user tries an IG URL without cookies.
- **Research** is YouTube-only because `yt-dlp ytsearchN:` only supports YouTube;
  IG/TikTok search via API would require auth tokens.
- **Subscribes** is currently YouTube-only (RSS feeds). Roadmap: IG/TikTok channel
  watching via yt-dlp scrape.

## Analyze backend (when CLI calls an LLM)

The CLI has an optional `--analyze-backend {gemini|claude|openai|ollama}` flag that
runs an LLM pass on the transcripts and writes `analysis-*.md` inside the batch dir.

**From inside Claude Code: you should NOT use it.** You're already the LLM in the
conversation — paying API for a second round-trip is wasteful and slow. Always pass
`--no-analyze` (or omit `--prompt`/`--prompt-file`) when invoking from chat, then
read `combined.md` yourself and answer the user directly.

**Onboarding behavior** (relevant if a user runs the CLI standalone, not via Claude):
on first interactive run without `--analyze-backend`, the CLI prompts once and
persists the choice in `~/.youtube-transcribe/config.toml`. In a non-TTY context
(like Claude Code subprocess), no prompt is shown and analyze is skipped silently —
exactly the behavior we want.

## After running

### After single

Always read the generated `.txt` file and offer the user a short summary or answer their original question (was the URL with "о чём это видео"? answer that). Do NOT echo the entire transcript back unless asked.

### After batch / research / subscribes update

Read the generated `combined.md` from the batch directory printed in stdout. Offer the user one of:
- **Заметка по теме** — extract key insights, group by topic, deduplicate repeated points across videos.
- **Сводка** — short paragraph per video + cross-video themes.
- **План изучения** — ordered reading list with what each video adds.

Use the per-video `source_language` field in `manifest.json` if multi-lang research
(`--languages ru,en`) to group findings by query origin.

Mention the batch directory path so the user can re-open it later. If `errors.log` exists, briefly summarize which videos failed and why.

For `research` runs, the run is also logged to `~/.youtube-transcribe/history.toml`
with an ID `r-MMDD-HHMMSS`. Mention this ID if the user might re-open later.

If the run fails, the CLI prints a friendly hint (yt-dlp blocked → cookies, key missing → set-key, etc.). Relay the hint to the user clearly.

## Privacy note

The default backend (`whisper-local`) processes everything locally — nothing is sent to the network. Cloud backends (gemini, groq, openai, deepgram, assemblyai, custom) DO send the audio to the respective provider. Mention this if the user asks about privacy or seems sensitive about the content.

### combined.md (v0.2)

Если использовался `--with-visuals`, combined.md содержит секцию
`### Visual moments` с встроенными скриншотами и описаниями визуальных
моментов. Это полноценный markdown-туториал — можно использовать как
основу для заметок и планов изучения.

При запросе пользователя «сделай туториал/инструкцию по этому видео»:
1. Используй визуальные моменты как структурные точки.
2. Цитируй timestamps в формате `00:00:45`.
3. Inline-картинки уже встроены — referencing их через relative paths.

При quality < 0.6 (warning в combined.md):
- Транскрипт может содержать ошибки распознавания.
- Скриншоты остаются достоверными.
- Помогай пользователю работать с тем что есть, не отказывайся.
