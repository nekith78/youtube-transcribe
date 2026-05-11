# youtube-transcribe v0.6 — Design: `analyze` sub-command

**Status:** draft for review
**Date:** 2026-05-11
**Base version:** 0.5.2
**Target version:** 0.6.0

## 1. Принцип и мотивация

Скилл — **производитель данных**. Он транскрибирует видео и кладёт результаты в `outputs/<batch>/`. Скилл сам ничего НЕ анализирует.

Анализ — отдельный явный шаг через произвольный LLM (cloud или local). Раньше единственным «анализатором» был хардкодный `summarize` (TL;DR + ключевые пункты + цитаты). v0.6 обобщает это в команду `analyze`, которая:

1. Берёт один или несколько уже готовых транскриптов из batch-папки.
2. Упаковывает их в единый prompt вместе с **произвольным запросом пользователя**.
3. Отправляет в выбранную LLM.
4. Возвращает ответ файлом в папку batch'а и параллельно печатает в stdout.

Существующий `summarize` остаётся работоспособным как обратно-совместимая тонкая обёртка (внутренне дёргает тот же движок с предзаданным summary-промптом).

## 2. CLI surface

```
youtube-transcribe analyze [SOURCE] [OPTIONS]
```

### 2.1 Позиционный аргумент SOURCE

Может быть:

| Что | Поведение |
|---|---|
| Путь к batch-папке | Анализируем видео из этой папки (с интерактивом или флагом `--all`/`--select`). |
| Путь к одному транскрипту (`.txt` / `.json` / `.srt`) | Анализируем только этот файл, picker не запускается. |
| Опущен | Если `--latest` — берётся последний batch. Иначе — single-select picker по списку batch'ей в `outputs/`. |

Если SOURCE — папка, не являющаяся batch'ем (нет `batch_manifest.json`), но содержит транскрипты — обрабатываем все `.txt`/`.json`/`.srt` файлы внутри как отдельные видео без метаданных.

### 2.2 Опции

| Флаг | Тип | Дефолт | Описание |
|---|---|---|---|
| `--prompt TEXT` | str | — | Inline-запрос пользователя. |
| `--prompt-file PATH` | path | — | Запрос из файла (`.md`/`.txt`). Взаимоисключает с `--prompt`. |
| `--backend` | choice | `gemini` | Один из `gemini` / `claude` / `openai` / `ollama`. |
| `--latest` | flag | False | Пропустить single-select batch'а, взять самый свежий по mtime. |
| `--all` | flag | False | Все видео batch'а без интерактива. |
| `--select INDICES` | str | — | Script-friendly выбор: `1,3,5-7`. Обходит интерактив. |
| `--append-to PATH` | path | — | Дописать результат в указанный markdown-файл вместо нового. |
| `--output PATH` | path | auto | Куда писать новый файл (auto = в папку batch'а). |
| `--ollama-model TEXT` | str | `llama3.2:3b` | Только для `backend=ollama`. |
| `--ollama-host TEXT` | str | `http://localhost:11434` | Только для `backend=ollama`. |
| `--no-stdout` | flag | False | Не печатать ответ в консоль (только в файл). |
| `--max-chars INT` | int | 60000 | На какой длине обрезать каждый транскрипт перед склейкой. |

Validation:
- Ровно один из `--prompt` / `--prompt-file` обязателен (иначе exit 2 с подсказкой).
- `--latest`, `--all`, `--select` взаимоисключающи.

### 2.3 Exit codes

| Code | Значение |
|---|---|
| 0 | OK, ответ записан. |
| 2 | Ошибка аргументов CLI. |
| 3 | SOURCE не существует или пустой. |
| 4 | LLM вернул пустой ответ / нет API-ключа. |
| 5 | Пользователь отменил интерактив (Ctrl-C в picker). |

## 3. Источник: разрешение SOURCE

Порядок:

1. Если SOURCE задан и это файл (`.txt`/`.json`/`.srt`) → single-video режим, picker пропускается.
2. Если SOURCE задан и это директория с `batch_manifest.json` → видео берутся из manifest'а.
3. Если SOURCE задан и это директория без manifest'а → все `*.txt|*.json|*.srt` в ней (sorted по имени), без metadata.
4. Если SOURCE опущен:
   - `--latest` → выбираем самую свежую папку в `outputs/` (по mtime).
   - иначе TTY + есть questionary → single-select picker по списку batch'ей.
   - иначе → ошибка с подсказкой передать SOURCE или `--latest`.

`outputs/` определяется так же, как в существующем `batch_cmd`: либо явно через config, либо `~/.youtube-transcribe/outputs/`.

## 4. Интерактивный picker

### 4.1 Когда применяется

Все условия одновременно:
- SOURCE — папка-batch (либо опущен и выбирается batch),
- НЕТ ни одного из `--latest` / `--all` / `--select`,
- stdin — TTY,
- `questionary` импортируется без ошибок.

В любом другом случае — fallback:
- если есть `--all` или `--select` или один файл — используем их,
- если нет ни флагов, ни TTY → exit 3 с подсказкой добавить `--all` / `--select` / `--latest`.

### 4.2 UX

Реализация на `questionary>=2.0`. Checkbox-список со стрелками, `Space` toggles, `Enter` confirms, `Ctrl-C` отменяет.

Строки picker'а (batch'а с видео):
```
[ ] 2026-05-09 14:22  03:42  How transformers work
[x] 2026-05-09 15:01  12:08  GPT-5 deep dive
[>] 2026-05-10 09:14  07:55  Mixture of Experts   ← cursor
[x] 2026-05-10 11:30  04:11  Claude vs GPT
```

