# Дизайн-документ: youtube-transcribe

**Дата:** 2026-05-08
**Статус:** Черновик к согласованию
**Автор:** brainstorm с пользователем (Claude Code)

---

## 1. Цель

Создать переиспользуемый skill `youtube-transcribe`, который:

1. Принимает на вход URL YouTube-видео (или другой поддерживаемой платформы), либо путь к локальному медиа-файлу.
2. Транскрибирует контент через один из шести взаимозаменяемых движков (бэкендов).
3. Сохраняет результат в `.txt` (с таймкодами и без) и `.srt`.
4. Триггерится в Claude Code естественным языком на любом языке (русский, английский, украинский, казахский, и т.д.) — пользователю достаточно сказать «транскрибируй это» и вставить ссылку.
5. Также имеет slash-команду `/transcribe` и работает как самостоятельный CLI без Claude.
6. **Распространяется тремя способами**, чтобы любой пользователь мог быстро установить — как Claude Code plugin, как личный skill в `~/.claude/skills/`, или как uv tool из Git/PyPI.

**Главный принцип:** zero-friction для конечного пользователя. Установка одной командой, разумные дефолты, понятные ошибки, никакого ручного возни с CUDA/cuDNN.

---

## 2. Аудитория и нефункциональные требования

### Аудитория

- **Обычные пользователи** — хотят кинуть ссылку, получить текст. Без знания Python/CUDA.
- **Технические пользователи** — хотят выбрать модель, движок, тонко настроить. Понимают разницу между float16 и int8.
- **Разработчики** — могут захотеть форкнуть и доработать (новый бэкенд, диаризация, и т.п.).

### Приватность (важно)

- **Дефолтный режим = оффлайн.** Бэкенд `whisper-local` ничего не отправляет в сеть после установки модели.
- **Облачные бэкенды** (gemini, groq, openai, custom) отправляют аудио на сервера провайдера. README и wizard явно об этом предупреждают.
- API-ключи **никогда** не попадают в git, в логи, в чат с Claude. Хранение — env vars или `~/.youtube-transcribe/.env` с правами `0600`.

---

## 3. Распространение и установка

Один GitHub-репозиторий обслуживает три варианта установки. Все три должны работать из коробки.

### Способ A — Claude Code Plugin (рекомендуется большинству)

```bash
git clone https://github.com/<user>/youtube-transcribe ~/.claude/plugins/youtube-transcribe
```

Claude автоматически подхватывает skill и slash-команду. При первом использовании запускается wizard.

### Способ B — Личный skill-папка

```bash
git clone https://github.com/<user>/youtube-transcribe /tmp/yt-transcribe
cp -r /tmp/yt-transcribe/skills/youtube-transcribe ~/.claude/skills/
cd ~/.claude/skills/youtube-transcribe && uv sync
```

Без plugin-обвязки. Работает только как skill (без slash-команды).

### Способ C — Только CLI, без Claude

```bash
uv tool install git+https://github.com/<user>/youtube-transcribe
```

В терминале появляется команда `youtube-transcribe`. Можно использовать в скриптах, других IDE, без Claude вообще.

### Загрузчик зависимостей: `uv`

Используем `uv` (Astral) вместо `pip`:
- Бинарник в 1 файл, доступен на всех платформах.
- В 10–50× быстрее `pip`.
- Сам ставит правильную версию Python если её нет.
- Решает проблему «у пользователя нет Python вообще».

`install.ps1` и `install.sh` — это тонкие обёртки, которые: (а) устанавливают `uv` если его нет, (б) запускают `uv sync` в репозитории. Это **запасной путь** для тех, у кого нет даже `uv`.

---

## 4. Архитектура и структура файлов

