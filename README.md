# youtube-transcribe

Universal audio/video transcription — YouTube, TikTok, Vimeo, Twitter, Twitch, local files. 8 interchangeable backends. Offline-by-default.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## What it does

Pass a video URL or local file → get `.txt` (with/without timestamps) and `.srt`. By default, transcription runs **fully offline** on your machine using Whisper. Cloud backends (Gemini / Groq / OpenAI / Deepgram / AssemblyAI / any OpenAI-compatible) are opt-in.

Works as:
- A **Claude Code skill** — paste a URL in the chat, get analysis.
- A **standalone CLI** — `youtube-transcribe transcribe <URL>` from any terminal.
- A **slash command** in Claude Code — `/transcribe <URL>`.

---

## Status

v0.1 — production-ready core:

| Feature | State |
|---|---|
| 8 backends (subtitles, whisper-local, gemini, groq, openai, deepgram, assemblyai, custom) | Working |
| Smart mode (subtitles fast-path → whisper-local fallback) | Working |
| Batch / channel / playlist | Working |
| First-run wizard with hardware auto-detect | Working |
| CLI (`youtube-transcribe transcribe`, `batch`, `config`) | Working |
| Slash command `/transcribe` | Working |
| macOS Apple Silicon (mlx-whisper) | Tested manually on M-series |
| Windows/Linux + NVIDIA (faster-whisper) | Working |

---

## Install

### Option A — Claude Code plugin (recommended)

```bash
git clone https://github.com/nekith78/youtube-transcribe ~/.claude/plugins/youtube-transcribe
cd ~/.claude/plugins/youtube-transcribe
uv sync
```

Then run `youtube-transcribe config wizard` to set up. Reload Claude Code if needed.

### Option B — Personal skill folder

```bash
git clone https://github.com/nekith78/youtube-transcribe /tmp/yt-transcribe
cp -r /tmp/yt-transcribe/skills/youtube_transcribe ~/.claude/skills/
cd ~/.claude/skills/youtube_transcribe && uv sync
```

### Option C — Standalone CLI (no Claude needed)

```bash
uv tool install git+https://github.com/nekith78/youtube-transcribe
```

**No `uv`?** Install it first: `curl -LsSf https://astral.sh/uv/install.sh | sh` (Mac/Linux) or `irm https://astral.sh/uv/install.ps1 | iex` (Windows PowerShell). Alternatively use `pip install git+https://github.com/nekith78/youtube-transcribe` with a regular virtualenv.

**System requirements:**
- Python 3.11+
- `ffmpeg` — required for audio extraction. Install: `brew install ffmpeg` (Mac), `choco install ffmpeg` (Windows), `apt install ffmpeg` (Ubuntu).
- macOS 13.5+ for Apple Silicon path.

---

## Quick start

```bash
# Default: offline whisper-local
youtube-transcribe transcribe https://youtu.be/dQw4w9WgXcQ --language en

# Fastest: pull YouTube's own subtitles (no GPU needed)
youtube-transcribe transcribe https://youtu.be/dQw4w9WgXcQ --backend subtitles

# Use cloud backend
youtube-transcribe transcribe video.mp4 --backend gemini

# Local file
youtube-transcribe transcribe /path/to/lecture.mp4 --language ru

# In Claude chat
"Расшифруй вот это: https://youtu.be/abc"
"Use gemini for this one: <URL>"
"Прогони через groq и сделай краткое резюме"

# Slash command
/transcribe https://youtu.be/xyz
```

Output goes to `./transcripts/` — one `.txt` (plain text with timestamps) and one `.srt` per video.

---

## Visual mode (v0.2)

Включи `--with-visuals` чтобы получить не только транскрипт, но и описание
визуальных моментов с встроенными скриншотами в `combined.md`. Полезно для
видео-туториалов: получаешь markdown-инструкцию с картинками.

```bash
youtube-transcribe https://youtube.com/watch?v=... --with-visuals
```