Колонки: дата загрузки видео (из metadata) · длительность · название (truncate до 60 символов).

Если SOURCE опущен — сначала single-select picker по batch'ам:
```
2026-05-11 14:42  ●●○ 8/12 ok   12 videos   gemini  claude-search
2026-05-11 10:11  ●●● 5/5 ok    5 videos   smart   week-recap
2026-05-10 18:03  ●○○ 3/8 ok    8 videos   subtitles  morning
```

Шорткаты в multi-select: `a` — toggle all, `i` — invert (документируются в hint-строке внизу).

Headless / non-TTY: picker не запускается, обязательно один из `--all` / `--select` / `--latest`.

## 5. Промпт-инжиниринг

Запрос пользователя передаётся в LLM **as-is, без префиксов и хардкодных подсказок**. Цель — пользователь полностью владеет содержанием запроса.

### 5.1 Структура итогового prompt'а

```
{user_prompt}

---
Транскрипты:

### [1] How transformers work (2026-05-09, 03:42, en)
Source: https://youtube.com/watch?v=...

[00:00:00] Hello and welcome
[00:00:05] ...
...

---

### [2] GPT-5 deep dive (2026-05-09, 12:08, en)
Source: https://youtube.com/watch?v=...

[00:00:00] ...
```

### 5.2 System prompt

Минимальный, нейтральный:
```
You are an assistant that answers user questions about the content
of the provided video transcripts. Reply in the language of the
user query.
```