```
youtube-transcribe/
├── .claude-plugin/
│   └── plugin.json                       # Метаданные Claude Code plugin
├── skills/
│   └── youtube-transcribe/
│       ├── SKILL.md                      # Триггеры + правила использования
│       ├── transcribe.py                 # CLI entry point
│       ├── wizard.py                     # First-run setup wizard
│       ├── config.py                     # Загрузка/запись config.toml + .env
│       ├── backends/
│       │   ├── __init__.py
│       │   ├── base.py                   # Абстрактный Transcriber
│       │   ├── subtitles.py              # youtube-transcript-api
│       │   ├── whisper_local.py          # faster-whisper / mlx-whisper
│       │   ├── gemini.py                 # google-genai SDK
│       │   ├── groq.py                   # OpenAI-compat
│       │   ├── openai_api.py             # OpenAI Whisper API
│       │   └── custom.py                 # Generic OpenAI-compat
│       ├── utils/
│       │   ├── __init__.py
│       │   ├── platform_detect.py        # Авто-определение OS/GPU/VRAM
│       │   ├── downloader.py             # yt-dlp wrapper + cookies + retries
│       │   └── output_writer.py          # .txt + .srt
│       └── tests/
│           ├── test_platform_detect.py
│           ├── test_output_writer.py
│           └── test_backends.py          # smoke-тесты с моками
├── commands/
│   └── transcribe.md                     # /transcribe slash-команда
├── pyproject.toml                        # uv tool install + entry_point
├── requirements-mac.txt                  # снапшот зависимостей для Apple Silicon
├── requirements-nvidia.txt               # снапшот зависимостей для Win/Linux + NVIDIA
├── install.ps1                           # bootstrap для Windows (если нет uv)
├── install.sh                            # bootstrap для Mac/Linux
├── README.md                             # Двухслойная документация
├── LICENSE
└── docs/
    ├── specs/
    │   └── 2026-05-08-youtube-transcribe-design.md
    └── plans/
        └── (план реализации добавится позже)
```

### Принцип абстракции бэкендов

Файл `backends/base.py` определяет интерфейс:

```python
class Transcriber(Protocol):
    name: str
    supports_url: bool          # умеет ли работать с URL напрямую (subtitles умеет, остальные через downloader)
    supports_local_file: bool

    def is_configured(self) -> tuple[bool, str | None]:
        """Проверка, что бэкенд готов работать. Возвращает (ok, причина_если_не_ок)."""

    def transcribe(self, audio_path: Path | str, *, language: str, **opts) -> TranscriptionResult:
        ...

@dataclass
class TranscriptionResult:
    text: str
    segments: list[Segment]   # для .srt и .txt с таймкодами
    language_detected: str | None
    backend_name: str
    duration_seconds: float
```

Каждый бэкенд — один файл, одна реализация интерфейса. Тесты пишутся против интерфейса.

---

## 5. Бэкенды (детально)

### 5.1 `subtitles` — youtube-transcript-api

**Когда:** YouTube-ссылка, есть автосубтитры.
**Скорость:** 2–5 сек на любую длину видео.
**Качество:** среднее (то, что YouTube распознал автоматически).
**Зависимости:** `youtube-transcript-api`.
**API-ключ:** не нужен.
**Поведение:**
- Если у видео нет субтитров на запрошенном языке — пробует автоперевод, если и его нет — возвращает «не получилось», skill переключается на fallback-бэкенд (если включён smart-режим).
- В .srt таймкоды берутся из субтитров (они уже разбиты на сегменты).

### 5.2 `whisper-local` — локальный Whisper (дефолт)

**Когда:** дефолт. Работает оффлайн.
**Зависимости:**
- На macOS Apple Silicon: `mlx-whisper`.
- На Windows/Linux + NVIDIA: `faster-whisper`.
- На CPU-only: `faster-whisper` с `device="cpu"` и `compute_type="int8"`.

Выбор реализации делает `platform_detect.py` автоматически, без участия пользователя.

**Модели** (через флаг `--model`):

| Параметр | Описание | Когда использовать |
|---|---|---|
| `turbo` (default) | large-v3-turbo | Большинство задач: подкасты, лекции, интервью |
| `large` | large-v3 | Максимальная точность, юридические/медицинские записи |
| `medium` | medium | Баланс на слабом железе (8 GB RAM/VRAM) |
| `small` | small | Очень быстрый черновик |
| `distil` | distil-large-v3 (только faster-whisper) | Самый быстрый full-quality, оптимизирован под английский |

