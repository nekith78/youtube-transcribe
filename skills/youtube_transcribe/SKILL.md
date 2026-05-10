---
name: youtube-transcribe
description: |
  Transcribe YouTube videos (or any yt-dlp-supported URL: TikTok/Vimeo/Twitter/Twitch/etc.)
  and local audio/video files (mp3/mp4/wav/m4a/mkv) via 8 interchangeable backends:
  local Whisper (default, offline, private), YouTube subtitles (instant), Gemini, Groq,
  OpenAI Whisper API, Deepgram, AssemblyAI, or any OpenAI-compatible custom API.
  Use this skill when the user pastes a video URL with intent to read/analyze content,
  asks to "transcribe", "расшифровать", "сделать текст из видео", "розшифрувати",
  "get a transcript", "subtitles", "what's in this video", "о чём это видео",
  or provides a local media file. Also fires for BATCH cases: a list of multiple URLs
  in one message, a YouTube channel/playlist URL ("весь канал", "последние N видео",
  "вот плейлист", "transcribe this whole channel"), or `--from-file` lists.
  Use for explicit backend switching ("через gemini", "локально whisper large", "use groq").
  DO NOT use for: general questions about transcription technology, requesting video
  recommendations, recording/creating videos, or operating on already-existing transcripts.
  Works in Russian, English, Ukrainian, Kazakh, German, Spanish, French — semantic match,
  not regex.
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

## After running

### After single

Always read the generated `.txt` file and offer the user a short summary or answer their original question (was the URL with "о чём это видео"? answer that). Do NOT echo the entire transcript back unless asked.

### After batch

Read the generated `combined.md` from the batch directory printed in stdout. Offer the user one of:
- **Заметка по теме** — extract key insights, group by topic, deduplicate repeated points across videos.
- **Сводка** — short paragraph per video + cross-video themes.
- **План изучения** — ordered reading list with what each video adds.

Mention the batch directory path so the user can re-open it later. If `errors.log` exists, briefly summarize which videos failed and why.

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