Для ollama (chat-completion API) system prompt передаётся явно, для остальных бэкендов — в обёртке текущего `_call_*` (если бэкенд не поддерживает system role — sysmsg склеивается с user-prompt'ом разделителем).

### 5.3 Метаданные транскрипта

Источник: `batch_manifest.json` (поле `results[i].videos[*]`). Берутся: `title`, `upload_date`, `duration_sec`, `language_detected`, `url`. Если manifest'а нет — только имя файла как заголовок.

### 5.4 Формат тела транскрипта

Если есть `.txt` с таймкодами — используется он как есть (формат `[HH:MM:SS.mmm --> HH:MM:SS.mmm] text`).
Если только `.json` — собираем `[HH:MM:SS] text` строки через `_format_transcript_for_summary`-подобный хелпер.
Если только `.srt` — конвертируем в плоский `[HH:MM:SS] text` через `transcript_loader`.

### 5.5 Размер контекста

Каждый транскрипт обрезается на `--max-chars` (default 60000) с маркером `[...truncated...]`. Это soft-guard от случайного запуска на 4-часовом подкасте, чтобы не выжечь токены и не получить 413 от API. Авто-chunking больших batch'ей в v0.6 НЕ делаем — пользователь сам отсекает через picker.

## 6. Output

### 6.1 Default путь

`<batch>/analysis-YYYY-MM-DD-HHMM.md`. При коллизии — суффикс `-2`, `-3` (как в existing output_writer).

Для single-file SOURCE: рядом с исходным файлом, `<source-stem>.analysis-YYYY-MM-DD-HHMM.md`.

### 6.2 Структура файла

```markdown
# Analysis — 2026-05-11 14:42

**Backend:** gemini (gemini-2.0-flash)
**Videos:** 4 of 12
- How transformers work
- GPT-5 deep dive
- Mixture of Experts
- Claude vs GPT

**Prompt:**
> Извлеки все упоминания эффективности и compute cost,
> сгруппируй по видео.

---

<полный ответ LLM>
```

### 6.3 `--append-to`

Если файл не существует — создаётся с заголовком документа `# Combined analyses`. Если существует — в конец дописывается блок-разделитель и стандартная шапка анализа выше (раздел 6.2 без `# Analysis` заголовка верхнего уровня, вместо него `## Analysis — 2026-05-11 14:42` на уровень ниже).

### 6.4 stdout

По умолчанию весь ответ LLM сразу печатается в stdout после записи в файл — чтобы при вызове из Claude Code в чате модель сразу видела результат (нет нужды ходить читать файл). `--no-stdout` подавляет.

## 7. Backend / auth

Полностью идентично `summarize` — переиспользуем существующие `_call_gemini` / `_call_claude` / `_call_openai` / `_call_ollama` из `quality/asr_corrector.py`.

| backend | env var | дефолтная модель |
|---|---|---|
| gemini | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| claude | `ANTHROPIC_API_KEY` | `claude-haiku-4-5` |
| openai | `OPENAI_API_KEY` | `gpt-4o-mini` |
| ollama | — (local) | `llama3.2:3b` |

(Дефолты совпадают с тем, что уже зашито в `quality/asr_corrector.py::_call_*` — нет необходимости вводить новые константы.)

При отсутствии ключа: exit 4 с подсказкой какую переменную в `.env` положить (как сейчас в `summarize`). Override модели для cloud-бэкендов в v0.6 не предусмотрен — дефолты выше; если потребуется, добавим `--model` отдельной итерацией.

## 8. Связь с `summarize`

`summarize` остаётся CLI-командой. Внутри:

```python
def summarize_cmd(...):
    return _run_analyze(
        sources=[src],
        user_prompt=_SUMMARY_PROMPT,
        backend=backend,
        ...
    )
```

Содержание `_SUMMARY_PROMPT` (хардкодного шаблона из `quality/summarizer.py`) переезжает в `analyze/runner.py` как именованный preset, к которому `summarize` обращается. Поведение `summarize` для пользователя не меняется.

## 9. Интеграция с `batch`

Добавляется флаг:

| Флаг | Поведение |
|---|---|
| `--then-analyze` | По завершении batch'а сразу запускает `analyze <свежий batch>` (с интерактивным picker'ом если TTY, иначе `--all`). |

Без флага batch ведёт себя как раньше. Промпт в этом сценарии — обязательный (`--prompt` / `--prompt-file`) или будет запрошен на stdin (если TTY).

## 10. Структура кода

```
skills/youtube_transcribe/
├── analyze/
│   ├── __init__.py
│   ├── source_resolver.py   # SOURCE → list of transcripts + metadata
│   ├── prompt_builder.py    # сборка контекста для LLM
│   ├── runner.py            # вызов LLM, retries, обработка ошибок
│   ├── picker.py            # questionary-based interactive UI
│   └── output_writer.py     # запись analysis-*.md и --append-to
├── transcribe.py            # +analyze_cmd, +--then-analyze в batch
└── quality/
    └── summarizer.py        # thin wrapper над analyze.runner
```

`quality/summarizer.py` после рефакторинга — 15-20 строк: тонкая обёртка с хардкодным промптом.