**Маппинг моделей по платформам:**

```python
MODEL_MAP = {
    "turbo":  {"mlx": "mlx-community/whisper-large-v3-turbo", "faster": "large-v3-turbo"},
    "large":  {"mlx": "mlx-community/whisper-large-v3-mlx",   "faster": "large-v3"},
    "medium": {"mlx": "mlx-community/whisper-medium-mlx",     "faster": "medium"},
    "small":  {"mlx": "mlx-community/whisper-small-mlx",      "faster": "small"},
    "distil": {"mlx": None,                                   "faster": "distil-large-v3"},
}
```

При выборе несовместимой пары (например, `--model distil` на Mac) — понятная ошибка, не stack trace.

**`compute_type` по умолчанию:** `auto`. Логика:
- `mlx-whisper` — параметр игнорируется (там свой режим).
- `faster-whisper` + CUDA + VRAM ≥ 6 GB → `float16`.
- `faster-whisper` + CUDA + VRAM < 6 GB → `int8_float16`.
- `faster-whisper` + CPU → `int8`.

Пользователь может переопределить через `--compute-type`.

### 5.3 `gemini` — Google AI Studio

**Когда:** хочется качество, но локальный Whisper слишком медленный.
**Скорость:** 30–120 сек на час видео (зависит от размера загрузки).
**Зависимости:** `google-genai` SDK.
**API-ключ:** `GEMINI_API_KEY` или через wizard. Получить: https://aistudio.google.com/apikey
**Модели:**
- `gemini-2.5-flash` (дефолт) — бесплатная, быстрая, точная.
- `gemini-2.5-pro` — точнее, медленнее, лимиты строже.

**Особенности:**
- Gemini нативно понимает видео — можно отправлять mp4 целиком (для коротких файлов) либо извлекать аудио и отправлять mp3 (для длинных, чтобы не упереться в лимиты).
- Используем Files API для файлов > 20 MB.
- Промпт: «Transcribe this audio. Output JSON: `{"language": "...", "segments": [{"start": ..., "end": ..., "text": "..."}, ...]}`. Use precise timestamps.»

### 5.4 `groq` — Groq Whisper API

**Когда:** нужен самый быстрый облачный вариант.
**Скорость:** 5–20 сек на час аудио (Groq крутит Whisper на специальных LPU-чипах).
**Зависимости:** `groq` SDK или `openai` SDK с base_url groq.
**API-ключ:** `GROQ_API_KEY`. Получить: https://console.groq.com/keys
**Модели:** `whisper-large-v3` (точнее), `whisper-large-v3-turbo` (быстрее, дефолт).

### 5.5 `openai` — OpenAI Whisper API

**Когда:** у пользователя уже есть OpenAI ключ.
**Скорость:** 30–60 сек на час.
**Стоимость:** ~$0.006/минута аудио.
**Зависимости:** `openai` SDK.
**API-ключ:** `OPENAI_API_KEY`.
**Модели:** `whisper-1`.

### 5.6 `custom` — OpenAI-совместимый API

**Когда:** для гиков. Поддержка Deepgram-OpenAI-bridge, локальная LiteLLM, vLLM, etc.
**Конфигурация:**
- `base_url` — URL endpoint
- `api_key` — секрет (через env или .env)
- `model` — имя модели
- Опционально: дополнительные параметры через `extra_options`

**Использует** OpenAI SDK с переопределённым `base_url`. Пользователь сам отвечает за совместимость.

### 5.7 Smart-режим (не отдельный бэкенд, а композиция)

Когда `default_backend = "smart"`:
1. Если URL — это YouTube → пробуем `subtitles`.
2. Если получилось — возвращаем результат.
3. Если не получилось (нет субтитров, не YouTube, флаг `--no-fast-path`) → используем `fallback_backend` (по умолчанию `whisper-local`).

---

## 6. First-run wizard