Требуется `GEMINI_API_KEY` (free tier ~1500 RPD достаточно для 75 видео/день).
Если ключ не задан — визуальная часть тихо отключается, остаётся обычный
транскрипт.

### Triggers — управление точками визуального анализа

```bash
# Создать пользовательский triggers.toml
youtube-transcribe triggers init

# Добавить фразы (через ;)
youtube-transcribe triggers add --universal "look here; for example; demo"

# Per-language strict (точное совпадение)
youtube-transcribe triggers add --strict --lang ru "баг; PR"

# Поднять вес важной фразы
youtube-transcribe triggers weight set --universal "function" 1.5

# Проверить какие триггеры срабатывают на конкретной фразе
youtube-transcribe triggers test "вот этот код важен"
```

### Presets

| Preset | Transcribe | Vision | Detection |
|---|---|---|---|
| `eco` | subtitles → user-chosen | off | keywords only |
| `smart` (default) | subtitles → quality check → fallback | gemini | hybrid |
| `standard` | whisper-local | gemini | hybrid |
| `premium` | whisper-large | gemini | LLM full pass |

```bash
youtube-transcribe URL --preset standard
youtube-transcribe URL --preset smart --frames-per-window 5
```

---

## Batch / каналы

Прогнать пачку URL, целый канал или плейлист — одной командой. Skill кладёт результат в одну папку (`combined.md` + `manifest.json` + `videos/`), которую дальше Claude в чате читает целиком и делает заметку/сводку.

```bash
# Несколько отдельных URL → один batch
youtube-transcribe batch https://youtu.be/AAA https://youtu.be/BBB

# Целый канал (топ-10 свежих видео), быстрый режим через субтитры YouTube
youtube-transcribe batch https://youtube.com/@anthropicai --limit 10 --backend subtitles

# Из файла со списком (1 URL на строку, # — комментарий)
youtube-transcribe batch --from-file ~/learn/claude-videos.txt --backend gemini

# Плейлист, все 5 видео локальным Whisper
youtube-transcribe batch https://youtube.com/playlist?list=PLxxx --limit 5 \
    --backend whisper-local --whisper-model turbo
```

**Дефолты:** `--limit 10`, последовательно (не параллельно), `continue-on-error` (упало 1 видео — продолжаем оставшиеся 9). Прервать на первой ошибке: `--fail-fast`.

**Структура выхода:**

```
./transcripts/batch_2026-05-09_15-30-12_anthropicai/
├── combined.md       ← один файл со всеми текстами + мета — для Claude-чата
├── manifest.json     ← машиночитаемый дубль
├── videos/           ← per-video .txt + .srt
└── errors.log        ← если были ошибки
```

> **Совет для больших каналов:** добавь `--backend subtitles`. 50 видео × subtitles ≈ 1 минута, против ≈2 часов на whisper-local. Качество — то, что YouTube распознал автоматически, но для заметки/сводки этого обычно достаточно.

**В Claude-чате:**

```
"Скачай последние 10 видео канала @anthropicai через субтитры и сделай сводку тем"
```

Claude запустит `batch --limit 10 --backend subtitles`, прочитает `combined.md` и напишет сводку. Skill сам по себе summary **не делает** — это задача Claude в чате после того, как `combined.md` готов.

> **Что НЕ делает batch в v0.1:** поиск по тегам/теме — v0.3; Instagram — v0.4; параллельный прогон — v0.3. См. roadmap.

---

## Hardware guide

Выбери подходящий бэкенд исходя из железа:

| Железо | Подходящий бэкенд | Час видео = | Комментарий |
|---|---|---|---|
| Любое (есть YouTube-субтитры) | `subtitles` | 2–10 сек | Среднее качество, мгновенно |
| RTX 4090/4080/5090 (16+ GB VRAM) | `whisper-local turbo` | 30–60 сек | float16, идеал |
| RTX 4070/3080/4060 Ti (12 GB VRAM) | `whisper-local turbo` | 1–2 мин | float16 |
| RTX 3060/4060 (8–12 GB VRAM) | `whisper-local turbo` | 2–4 мин | float16 |
| RTX 2060 / GTX 1660 Ti (6 GB VRAM) | `whisper-local turbo` | 5–10 мин | int8_float16 |
| GTX 1060/1050 Ti (3–6 GB VRAM) | `whisper-local medium` | 15–30 мин | На грани |
| M3 Max / M4 Pro | `whisper-local turbo` | 30–45 сек | mlx-whisper |
| M2 Pro / M3 / M4 | `whisper-local turbo` | 1–2 мин | mlx-whisper |
| M1 / M2 base (8 GB) | `whisper-local turbo` | 2–4 мин | mlx-whisper |
| CPU only, Ryzen 7 / i7 | `whisper-local small` | 30–45 мин | Очень медленно |
| Слабое железо / без дискретной GPU | `gemini` или `groq` | 30–120 сек | Облако, нужен интернет + ключ |

**Рекомендация:**
- ✅ Идеально: NVIDIA RTX 30/40/50-серия (≥6 GB VRAM) или Apple Silicon M1+.
- 🟡 Норм для коротких видео: GTX 16-серия, старые RTX 20-серия.
- 🔴 Лучше переключиться на `subtitles` или `gemini`/`groq`: интегрированная графика, ноутбуки без дискретной GPU.
- ⛔ Не ставь `whisper-local`: машины с <8 GB RAM. Используй облачные бэкенды.

---

## Backends overview

| Backend | Скорость (час видео) | Качество | Стоимость | API-ключ | Данные уходят в сеть |
|---|---|---|---|---|---|
| `subtitles` | 2–10 сек | Среднее (YouTube ASR) | Бесплатно | Нет | Нет (только запрос к YouTube) |
| `whisper-local` | 30 сек – 45 мин (зависит от GPU) | Отличное | Бесплатно | Нет | Нет (полностью офлайн) |
| `gemini` | 30–120 сек | Отличное | Бесплатно (flash) / платно (pro) | `GEMINI_API_KEY` | Да, Google |
| `groq` | 5–20 сек | Отличное | Бесплатный tier, затем платно | `GROQ_API_KEY` | Да, Groq |
| `openai` | 30–60 сек | Отличное | ~$0.006/мин аудио | `OPENAI_API_KEY` | Да, OpenAI |
| `deepgram` | 15–60 сек | Отличное + точные таймкоды | $200 бесплатный старт | `DEEPGRAM_API_KEY` | Да, Deepgram |
| `assemblyai` | 30–90 сек | Отличное | Бесплатный tier | `ASSEMBLYAI_API_KEY` | Да, AssemblyAI |
| `custom` | Зависит от провайдера | Зависит | Зависит | Настраивается | Да, ваш провайдер |

**Smart-режим** (`--backend smart`, дефолт): пробует `subtitles` для YouTube-ссылок, если субтитров нет — падает на `whisper-local`. Автоматически, без участия пользователя.

---

## Switching backends in chat (3 levels)

### Уровень 1 — разовое (per-call)

Claude видит явное упоминание движка и использует его для одного запроса:

| Фраза в чате | Что происходит |
|---|---|
| «расшифруй это через gemini: &lt;URL&gt;» | `--backend gemini` для этого вызова |
| «прогони через groq» | `--backend groq` |
| «локально whisper large» | `--backend whisper-local --whisper-model large` |
| «возьми субтитры с ютуба» | `--backend subtitles` |
| «gemini, но pro вместо flash» | `--backend gemini --gemini-model gemini-2.5-pro` |

### Уровень 2 — сессионное

«До конца разговора используй groq» — Claude запоминает в рамках сессии и подставляет флаг ко всем последующим вызовам.

### Уровень 3 — постоянное

Меняет дефолт через CLI или из чата:

```bash
youtube-transcribe config show
youtube-transcribe config set backend groq
youtube-transcribe config set whisper-model turbo
youtube-transcribe config set language ru
youtube-transcribe config set-key gemini       # интерактивный ввод ключа
youtube-transcribe config test groq            # проверить, что ключ рабочий
youtube-transcribe config wizard               # перезапустить мастер
```