LLM-вызовы (`_call_gemini`/`_call_claude`/...) **остаются** в `quality/asr_corrector.py` — это уже общая инфраструктура, переиспользуется и `translator.py`, и `summarizer.py`, и теперь `analyze/runner.py`.

## 11. Тестирование

### 11.1 Unit

| Файл | Что покрывает |
|---|---|
| `tests/test_analyze_source_resolver.py` | разрешение SOURCE: файл / batch-папка / папка без manifest / `--latest` / отсутствует. |
| `tests/test_analyze_prompt_builder.py` | сборка контекста для LLM из mix-форматов; metadata header; truncation на `--max-chars`. |
| `tests/test_analyze_select_parser.py` | `--select` парсер: `"1,3,5-7"` → `[0, 2, 4, 5, 6]` (0-based внутри). |
| `tests/test_analyze_runner.py` | моки `_call_*`, проверка что user prompt идёт целиком, без модификации; backend gating; empty-response → exit 4. |
| `tests/test_analyze_output.py` | новый файл / коллизия имени / `--append-to` (новый/существующий). |
| `tests/test_cli_analyze.py` | CLI: `--help` содержит все флаги; required `--prompt`/`--prompt-file`; backend choice; missing key; ollama без ключа; `--no-stdout`. |
| `tests/test_summarize_uses_analyze.py` | `summarize` после рефакторинга вызывает `analyze.runner` с правильным prompt'ом и сохраняет старый output format. |

Picker (`analyze/picker.py`) не тестируется напрямую (TTY-зависимо) — вызывается через mock в CLI-тестах.

Цель по объёму: +20-25 тестов, итого ~565.

### 11.2 E2E smoke

Опциональный (`RUN_E2E_SMOKE=1`): запускает `analyze` на zafiksированном test batch'е с `--backend ollama` (если запущен локально) или `--backend gemini` (если задан ключ), проверяет ненулевой ответ. Под флагом из-за зависимости от внешних сервисов.

## 12. Зависимости

Новые runtime:
- **`questionary>=2.0`** (~30 KB) — interactive picker. В обязательные deps (без него default UX заметно деградирует).

Не добавляется ничего более. Все LLM-SDK уже подтянуты v0.5.

## 13. Out of scope (v0.6)

- авто-chunking больших batch'ей под context window (пользователь сам отбирает через picker),
- структурированный JSON-output (только free-form markdown),
- стриминг ответа в stdout (полный текст после завершения),
- multi-LLM ensemble / сравнение бэкендов в одном вызове,
- веб-форма для `analyze` (web UI — отдельная таска B2 в v0.6 plan),
- caching / dedup идентичных prompt'ов,
- slash-команда `/yt-analyze` в Claude Code (полагаемся на голый CLI; slash может появиться позже без изменений в скилле).

## 14. Совместимость и migration

- `summarize` сохраняет поведение байт-в-байт. Никакие пользователи не ломаются.
- Новых полей в `config.toml` нет.
- Manifest формат не меняется.
- Все новые пути файлов (`analysis-*.md`) — additive, не конфликтуют с существующими artefact'ами batch'а.

## 15. Acceptance criteria

- [ ] `youtube-transcribe analyze --help` показывает все флаги из §2.2.
- [ ] `analyze <path-to-txt> --prompt "..." --backend ollama` работает без API-ключей и пишет файл рядом.
- [ ] `analyze <batch> --all --prompt "..." --backend gemini` пишет `analysis-*.md` в папку batch'а.
- [ ] `analyze <batch> --prompt "..."` в TTY запускает picker, после выбора — пишет файл.
- [ ] `analyze --latest --prompt "..."` берёт самый свежий batch без интерактива.
- [ ] `analyze <batch> --select "1,3-5" --prompt "..."` обходит picker, обрабатывает указанные видео.
- [ ] `analyze ... --append-to existing.md` дописывает блок в существующий файл.
- [ ] `summarize` продолжает работать (existing tests green).
- [ ] `batch ... --then-analyze --prompt "..."` запускает analyze сразу после batch.
- [ ] Все новые тесты зелёные на macOS arm64, Linux, Windows × Python 3.11/3.12/3.13.