Запускается при первом вызове skill (отсутствует `~/.youtube-transcribe/config.toml`) **или** по команде `youtube-transcribe config wizard`.

### Поведение

1. Приветствие, объяснение что это и какие варианты есть.
2. Авто-определение железа: OS, наличие NVIDIA GPU, объём VRAM, наличие Apple Silicon.
3. Подсказка наиболее подходящего варианта на основе железа:
   - Сильное железо (RTX 30/40/50, M1+) → рекомендация `whisper-local`.
   - Слабое железо → рекомендация `gemini` или `subtitles`.
4. Меню выбора бэкенда (см. ниже).
5. Если выбран облачный — запрос API-ключа с ссылкой где его взять, с проверкой ключа тестовым 5-секундным запросом.
6. Если выбран `smart` — выбор fallback-бэкенда отдельным вопросом.
7. Сохранение в `~/.youtube-transcribe/config.toml`. Ключи — в `~/.youtube-transcribe/.env`.

### Пример меню (текстовый)

```
🎬 youtube-transcribe — первая настройка

Обнаружил: Windows + NVIDIA RTX 4090 (24 GB)
Рекомендация: режим whisper-local (полностью оффлайн, лучшее качество)

Какой движок использовать по умолчанию?

  1) ⭐ whisper-local (рекомендуется для твоего железа)
     Локальный Whisper. Оффлайн, приватно, лучшее качество.

  2) smart
     Сначала пробует субтитры YouTube (мгновенно), иначе — выбранный fallback.

  3) subtitles
     Только субтитры YouTube. Мгновенно, среднее качество, только YouTube.

  4) gemini (Google AI Studio)
     Облачный. Бесплатный free tier. Нужен ключ.
     Получить: https://aistudio.google.com/apikey

  5) groq
     Облачный. Самый быстрый. Бесплатный free tier. Нужен ключ.
     Получить: https://console.groq.com/keys

  6) openai
     Облачный. Платный (~$0.006/мин). Нужен ключ.

  7) custom
     OpenAI-совместимый API. Для продвинутых.

> 1
✅ Сохранил. Дефолтный движок: whisper-local

Поменять выбор: youtube-transcribe config wizard
Использовать другой движок разово: youtube-transcribe <URL> --backend gemini
```

---

## 7. Переключение движков в чате (3 уровня)

Документируется и в SKILL.md (чтобы Claude применял), и в README (чтобы пользователь знал).

### Уровень 1 — разовое (per-call)

Claude видит явное упоминание движка в сообщении и добавляет флаг `--backend X` к одному вызову.

| Фраза пользователя | Команда |
|---|---|
| «расшифруй это через gemini: <URL>» | `youtube-transcribe <URL> --backend gemini` |
| «прогони через groq» | `... --backend groq` |
| «локально whisper large» | `... --backend whisper-local --model large` |
| «возьми субтитры с ютуба» | `... --backend subtitles` |
| «gemini, но pro вместо flash» | `... --backend gemini --gemini-model gemini-2.5-pro` |

### Уровень 2 — сессионное

Пользователь говорит «до конца разговора используй groq» — Claude запоминает в сессии и подставляет флаг ко всем последующим вызовам. Это поведение Claude как агента; SKILL.md явно инструктирует его так делать.

### Уровень 3 — постоянное

Меняет дефолт через CLI:

```bash
youtube-transcribe config show
youtube-transcribe config set backend groq
youtube-transcribe config set whisper-model turbo
youtube-transcribe config set language ru
youtube-transcribe config set-key gemini       # интерактивный ввод ключа
youtube-transcribe config test groq            # проверить, что ключ рабочий
youtube-transcribe config wizard               # перезапустить мастер
```

В чате тоже работает: «переключи дефолт на groq» → Claude дёргает `youtube-transcribe config set backend groq`.

---

## 8. CLI-параметры