Из чата: «переключи дефолт на groq» → Claude дёргает `youtube-transcribe config set backend groq`.

---

## Common errors

### "Sign in to confirm you're not a bot" (yt-dlp 403)

YouTube периодически обновляет защиту от ботов, ломая yt-dlp на 1–3 месяца подряд по всему миру. **Это не баг этого инструмента.** Исправление:

1. `youtube-transcribe update-deps` — обновляет yt-dlp до последнего релиза.
2. Если не помогло: `youtube-transcribe transcribe <URL> --cookies-from-browser chrome`
   (также: `firefox`, `edge`, `safari`).
3. Если всё ещё не работает — открой issue, обычно фикс появляется за несколько дней.

> **Контекст:** YouTube регулярно усиливает защиту. Возможно, понадобится PO Token plugin (`bgutil-ytdlp-pot-provider`) — следи за [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases).

### Нет API-ключа

```
Error: GEMINI_API_KEY not set. Run: youtube-transcribe config set-key gemini
```

Запусти `youtube-transcribe config set-key <backend>` — попросит ввести ключ интерактивно и сохранит в `~/.youtube-transcribe/.env` с правами `0600`.

### `distil` модель на Mac

```
Error (exit code 4): Model 'distil' is not available on Apple Silicon (mlx-whisper).
Use: turbo, large, medium, or small.
```

`distil-large-v3` реализован только в `faster-whisper` (Windows/Linux). На Mac используй `turbo` — сопоставимая скорость.

### Нет `ffmpeg`

```
Error: ffmpeg not found. Install: brew install ffmpeg (Mac) / choco install ffmpeg (Windows)
```

ffmpeg нужен для извлечения аудио из видео перед транскрипцией.

### CUDA не найдена / падает на GPU

```bash
youtube-transcribe transcribe <URL> --device cpu --compute-type int8
```

Или смени бэкенд на `subtitles` / `gemini` / `groq`.

### Нет субтитров на `subtitles` бэкенде

Видео без субтитров (автоматических или ручных) на запрошенном языке — skill вернёт ошибку. В smart-режиме автоматически переключится на `whisper-local`.

### Лимиты Gemini Files API

Gemini Files API принимает файлы до ~2 GB и видео до ~1 часа стабильно. Для видео > 1 часа используй `whisper-local` или `assemblyai`.

---

## Privacy

| Backend | Аудио уходит с машины? |
|---|---|
| `whisper-local` | Никогда |
| `subtitles` | Нет — но YouTube видит запрос |
| `gemini` | Да, Google |
| `groq` | Да, Groq |
| `openai` | Да, OpenAI |
| `deepgram` | Да, Deepgram |
| `assemblyai` | Да, AssemblyAI |
| `custom` | Да, твой провайдер |

API-ключи никогда не выводятся целиком в логи — маскируются как `sk-***...XYZ`. `config show` тоже маскирует.

---

---

## Architecture (for developers)

### Структура проекта

```
youtube-transcribe/
├── .claude-plugin/
│   └── plugin.json                       # Метаданные Claude Code plugin
├── skills/
│   └── youtube_transcribe/               # Python-пакет (snake_case)
│       ├── SKILL.md                      # Триггеры + правила для Claude
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
│       │   ├── platform_detect.py        # OS/GPU/VRAM авто-определение
│       │   ├── downloader.py             # yt-dlp wrapper
│       │   └── output_writer.py          # .txt + .srt
│       └── tests/
├── commands/
│   └── transcribe.md                     # /transcribe slash-команда
└── pyproject.toml
```

### Transcriber Protocol

`backends/base.py` определяет контракт:

```python
class Transcriber(Protocol):
    name: str
    supports_url: bool          # subtitles — да, остальные через downloader
    supports_local_file: bool

    def is_configured(self) -> tuple[bool, str | None]:
        """Готов ли бэкенд. Возвращает (ok, причина_если_нет)."""

    def transcribe(
        self, audio_path: Path | str, *, language: str, **opts
    ) -> TranscriptionResult:
        ...

@dataclass
class TranscriptionResult:
    text: str
    segments: list[Segment]        # для .srt и .txt с таймкодами
    language_detected: str | None
    backend_name: str
    duration_seconds: float
```

Все 8 бэкендов — взаимозаменяемые реализации одного `Transcriber` Protocol. Тесты пишутся против интерфейса; внешние SDK мокаются.

### Smart-режим — композиция, не бэкенд

При `default_backend = "smart"`:
1. URL → YouTube? → пробуем `subtitles`.
2. Успех → возвращаем результат.
3. Нет субтитров / не YouTube / `--no-fast-path` → используем `fallback_backend` (дефолт: `whisper-local`).

Логика живёт на верхнем уровне; бэкенды ничего не знают друг о друге.

### Whisper-local — две реализации, один интерфейс

`platform_detect.py` определяет окружение и возвращает `label` / `backend_impl` / `device` / `vram`. `whisper_local.py` использует результат чтобы выбрать:
- macOS arm64 → `mlx-whisper`
- Windows/Linux + NVIDIA → `faster-whisper` (float16 или int8_float16 в зависимости от VRAM)
- CPU only → `faster-whisper` с `device="cpu"`, `compute_type="int8"`

### Конфиг и секреты

- `~/.youtube-transcribe/config.toml` — настройки (TOML).
- `~/.youtube-transcribe/.env` — API-ключи, права `0600` на Unix.
- Приоритет: env vars процесса > `.env` > ошибка с инструкцией.

---

## Adding a new backend

1. Создай файл `skills/youtube_transcribe/backends/my_provider.py`.
2. Реализуй `Transcriber` Protocol (см. `backends/base.py`).
3. Зарегистрируй в фабрике (`backends/__init__.py`):
   ```python
   from .my_provider import MyProviderTranscriber
   REGISTRY["my-provider"] = MyProviderTranscriber
   ```
4. Добавь в `--backend` choices в `transcribe.py`.
5. Напиши unit-тест с замоканным SDK в `tests/test_backends.py`.

Всё. Остальной код (smart-режим, output writer, config, CLI) не трогается.

---

## Whisper model comparison

| Параметр | `turbo` (default) | `large` | `medium` | `small` | `distil` |
|---|---|---|---|---|---|
| Базовая модель | large-v3-turbo | large-v3 | medium | small | distil-large-v3 |
| VRAM (float16) | ~6 GB | ~10 GB | ~5 GB | ~2 GB | ~6 GB |
| Точность | Отличная | Максимальная | Хорошая | Средняя | Отличная (EN) |
| Скорость | Быстрая | Медленная | Средняя | Очень быстрая | Самая быстрая |
| Когда использовать | Большинство задач | Юридические/медицинские записи | Слабое железо | Черновик | Только faster-whisper, EN |
| macOS (mlx) | Да | Да | Да | Да | Нет |

---

## Roadmap

**v0.3 — расширение batch:**
- `batch --search "claude programming"` — поиск по тегам/теме (YouTube Data API или yt-dlp `ytsearchN:`)
- `--workers N` — параллельный прогон (для облачных бэкендов)
- `--skip-existing` — кэш по `video_id`, чтобы повторный batch не перетранскрибировал уже сделанное
- Фильтры канала: `--since`, `--until`, `--min-duration`, `--max-duration`, `--no-shorts`

**v0.4:**
- `batch --instagram @user` — Reels из аккаунта Instagram (yt-dlp + cookies)

**v1.x:**
- Диаризация (who-said-what) через `pyannote-audio`
- Чанкинг для видео >2ч
- Опциональное LLM-саммари внутри skill (`--summarize`) — для тех, кто использует CLI без Claude-чата
- PyPI publication

---

## License

MIT — see [LICENSE](LICENSE).