```
youtube-transcribe <URL_или_путь_к_файлу> [опции]

Опции выбора движка:
  --backend {smart,subtitles,whisper-local,gemini,groq,openai,custom}
                                         Какой движок использовать (default: из config)
  --whisper-model {turbo,large,medium,small,distil}
                                         Модель для whisper-local (default: turbo)
  --gemini-model NAME                    Модель Gemini (default: gemini-2.5-flash)
  --groq-model NAME                      Модель Groq (default: whisper-large-v3-turbo)

Опции вывода:
  --output-dir DIR                       Куда сохранить (default: ./transcripts)
  --timestamps / --no-timestamps         Включить таймкоды в .txt (default: true)
  --srt / --no-srt                       Создавать .srt (default: true)
  --language LANG                        Язык (ru, en, kk, uk, …) (default: auto)

Whisper-специфичные:
  --device {auto,cuda,cpu,mps}           Устройство (default: auto)
  --compute-type {auto,float16,int8_float16,int8}
                                         (default: auto)
  --beam-size N                          (default: 5)
  --vad / --no-vad                       Voice activity detection (default: true)

Загрузка:
  --keep-audio                           Сохранить скачанный mp3
  --cookies-from-browser {chrome,firefox,edge,safari}
                                         Использовать cookies для обхода блокировок YouTube

Прочее:
  --no-fast-path                         Отключить subtitles fast-path в smart-режиме
  --verbose                              Подробный вывод
  --version
  --help

Sub-commands:
  config show
  config set <key> <value>
  config set-key <backend>
  config test <backend>
  config wizard
```

---

## 9. Slash-команда `/transcribe`

Файл `commands/transcribe.md` определяет команду. Тонкая обёртка вокруг `transcribe.py`:

```bash
/transcribe <URL_или_путь> [любые флаги CLI]
```

Примеры:
- `/transcribe https://youtu.be/XXX`
- `/transcribe video.mp4 --backend gemini`
- `/transcribe https://youtu.be/XXX --backend whisper-local --model large --language ru`

После выполнения Claude автоматически читает результат и предлагает анализ/перевод/саммари (как в спеке).

---

## 10. SKILL.md — триггеры и анти-триггеры

Skill срабатывает по семантическому матчингу `description`. Поэтому описание должно:

1. Чётко формулировать цель.
2. Перечислять характерные фразы-триггеры на нескольких языках.
3. **Явно** перечислять анти-триггеры, чтобы избежать ложных срабатываний.

### Позитивные триггеры (примеры формулировок в description)

- Прямые: «транскрибируй», «расшифруй», «сделай текст», «transcribe», «get transcript», «розшифруй», «yazıya geçir».
- Просьбы по содержанию видео: «о чём это видео», «что говорят», «what's in this video».
- Просьбы субтитров: «сделай субтитры», «.srt», «make subtitles».
- Скачивание + расшифровка: «скачай и расшифруй», «download and transcribe».
- Локальные файлы: «расшифруй mp3», «transcribe meeting.mp4».
- Просто YouTube-ссылка как единственный контент сообщения.
- Запросы на саммари видео по ссылке (skill сначала транскрибирует, потом Claude суммирует).
- Запросы цитат из видео, таймкодов, перевода видео.
- Переключение движка: «через gemini», «локально whisper», «возьми субтитры», «через groq».

### Анти-триггеры

- В чате уже есть готовый транскрипт — пользователь просит про сам текст, skill не нужен.
- Концептуальные вопросы: «что такое whisper», «как работает транскрипция».
- Запрос рекомендации видео без URL: «посоветуй видео про X».
- Создание / запись / съёмка видео.
- Вопросы про сам skill: «как установить», «покажи код transcribe.py».
- Не-видео ссылки в контексте, где явно не запрошена транскрипция.

### Поддерживаемые платформы (URL)

`yt-dlp` поддерживает 1000+ сайтов: YouTube, Vimeo, Twitter/X, TikTok, Twitch VOD, SoundCloud, Bilibili, Rutube и т.д. По умолчанию любой URL пробуем через yt-dlp. Если yt-dlp не справляется — понятная ошибка.

---

## 11. Загрузчик YouTube/медиа (utils/downloader.py)

`yt-dlp` как основной инструмент. Обёртка добавляет:

1. **Авто-обновление yt-dlp** при первом запуске за день (`yt-dlp -U`). Кэшируется флаг последнего обновления в `~/.youtube-transcribe/state.json`.
2. **Поддержка cookies** через `--cookies-from-browser`, флаг проброшен в CLI.
3. **Геобайпасс** по умолчанию: `--geo-bypass`.
4. **Обработка типичных ошибок:**
   - 403 / "Sign in to confirm you're not a bot" → подсказка: «попробуй `--cookies-from-browser chrome`».
   - 401 / age-restricted → подсказка: «нужны cookies залогиненного аккаунта».
   - Региональная блокировка → подсказка: «попробуй VPN или другой регион».
5. **Опциональный fallback на pytube** — если установлен и yt-dlp упал, пробуем pytube. Чисто запасной парашют, не основной механизм.
6. **Извлечение только аудио:** `-x --audio-format mp3 --audio-quality 0`.
7. **Очистка временного файла** после транскрипции (если `--keep-audio` не указан).

---

## 12. Output writer (utils/output_writer.py)

### .txt с таймкодами

```
[00:00:00.000 --> 00:00:05.240] Привет, в этом видео мы разберём…
[00:00:05.240 --> 00:00:09.800] первое что нужно понимать это…
```

### .txt без таймкодов

Слитный текст, разбитый на абзацы по эвристике: новый абзац после паузы > 2 сек **или** после ~5 сегментов.

### .srt

Стандартный формат, индексация с 1, таймкоды `HH:MM:SS,mmm`.

```
1
00:00:00,000 --> 00:00:05,240
Привет, в этом видео мы разберём…

2
00:00:05,240 --> 00:00:09,800
первое что нужно понимать это…
```

### Имена файлов

`<output-dir>/<санитизированное имя видео>_<дата>.txt` (и `.srt`). Из спецсимволов в имени оставляем только буквы/цифры/`-`/`_`.

---

## 13. Конфиг и хранение ключей

### `~/.youtube-transcribe/config.toml`

```toml
default_backend = "whisper-local"
fallback_backend = "whisper-local"     # для smart-режима

[whisper-local]
model = "turbo"
device = "auto"
compute_type = "auto"
beam_size = 5
vad = true

[gemini]
model = "gemini-2.5-flash"

[groq]
model = "whisper-large-v3-turbo"

[openai]
model = "whisper-1"

[custom]
base_url = ""
model = ""

[output]
language = "auto"
timestamps = true
srt = true
output_dir = "./transcripts"

[behavior]
keep_audio = false
yt_dlp_auto_update = true              # авто-обновление раз в день
cookies_browser = ""                   # "" | "chrome" | "firefox" | "edge"
fast_path_enabled = true               # пробовать субтитры в smart-режиме
```

### `~/.youtube-transcribe/.env`

```
GEMINI_API_KEY=...
GROQ_API_KEY=...
OPENAI_API_KEY=...
CUSTOM_API_KEY=...
```

- Права на Unix: `0600`. На Windows — стандартные права пользователя.
- Файл явно прописан в `.gitignore` репозитория skill (на случай, если кто-то решит закоммитить).
- Wizard и `config set-key` пишут сюда.

### Приоритет загрузки ключей

1. Переменные окружения процесса (например, `GEMINI_API_KEY=xxx youtube-transcribe ...`).
2. `~/.youtube-transcribe/.env`.
3. Если нет — wizard или CLI выводит понятную ошибку с инструкцией.

### Безопасность

- Ключи никогда не печатаются в логи (`--verbose`) полностью; маскируются как `sk-***...XYZ`.
- Не передаются в Claude-чат напрямую — Claude видит только результат транскрипции.
- При запросе пользователю «покажи мой ключ» — отказываемся, говорим что лежит в `.env`.

---

## 14. Документация (README.md)

Двухслойная структура:

### Слой 1 — для обычного пользователя (~50% файла)

1. **Заголовок и одно предложение что это.**
2. **GIF/скриншот демо** (потом, опционально).
3. **Установка** — три рецепта (плагин / skill / uv tool), для каждого один блок команд для Win/Mac/Linux.
4. **Быстрый старт** — три примера: вставить ссылку, локальный файл, slash-команда.
5. **Какое железо нужно** — таблица с честными цифрами (см. ниже).
6. **Управление движками** — как переключаться в чате (3 уровня) и через CLI.
7. **Частые ошибки** — yt-dlp 403, нет CUDA, ключ не работает, и т.д.

### Слой 2 — для тех, кто хочет глубже (~50% файла)

1. **Архитектура** — диаграмма, что-куда-зачем, как устроены backends.
2. **Сравнение моделей Whisper** — turbo / large / medium / small / distil, реальный WER, размер VRAM.
3. **Как работают облачные бэкенды** — что отправляется, как защищаются ключи, лимиты free tier.
4. **Smart-режим внутри** — алгоритм выбора движка.
5. **Тонкая настройка** — `compute_type`, `beam_size`, `vad`, `--no-fast-path`.
6. **Расширение** — как добавить свой бэкенд (реализовать интерфейс `Transcriber`).
7. **Roadmap** — диаризация (`pyannote-audio`), чанкинг для видео >2ч, авто-саммари через Claude/Gemini.

### Таблица «какое железо нужно»

| Железо | Подходящий бэкенд | Час видео = | Комментарий |
|---|---|---|---|
| Любое (есть YouTube-субтитры) | `subtitles` | 2–10 сек | Среднее качество, мгновенно |
| RTX 4090/4080/5090 (16+ GB) | whisper-local turbo | 30–60 сек | float16, идеал |
| RTX 4070/3080/4060 Ti (12 GB) | whisper-local turbo | 1–2 мин | float16 |
| RTX 3060/4060 (8–12 GB) | whisper-local turbo | 2–4 мин | float16 |
| RTX 2060 / GTX 1660 Ti (6 GB) | whisper-local turbo | 5–10 мин | int8_float16 |
| GTX 1060/1050 Ti (3–6 GB) | whisper-local medium | 15–30 мин | На грани |
| M3 Max / M4 Pro | whisper-local turbo | 30–45 сек | mlx-whisper |
| M2 Pro / M3 / M4 | whisper-local turbo | 1–2 мин | mlx-whisper |
| M1 / M2 base (8 GB) | whisper-local turbo | 2–4 мин | mlx-whisper |
| CPU only, Ryzen 7 / i7 | whisper-local small | 30–45 мин | Очень медленно |
| Слабое железо в целом | `gemini` или `groq` | 30–120 сек | Облако, нужен интернет + ключ |

**Рекомендация по железу для дефолтного режима (whisper-local):**
- ✅ Идеально: NVIDIA RTX 30/40/50-серия (≥6 GB VRAM) или Apple Silicon M1+.
- 🟡 Норм для коротких видео: GTX 16-серия, старые RTX 20.
- 🔴 Лучше переключиться на `subtitles` или `gemini`/`groq`: интегрированная графика, ноутбуки без дискретной GPU.
- ⛔ Не ставь whisper-local: машины <8 GB RAM. Используй облачные бэкенды.

---

## 15. Тестирование

### Уровень 1 — unit-тесты с моками

- `test_platform_detect.py` — мокаем `subprocess` и `platform`, проверяем что выбор движка корректен для всех комбинаций OS × GPU.
- `test_output_writer.py` — проверяем формат .txt (с/без таймкодов) и .srt.
- `test_config.py` — загрузка/запись config.toml, приоритет env vars, маскирование ключей в логах.
- `test_backends.py` — каждый бэкенд тестируется с замоканным внешним вызовом, проверяем что они корректно реализуют интерфейс.

### Уровень 2 — интеграционные тесты

- Smoke-тест на коротком (≤60 сек) публичном YouTube-видео для каждого бэкенда (whisper-local, subtitles; gemini/groq/openai — только если ключ настроен в окружении CI).
- Тест fallback: yt-dlp ловит специально подготовленную ошибку → пробуется pytube (или возвращается понятная ошибка).
- Тест cookies: проверка что флаг `--cookies-from-browser` правильно передаётся в yt-dlp (без реального вызова).

### Уровень 3 — проверка вручную в финале

- `python transcribe.py --help` — показывает все опции.
- Прогон на тестовом 60-секундном русском видео с YouTube → получаем .txt и .srt.
- Прогон того же видео с `--backend subtitles` → мгновенно.
- Прогон того же видео с `--backend gemini` (если ключ есть) → результат сопоставим.
- Wizard на свежей машине (через эмуляцию: удаляем `~/.youtube-transcribe/`, запускаем).
- `youtube-transcribe config set backend groq && youtube-transcribe config show` — изменение видно.

---

## 16. Что НЕ делаем в v1 (out of scope)

- **Диаризация** (определение спикеров) — `pyannote-audio` тяжёлый, требует HF-токен. Оставляем как опциональный плагин в roadmap.
- **Чанкинг для видео > 2 ч** — для большинства бэкендов это не критично, но для надёжности — задача v2.
- **Постобработка через локальную LLM** (исправление имён собственных, терминов) — пользователь может попросить Claude в чате после транскрипции.
- **Авто-саммари как часть skill** — не нужно, Claude в чате всё равно читает результат и сам предлагает саммари.
- **Web UI** — этот skill чисто CLI/chat.
- **Стриминг** (live-транскрипция) — это совсем другой usecase.
- **Поддержка не-OpenAI-compatible API** в `custom`-бэкенде — провайдер должен говорить на OpenAI-диалекте.

---

## 17. Открытые вопросы / риски

1. **Версии моделей mlx-whisper.** Нужно проверить актуальные имена в репо `mlx-community` на huggingface — возможно, пути в `MODEL_MAP` изменятся к моменту реализации.
2. **YouTube anti-bot обновления.** YouTube обновляет защиту регулярно. Возможно, к моменту релиза потребуется PO Token plugin (`bgutil-ytdlp-pot-provider`). README должен это упомянуть.
3. **Gemini Files API лимиты.** Уточнить актуальные лимиты на размер файла (на момент написания — 2GB через Files API), длительность (до 1 часа — стабильно, дольше — есть нюансы).
4. **mlx-whisper не тестируется в этой сессии** — у разработчика Windows-машина. Реализация будет по официальной документации, но без живого прогона. Помечаем в README как «macOS-путь требует прогона на реальном Mac перед релизом».
5. **uv доступность.** На каких-то корпоративных Windows-машинах может быть запрет на скачивание бинарников. README должен иметь fallback-инструкцию через pip.

---

## 18. Финальный чек-лист (повторение для удобства)

- ✅ Дефолтный бэкенд: `whisper-local` (оффлайн, приватно).
- ✅ 6 бэкендов: subtitles, whisper-local, gemini, groq, openai, custom + smart-композиция.
- ✅ First-run wizard с автодетектом железа.
- ✅ Переключение движков в чате (per-call / session / persistent).
- ✅ Slash-команда `/transcribe`.
- ✅ Расширенные мультиязычные триггеры + явные анти-триггеры.
- ✅ Защита yt-dlp: cookies, auto-update, fallback на pytube, понятные ошибки.
- ✅ Двухслойный README + честная таблица железа.
- ✅ Три способа установки: plugin / skill / uv tool.
- ✅ Безопасное хранение ключей: env vars > .env (0600), не в git, маскирование в логах.
- ✅ Тесты: unit + интеграционные + ручная финальная проверка.

---

## 19. Что дальше

После одобрения этого документа:

1. Создаётся **детальный план реализации** через skill `superpowers:writing-plans` — пошаговый: что делаем сначала, что потом, как проверяем каждый шаг.
2. Реализация по плану с регулярными чекпойнтами.
3. Финальный прогон и проверка по списку из раздела 15.
