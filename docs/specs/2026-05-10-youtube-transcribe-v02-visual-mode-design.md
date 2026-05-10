# Дизайн-документ: youtube-transcribe v0.2 — visual mode + quality check + dynamic presets

**Дата:** 2026-05-10
**Статус:** Черновик к согласованию
**Автор:** brainstorm с пользователем (Claude Code)
**Базовые спеки:**
- [v0.1 single](2026-05-08-youtube-transcribe-design.md)
- [v0.1 batch extension](2026-05-09-youtube-transcribe-v01-batch-extension-design.md)

---

## 1. Контекст и цель v0.2

v0.1.2 в production: 8 бэкендов, batch, smart-режим, wizard, slash, CI на 3 ОС × 2 Python, uv tool install, 208 unit + 2 e2e тестов зелёные, валидация на реальных API прошла.

**Главная мечта v0.2** (формулировка пользователя):

> «Хочу не просто транскрипт того, что говорят, а инструкцию с наглядными картинками — описание происходящего на экране, ключевые моменты с скриншотами, чтобы потом из этого сделать заметку или туториал.»

Это уникальная фича. Среди 8 бэкендов только Gemini multimodal умеет работать с видео целиком. Остальные семь — audio-only. v0.2 строится вокруг этой возможности, но **не привязана к одному провайдеру архитектурно**: добавляем `VisionBackend` как Protocol, чтобы будущие multimodal бэкенды (Claude Sonnet vision, GPT-4o vision) подключались без переделки.

Вторая цель v0.2 — **закрыть слабость smart-режима**: сейчас `subtitles` берутся всегда, если они есть, без проверки качества. На авто-сабах ютуба (60-70% accuracy в среднем) это даёт мусорный результат. Добавляем quality check.

Третья цель — **выкатить динамические презеты** вместо нынешних хардкод-настроек. Конфиг становится единой системой: реестр опций → CLI / TUI / будущий web UI читают одно и то же.

### Что входит в v0.2

- **Visual mode** для backend=gemini: `--with-visuals`, frame-detection, vision-prompt, embedded screenshots в combined.md.
- **Quality check** для транскриптов: `is_generated` от youtube-transcript-api + spell-check + 3-gram repetition + Aho–Corasick BoH + опц. perplexity (kenlm).
- **Multilingual triggers** через локальные embeddings (`paraphrase-multilingual-MiniLM-L12-v2`) + per-language soft/strict + raw.
- **Dynamic presets** — 4 готовых тира (eco / smart / standard / premium), все поля перекрываются CLI-флагами или своим конфигом.
- **Custom triggers TOML** в `~/.youtube-transcribe/triggers.toml`.
- **Architecture seam для web UI v0.4+**: единый реестр опций, никакого global state в pipeline.

### Out-of-scope для v0.2

| Фича | Куда отложено | Причина |
|---|---|---|
| Web UI | v0.4+ | Большой UX-проект, требует отдельной архитектурной фазы |
| ASR error correction (исправление ошибок через LLM) | v0.4+ | Отдельная подсистема, увеличит задержку и cost |
| Visual mode на других multimodal-моделях (Claude vision, GPT-4o) | v0.3 | API существует, но v0.2 фокусируется на Gemini для отладки |
| Search by tags (`batch --search`) | v0.3 | Унаследованный долг из v0.1 batch extension |
| Channel filters (`--since`, `--until`, `--no-shorts`) | v0.3 | Поля уже зарезервированы в `ResolverFilters` |
| `--workers N` параллелизм | v0.3 | Cloud-rate-limits, whisper-local не выигрывает |
| `--skip-existing` кэш | v0.3 | По фидбеку |
| Diarization (кто говорит) | v1.x | Глобально out-of-scope для всех бэкендов |
| Instagram backend | v0.4+ | Анти-бот, отдельная стратегия |

---

## 2. Архитектура

### Новые protocols

```python
# skills/youtube_transcribe/backends/vision_base.py
from typing import Protocol
from dataclasses import dataclass

@dataclass(frozen=True)
class VisualSegment:
    """Один визуально-аннотированный кусок видео."""
    start: float                    # секунды
    end: float
    description: str                # текст от vision-LLM: что происходит на экране
    keyframes: list[str]            # пути к кадрам (frames/<vid>_<sec>.jpg)
    detected_objects: list[str]     # опц. результат OCR / классификации
    trigger_reason: str             # "keyword:смотри сюда" | "scene_change" | "llm_classify" | "user_keyword:дедлайн"

class VisionBackend(Protocol):
    """Multimodal LLM, способный анализировать видео+аудио вместе."""
    def annotate_segments(
        self,
        video_path: Path,
        windows: list[DetectionWindow],
        prompt_template: str,
        language: str,
    ) -> list[VisualSegment]: ...

# skills/youtube_transcribe/quality/base.py
@dataclass(frozen=True)
class QualityReport:
    score: float                    # 0.0-1.0
    breakdown: dict[str, float]     # {"oov": 0.12, "repetition": 0.04, ...}
    flags: list[str]                # ["mostly_music", "high_oov", "looped"]
    recommendation: Literal["use_as_is", "fallback_recommended", "skip"]

class QualityChecker(Protocol):
    def check(
        self,
        segments: list[Segment],
        language: str,
        source: Literal["youtube_manual", "youtube_auto", "whisper", "external_asr"],
    ) -> QualityReport: ...

# skills/youtube_transcribe/detection/base.py
@dataclass(frozen=True)
class DetectionWindow:
    start: float
    end: float
    reason: str                     # совпадает с trigger_reason VisualSegment
    score: float                    # приоритет, для бюджета кадров

class Detector(Protocol):
    def find_windows(
        self,
        segments: list[Segment],
        video_path: Path,
        triggers: TriggerConfig,
    ) -> list[DetectionWindow]: ...
```

### Изменения в существующих типах

```python
# backends/base.py
@dataclass
class TranscriptionResult:
    text: str
    segments: list[Segment]
    language: str
    backend_used: str
    # NEW v0.2:
    quality: QualityReport | None = None
    visual_segments: list[VisualSegment] = field(default_factory=list)
```

`text` и `segments` остаются как раньше. `quality` заполнен всегда (в т.ч. score=1.0 для manual subs). `visual_segments` непустой только если запрошен visual-режим и backend=gemini.

### Pipeline в v0.2

```
ResolvedTarget
    ↓
download (mp4 если visual, m4a иначе)
    ↓
transcribe → TranscriptionResult{text, segments}
    ↓
quality_check → quality
    ↓ (smart-режим: если score < threshold → fallback transcribe)
detect_visual_windows → list[DetectionWindow]   (если --with-visuals)
    ↓
vision_annotate → list[VisualSegment]           (если windows непустой)
    ↓
write outputs (.txt, .srt, .visual.md или embedded в combined.md)
```

`run_pipeline()` остаётся единой точкой входа. Visual + quality — два опциональных stage перед write-этапом, не ломают ни single, ни batch.

### Файловая структура новых модулей

```
skills/youtube_transcribe/
├── backends/
│   └── vision_base.py             # NEW: VisionBackend Protocol, VisualSegment
├── quality/
│   ├── __init__.py
│   ├── base.py                    # NEW: QualityChecker Protocol, QualityReport
│   ├── heuristic_checker.py       # NEW: композитный чек из всех кирпичей
│   ├── spell.py                   # NEW: pyspellchecker wrapper
│   ├── repetition.py              # NEW: 3-gram loops detection
│   ├── boh.py                     # NEW: Aho-Corasick BoH
│   ├── perplexity.py              # NEW: kenlm wrapper (опц.)
│   └── data/
│       └── boh_phrases.txt        # NEW: список типичных whisper-галлюцинаций
├── detection/
│   ├── __init__.py
│   ├── base.py                    # NEW: Detector Protocol, DetectionWindow
│   ├── triggers.py                # NEW: TriggerConfig, load_triggers()
│   ├── matcher.py                 # NEW: regex/lemma/embedding matching
│   ├── scene.py                   # NEW: PySceneDetect wrapper
│   ├── frame_diff.py              # NEW: ImageHash diffing
│   └── data/
│       └── triggers_default.toml  # NEW: built-in EN universal phrases
├── vision/
│   ├── __init__.py
│   ├── gemini.py                  # NEW: VisionBackend для Gemini
│   ├── prompts.py                 # NEW: vision-prompt templates
│   └── frames.py                  # NEW: ffmpeg keyframe extraction
└── presets/
    ├── __init__.py
    ├── registry.py                # NEW: реестр всех опций (для CLI/TUI/web)
    └── data/
        └── presets_default.toml   # NEW: 4 готовых тира
```

---

## 3. Quality check

### Принцип

Composable. Один итоговый `HeuristicChecker` = композиция отдельных кирпичей. Каждый кирпич можно отключить флагом конфига. Все локальные, без сети.

### Кирпич A — `is_generated` gate

Источник: youtube-transcript-api `transcript.is_generated` (есть в публичном API). Стоимость: ноль (флаг идёт в той же мете, что текст). Если `False` (manual subs) → итог `score=1.0`, остальные кирпичи не запускаются.

### Кирпич B — Out-of-vocab ratio (`pyspellchecker`)

```python
def out_of_vocab_ratio(text: str, lang: str) -> float:
    spell = SpellChecker(language=lang)  # en, ru, de, es, fr, it, pt, ar
    tokens = re.findall(r"\b[a-zA-Zа-яА-ЯёЁ]+\b", text.lower())
    if not tokens:
        return 1.0
    unknown = spell.unknown(tokens)
    return len(unknown) / len(tokens)
```

- Норма: <0.05 (имена + редкие термины).
- Тревога: >0.15 — массовые обрезки слов ("првие" вместо "привет").
- Если язык не поддерживается pyspellchecker (например, kk), кирпич отключается, breakdown содержит `"oov": null`.

### Кирпич C — 3-gram repetition

```python
def trigram_repetition_rate(text: str) -> float:
    tokens = text.lower().split()
    if len(tokens) < 6:
        return 0.0
    trigrams = list(zip(tokens, tokens[1:], tokens[2:]))
    counter = Counter(trigrams)
    most_common_count = counter.most_common(1)[0][1]
    return most_common_count / len(trigrams)
```

- Норма: <0.1.
- Тревога: >0.3 — петля Whisper или мусор.

### Кирпич D — Bag of Hallucinations (Aho–Corasick)

Файл `quality/data/boh_phrases.txt` — стартовый список ≈50 фраз: "thank you for watching", "subtitles by", "♪ ♪", "you", "Пожалуйста, поделитесь видео", "Subscribe to my channel" и т.д. Источники: [whisper github discussion #679](https://github.com/openai/whisper/discussions/679), [arxiv 2501.11378](https://arxiv.org/html/2501.11378v1). Aho-Corasick через `pyahocorasick`. Метрика: суммарная длина hallucination-фраз / длина текста.

### Кирпич E — Non-speech markers

Регулярка по `[Music]`, `♪`, `🎵`, `[Applause]`, `(unintelligible)`, `[laughter]`, `[Music playing]`. Считаем долю покрытия по таймингу. Если >0.25 — флаг `mostly_music=True` в `flags`. На music whisper галлюцинирует, поэтому в smart-режиме quality падает до 0.3 даже без других проверок.

### Кирпич F — Perplexity (опционально, premium-преcет)

`kenlm` ngram-модель `wiki40b/<lang>` (≈30MB на язык, lazy download в `~/.cache/youtube-transcribe/lm/`). Считаем средний perplexity на сегмент, ищем outliers. Опционально, потому что:
- модели не существуют для редких языков;
- замедление ≈100ms на сегмент при тысячах сегментов даёт ощутимую задержку;
- pyspellchecker + repetition + BoH покрывают 90% реальных проблем без perplexity.

В eco/smart/standard выключен. В premium — включён.

### Композитный score

```python
def assess_transcript_quality(segments, language, source) -> QualityReport:
    if source == "youtube_manual":
        return QualityReport(1.0, {}, [], "use_as_is")

    text = " ".join(s.text for s in segments)
    breakdown = {}

    music = non_speech_marker_ratio(segments)
    breakdown["music"] = music
    if music > 0.25:
        return QualityReport(0.3, breakdown, ["mostly_music"], "fallback_recommended")

    oov = out_of_vocab_ratio(text, language)        # 0.0 хорошо, 1.0 плохо
    rep = trigram_repetition_rate(text)              # 0.0 хорошо, 1.0 плохо
    boh = bag_of_hallucinations_coverage(text)       # 0.0 хорошо, 1.0 плохо
    breakdown.update({"oov": oov, "repetition": rep, "boh": boh})

    if perplexity_enabled(language):
        ppl_outlier = perplexity_outlier_ratio(segments, language)
        breakdown["perplexity_outlier"] = ppl_outlier
    else:
        ppl_outlier = 0.0

    # Веса подобраны на golden set из 30 видео разных типов (см. §11 testing).
    # 1 - x → инвертируем чтобы все слагаемые «больше = лучше».
    score = (
        0.30 * (1 - min(oov / 0.15, 1.0)) +
        0.25 * (1 - min(rep / 0.3, 1.0)) +
        0.25 * (1 - min(boh / 0.1, 1.0)) +
        0.20 * (1 - min(ppl_outlier / 0.2, 1.0))
    )

    flags = []
    if oov > 0.15: flags.append("high_oov")
    if rep > 0.3: flags.append("looped")
    if boh > 0.1: flags.append("boilerplate_hallucinations")

    rec = "use_as_is" if score >= 0.6 else (
        "fallback_recommended" if score >= 0.3 else "low_quality"
    )
    return QualityReport(score, breakdown, flags, rec)
```

### Где запускается и что меняет

Quality check — **диагностический инструмент для выбора источника транскрипта**, а не gate для дропа видео. Финальный output идёт в combined.md **всегда**, независимо от score.

- **Smart-режим (только на источнике субтитров):** auto-subs прогоняются через checker. Если `recommendation != "use_as_is"` → fallback к `presets.smart.fallback_backend` (whisper-local). Полученный whisper-output записывается **как есть, без повторной проверки**.
- **Финальный output (любой режим, опционально):** флаг `--check-quality` или `[output] check_transcript_quality = true`. Записывает score+flags в `manifest.json` и в combined.md как warning, **не меняет what was written**.
- **`recommendation == "low_quality"`:** не failure. Видео попадает в combined.md с пометкой `⚠ Quality: low (score=0.32, flags=[looped, high_oov])`. В `errors.log` НЕ идёт. Failure — это только когда транскрипт пустой / download упал / API недоступен.

### Threshold-конфиг

```toml
[smart]
subtitle_quality_threshold = 0.6   # score < этого → fallback
quality_perplexity = false         # включить kenlm
quality_perplexity_lang_models = ["en", "ru"]   # какие модели держать
```

### Зависимости (новые в requirements)

| Пакет | Размер | Что даёт |
|---|---|---|
| `pyspellchecker` | ≈30MB (со словарями) | OOV detection |
| `pyahocorasick` | ≈1MB | Aho-Corasick для BoH и raw triggers |
| `kenlm` (опц.) | ≈5MB код + 30MB/lang модели | perplexity |
| `langdetect` | ≈1MB | язык per-segment для триггеров |

---

## 4. Триггеры — мультиязычные через локальные embeddings

### Принцип

Пользователь пишет триггеры на **одном языке** (default English) — они работают на видео любого языка через cross-lingual semantic similarity. Per-language секции остаются для случаев, когда нужно точное совпадение или сленг. **Никаких LLM-вызовов** — всё локально через `paraphrase-multilingual-MiniLM-L12-v2`.

### Структура `triggers.toml`

```toml
# ~/.youtube-transcribe/triggers.toml
# Override и extend built-in default. Built-in лежит в
# skills/youtube_transcribe/detection/data/triggers_default.toml.

# Основной язык универсальных триггеров.
default_language = "en"

# Метод матчинга универсальных триггеров на видео других языков.
# В v0.2 единственный поддерживаемый метод — semantic (локальные embeddings).
universal_match_method = "semantic"
universal_match_threshold = 0.65   # cosine similarity 0..1

# === ФОРМАТ ФРАЗ ===
# Каждая фраза в любой секции хранится одним из двух способов:
#   "look here"           — обычная строка, вес = 1.0 (по умолчанию)
#   ["function", 1.5]     — массив [фраза, вес], вес ≠ 1.0
# Веса учитываются при сортировке окон при превышении max_windows_per_video,
# не меняют отображаемый score (он остаётся 0..1).

# === УНИВЕРСАЛЬНЫЕ ТРИГГЕРЫ ===
# Срабатывают на ЛЮБОМ языке видео через cross-lingual embeddings.
[triggers.universal]
phrases = [
  "look here",
  "pay attention",
  "see this code",
  "this is important",
  "for example",
  "step by step",
  "demonstrate",
  "result",
  "diagram",
  "notice this",
  ["function", 1.5],          # код — приоритетнее обычных пояснений
  ["class", 1.5],
  ["method", 1.5],
]

# === PER-LANGUAGE OVERRIDES (опционально) ===
# Активны только когда detect_language(segment) == ключ.
[triggers.languages.ru]
soft   = ["смотри сюда", "обрати внимание", "вот этот код", "посмотрите сюда"]
strict = ["баг", ["PR", 2.0], "merge conflict", ["коммит", 1.3], "пайплайн"]

[triggers.languages.es]
soft   = ["mira aquí", "presta atención"]

[triggers.languages.de]
strict = ["Achtung", "Wichtig"]

# === RAW ===
# Срабатывают всегда, точное совпадение, на любом языке.
# Для мемов, сленга, технических терминов, имён собственных.
[triggers.raw]
phrases = [
  "this is fine",
  "feature not a bug",
  "deadline",
  ["TODO", 2.0],
  "FIXME",
]
```

### Алгоритм matching

**Парсинг записей фраз:**

```python
def parse_phrase_entry(entry) -> tuple[str, float]:
    """Возвращает (phrase, weight). Дефолт weight = 1.0."""
    if isinstance(entry, str):
        return entry, 1.0
    if isinstance(entry, list) and len(entry) == 2:
        phrase, weight = entry
        if not isinstance(phrase, str) or not isinstance(weight, (int, float)):
            raise ValueError(f"Invalid phrase entry: {entry}")
        return phrase, float(weight)
    raise ValueError(f"Phrase must be 'string' or ['string', number]: {entry}")
```

**Один раз на старте сессии (`load_triggers()`):**
1. Загрузить built-in default + user override (deep merge, user может выставить `mode = "replace"` для полной замены).
2. Распарсить все секции через `parse_phrase_entry`. Получаем `dict[phrase, weight]` для каждой секции.
3. Для `triggers.universal` посчитать embeddings через `paraphrase-multilingual-MiniLM-L12-v2`. Кэш в `~/.cache/youtube-transcribe/embeddings/<sha256(phrases_json)>.npy`.
4. Скомпилить Aho-Corasick automata: один для `raw`, по одному на каждый `languages.<lang>.strict`.
5. Загрузить lemmatizers для языков, у которых задан `soft`: `lemminflect` для en, `pymorphy3` для ru, spaCy multilingual model для остальных. Lazy import — только если соответствующая секция в TOML непустая.

**Per-segment в `Detector.find_windows()`:**

```python
@dataclass
class TriggerMatch:
    score: float           # base 0..1
    weight: float          # из TOML, default 1.0
    reason: str            # "raw" | "strict:ru" | "soft:ru" | "universal"
    phrase: str            # какая фраза сработала

def match_segment(segment: Segment) -> TriggerMatch | None:
    seg_lang = langdetect.detect(segment.text)
    text_lower = segment.text.lower()
    text_lemmas = lemmatize(text_lower, seg_lang) if has_lemmatizer(seg_lang) else None

    # 1. raw — Aho-Corasick точное совпадение
    hit = raw_automaton.find(text_lower)
    if hit:
        return TriggerMatch(1.0, raw_weights[hit], "raw", hit)

    # 2. languages.<seg_lang>.strict — Aho-Corasick точное совпадение
    if seg_lang in lang_strict_automatons:
        hit = lang_strict_automatons[seg_lang].find(text_lower)
        if hit:
            return TriggerMatch(1.0, lang_strict_weights[seg_lang][hit], f"strict:{seg_lang}", hit)

    # 3. languages.<seg_lang>.soft — substring по леммам
    if text_lemmas and seg_lang in lang_soft_lemmas:
        for lemma_phrase, weight in lang_soft_lemmas[seg_lang].items():
            if lemma_phrase in text_lemmas:
                return TriggerMatch(0.9, weight, f"soft:{seg_lang}", lemma_phrase)

    # 4. universal — cosine similarity через multilingual embeddings
    seg_emb = encoder.encode(segment.text)
    sims = cosine(seg_emb, universal_embeddings)  # vec [N]
    best_idx = sims.argmax()
    if sims[best_idx] >= threshold:
        phrase = universal_phrases[best_idx]
        return TriggerMatch(float(sims[best_idx]), universal_weights[phrase], "universal", phrase)

    return None
```

**Применение веса при выборе окон:**

```python
def select_windows(matches: list[TriggerMatch], max_windows: int, video_duration: float) -> list[DetectionWindow]:
    """Если matches помещаются в бюджет — берём все. Иначе — равномерно распределяем
    по таймкоду, в каждой временной корзине берём окно с максимальным score*weight."""
    if len(matches) <= max_windows:
        return [m.to_window() for m in matches]

    # Делим видео на max_windows корзин по времени
    bucket_size = video_duration / max_windows
    buckets: list[list[TriggerMatch]] = [[] for _ in range(max_windows)]
    for m in matches:
        idx = min(int(m.start / bucket_size), max_windows - 1)
        buckets[idx].append(m)

    # В каждой корзине — лучший по score*weight
    selected = []
    for bucket in buckets:
        if bucket:
            best = max(bucket, key=lambda m: m.score * m.weight)
            selected.append(best.to_window())
    return selected
```

### Боюсь ли производительности

`paraphrase-multilingual-MiniLM-L12-v2`: 118MB, 384-dim, ≈30ms на сегмент на CPU. Для 1-часового видео ~1500 сегментов × 30ms = 45 секунд один раз на видео. Acceptable. Под GPU (если есть) автоматически в 5x быстрее через PyTorch detect.

### Built-in default `triggers_default.toml`

≈25 EN-фраз в `triggers.universal`. Примеры:
- "look here", "pay attention", "this is important", "see this code", "for example", "step by step", "demonstrate", "result", "diagram", "notice this", "key point", "remember this", "important note", "watch closely", "the trick is", "the catch is", "this part", "see the difference", "this is how", "let me show you", "right here", "as you can see", "the result is", "compare these", "before and after"

Дефолтных весов на этапе built-in не задаём — все 1.0. Пользователь сам поднимает вес важных фраз через `triggers weight set` или ручную правку.

User может расширять/переопределять без правки built-in.

---

## 5. Детекция визуально-важных моментов

### Стратегия

Не отдаём всё видео в Gemini — это дорого и подавляющая часть контента это «человек говорит на камеру». Выбираем **окна** (диапазоны времени) для визуального анализа:

1. **Trigger-based** — фразы из `triggers.toml` matched на сегментах транскрипта. Окно: ±3 секунды от триггер-сегмента.
2. **Scene change** — резкая смена сцены через [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) `ContentDetector(threshold=27)`. Окно: 0.5 секунды до и после границы сцены.
3. **Frame-diff внутри окна** — через `imagehash` (perceptual hashing). Если внутри trigger-окна 5 кадров с разницей > N, расширяем окно или делаем больше keyframes.
4. **LLM full-pass** (только premium-преcет) — отдаём весь транскрипт в дешёвую LLM с системным промптом «найди фрагменты, где визуальная составляющая важнее аудио». Возвращает таймкоды.

### Composition по `detect_method`

| `detect_method` | A: keywords | B: scene | C: frame-diff | D: llm-full-pass | OCR |
|---|---|---|---|---|---|
| `keywords_only` | ✓ | — | — | — | — |
| `semantic` | universal+raw | — | — | — | — |
| `hybrid` | ✓ | ✓ | ✓ | — | опц. |
| `llm_full_pass` | ✓ | ✓ | ✓ | ✓ | ✓ |

Все методы возвращают `list[DetectionWindow]`. После — мердж пересекающихся окон (union интервалов с small gap < 1s) и cap на бюджет: `max_windows_per_video`, `max_total_keyframes`.

### OCR (опц.)

Включается флагом `ocr_enabled = true` в preset. Прогоняем все keyframes через [`pytesseract`](https://github.com/madmaze/pytesseract) (если есть в системе) или [`easyocr`](https://github.com/JaidedAI/EasyOCR) fallback. Результат идёт в `VisualSegment.detected_objects` как массив строк. Полезно когда в видео код, диаграммы, текст на экране — Claude в финальной заметке может процитировать кусок кода даже если в транскрипте речи о нём не было.

OCR off по умолчанию (тяжёлая зависимость, системный binary tesseract, замедление). Включается явно.

---

## 6. Vision backend (Gemini)

### Поведение

`VisionBackend.annotate_segments(video_path, windows, prompt_template, language)`:

1. Извлечь keyframes для каждого окна через `ffmpeg -ss <start> -t <dur> -vf 'select=eq(pict_type\,I)' -vsync vfr frames/%d.jpg`. Бюджет: `frames_per_window` (default 3) на окно.
2. Загрузить mp4 целиком в Gemini File API (один раз, не на окно). Использовать его в каждом call'е.
3. На каждое окно — структурированный prompt с timecode-диапазоном и keyframes. Получить JSON с описанием.
4. Собрать `VisualSegment[]`.

### Промпт-шаблон

```python
# vision/prompts.py

DEFAULT_PROMPT = """\
You are analyzing a YouTube video. Below is the transcript snippet for a specific
moment. Describe what is shown VISUALLY on the screen during this moment in
{language}, structured as JSON with these keys:
- description: 1-3 sentences. What is happening visually. Mention UI, code,
  diagrams, demonstrations. NOT what is said.
- key_objects: list of distinct visual objects/UI-elements/code-fragments shown.
- importance: "high" | "medium" | "low" — how visually informative is this moment
  beyond the spoken content.

Transcript context (audio only):
{transcript_snippet}

Time window: {start_sec:.1f}s — {end_sec:.1f}s.

Return ONLY valid JSON, no preamble.
"""
```

Язык описания (`description`) — берём из `language` параметра, который равен `language_detected` транскрипта. Это даёт consistent UX: транскрипт по-русски → визуальные описания тоже по-русски.

### Cost (Gemini 2.5-flash, по [google.dev/pricing](https://ai.google.dev/gemini-api/docs/pricing))

- Input video через File API: ≈263 input-tokens/sec видео.
- Output JSON ≈ 100 tokens/window.
- 60-минутное видео × 20 windows × 3 frames/window ≈ 60×60×263 + 20×100 = ~948k input + 2k output ≈ $0.07 на видео в free tier (бесплатно), на платном — те же копейки.
- Free tier: 15 RPM, 1500 RPD, 1M TPM. Один call на window. 1500/20 = 75 видео/день в free tier — достаточно для 99% пользователей.

### Обработка ошибок Gemini

- 403 PERMISSION_DENIED → понятный message «ключ заблокирован Google, создай новый проект в AI Studio» + exit code 5.
- 429 RATE_LIMIT → exponential backoff (3, 6, 12s), 3 попытки. Если всё ещё 429 — собираем то что успели и помечаем оставшиеся windows как `description="(rate-limited)"`. Не валим весь pipeline.
- timeout (30s/window) → пропуск окна с `description="(timeout)"`.
- Все ошибки логируются в `manifest.json` per-window.

---

## 7. Embedded screenshots в combined.md

### Структура batch-папки расширяется

```
transcripts/batch_20260510_120000_anthropic_ai/
├── combined.md                    # ← extended in v0.2
├── manifest.json                  # ← extended
├── errors.log
├── frames/                        # NEW
│   ├── jNQXAC9IVRw_00045.jpg     # <video_id>_<sec>.jpg
│   ├── jNQXAC9IVRw_00112.jpg
│   └── XYZ_00030.jpg
├── Me_at_the_zoo_jNQXAC9IVRw.txt
├── Me_at_the_zoo_jNQXAC9IVRw.srt
└── How_to_code_XYZ.txt
```

Single-режим:
```
transcripts/
├── Me_at_the_zoo_jNQXAC9IVRw.txt
├── Me_at_the_zoo_jNQXAC9IVRw.srt
├── Me_at_the_zoo_jNQXAC9IVRw.visual.md          # NEW: только если --with-visuals
└── frames/
    └── Me_at_the_zoo_jNQXAC9IVRw_*.jpg
```

### Combined.md формат с visuals

Per-video секция расширяется блоками визуальных моментов:

```markdown
## 1. Tutorial: building Claude tools

| Поле | Значение |
|---|---|
| URL | https://... |
| Video ID | jNQXAC9IVRw |
| Date | 2026-04-15 |
| Duration | 12:34 |
| Channel | Anthropic |
| Language detected | en |
| Quality score | 0.92 (manual subs) |
| Visual segments | 8 |

### Transcript

Hello and welcome to today's tutorial...

### Visual moments

#### 00:00:45 — Code editor with API call (importance: high)

![](frames/jNQXAC9IVRw_00045.jpg)

The video shows VS Code with `anthropic.messages.create(...)` call being typed.
Visible imports: `from anthropic import Anthropic`.

Trigger: `universal:function` (cosine 0.78, weight 1.5)

#### 00:01:52 — Diagram of agent loop (importance: high)

![](frames/jNQXAC9IVRw_00112.jpg)

A whiteboard diagram showing the agent loop: tool_call → execute → result → next.
```

Скриншоты — relative paths, чтобы combined.md можно было перенести вместе с папкой и оно всё работало в любом markdown-renderer'е (Obsidian, Typora, GitHub preview).

### Как Claude использует это

В SKILL.md добавляется:

> После batch с `--with-visuals`: `combined.md` содержит embedded скриншоты.
> Пользователь может попросить: «сделай туториал по этому видео» — у тебя есть и
> текст и визуальные моменты; используй timecodes для структурирования.

---

## 8. Динамические презеты + единый реестр опций

### Идея

Все настройки v0.2 — это поля в одном реестре. Каждое поле имеет: имя, тип, дефолт, допустимые значения, описание. Из реестра рендерятся:
- Дефолтный `config.toml` с комментариями над каждой опцией;
- CLI-флаги (Click options генерируются из реестра);
- TUI `youtube-transcribe config` (Rich-prompts);
- В будущем v0.4+ web UI (формы из того же реестра).

### Реестр

```python
# presets/registry.py
@dataclass(frozen=True)
class OptionField:
    key: str
    type: type
    default: Any
    choices: list[Any] | None
    description: str
    section: str   # "transcribe" | "vision" | "detection" | "smart" | "output"

REGISTRY: list[OptionField] = [
    OptionField(
        "transcribe_backend", str, "subtitles",
        choices=["subtitles", "whisper-local", "gemini", "groq", "openai",
                 "deepgram", "assemblyai", "custom"],
        description="Чем транскрибировать. Subtitles = брать готовые с YouTube.",
        section="transcribe",
    ),
    OptionField(
        "vision_backend", str, "off",
        choices=["off", "gemini"],
        description="Visual mode. Off = только аудио. Gemini = multimodal.",
        section="vision",
    ),
    OptionField(
        "detect_method", str, "keywords_only",
        choices=["keywords_only", "semantic", "hybrid", "llm_full_pass"],
        description="Как находить визуально-важные моменты.",
        section="detection",
    ),
    # ... ~30 полей всего
]
```

### Готовые презеты (`presets_default.toml`)

```toml
# === ECO ===
# Минимум cost. Пользователь сам выбирает transcribe_backend в wizard
# (whisper-local оффлайн / groq free / gemini free / subtitles only).
# Без visual mode, без OCR.
[presets.eco]
transcribe_backend = "subtitles"
fallback_backend = "whisper-local"  # перекрывается выбором в wizard
vision_backend = "off"
detect_method = "keywords_only"
quality_check = false                # экономим CPU

# === SMART ===
# Дефолт. Subtitles → quality check → fallback → опц. visuals.
# Visual mode включён, но silent fallback на off если нет GEMINI_API_KEY.
[presets.smart]
transcribe_backend = "subtitles"
fallback_backend = "whisper-local"
quality_check = true
subtitle_quality_threshold = 0.6
vision_backend = "gemini"            # silent fallback to "off" if no API key
detect_method = "hybrid"
frames_per_window = 3
max_windows_per_video = 20

# === STANDARD ===
# Visual mode на всех видео, whisper-local сразу без try-subtitles-first.
# Подходит когда хочется консистентного качества транскрипта.
[presets.standard]
transcribe_backend = "whisper-local"
vision_backend = "gemini"
detect_method = "hybrid"
frames_per_window = 3
max_windows_per_video = 30

# === PREMIUM ===
# Максимальное качество. LLM-full-pass detection, perplexity quality check,
# больше кадров.
[presets.premium]
transcribe_backend = "whisper-local"
whisper_model = "large"              # перекрывает дефолт turbo
vision_backend = "gemini"
detect_method = "llm_full_pass"
frames_per_window = 5
max_windows_per_video = 50
quality_check = true
quality_perplexity = true

# OCR (--ocr флаг) НЕ включён ни в один preset. Это отдельная функция,
# активируется явным флагом или [output] ocr = true в config.
```

### CLI и override-приоритет

```
1. CLI flag (--backend, --preset, --vision-backend, ...)
2. --config /path/to/custom.toml (если задано)
3. ~/.youtube-transcribe/config.toml [presets.<active>]
4. presets_default.toml [presets.<active>]
5. Hard-coded defaults в registry
```

`active` определяется CLI `--preset <name>` или config `default_preset = "smart"`.

### TUI `youtube-transcribe config`

```
$ youtube-transcribe config
[1] Manage API keys
[2] Edit preset
[3] Edit triggers
[4] Show current config
[5] Reset to defaults
> 2

Select preset to edit:
[1] eco       (current default)
[2] smart
[3] standard
[4] premium
[5] Create new preset (clone from existing)
> 2

Editing [presets.smart]:
  transcribe_backend = "subtitles"
  fallback_backend = "whisper-local"
  ...

Field to change (number) or [s] to save and exit:
> 4

vision_backend (off | gemini) [current: gemini]:
> off

OK. Save? [y/N]: y
Saved to ~/.youtube-transcribe/config.toml.
```

Это **не блокер для v0.2** — TUI можно сделать минимально (показ + ручная правка `config.toml`). Полноценный wizard-flow для редактирования преcетов — задача в v0.3.

### --config flag

```bash
youtube-transcribe URL --config ~/configs/aggressive-quality.toml
```

Читает указанный файл как полный config, игнорируя `~/.youtube-transcribe/config.toml`. Полезно для:
- Шеринга своих преcетов между машинами;
- Разных конфигов под разные проекты (учебные видео vs. рабочие созвоны);
- CI-сценариев.

---

## 9. CLI флаги v0.2

Новые/изменённые флаги. Полный набор будет в README.

```
--with-visuals                   shortcut для --vision-backend=gemini
--vision-backend gemini|off
--detect-method keywords_only|semantic|hybrid|llm_full_pass
--frames-per-window N            (override preset)
--max-windows N
--ocr                            enable OCR
--check-quality                  force quality check + write to manifest
--no-quality-check               skip quality check even in smart preset
--preset eco|smart|standard|premium|<custom_name>
--config /path/to/config.toml    use external config file
--triggers /path/to/triggers.toml
--no-default-triggers            disable built-in triggers, use only user
```

CLI приоритет описан в §8. Single-режим и batch принимают одинаковый набор.

---

## 10. Архитектурный seam для web UI v0.4+

В v0.2 не пишем web UI, но соблюдаем требования:

1. **`run_pipeline()` — чистая функция** без `click.echo`/`print`. Все сообщения идут через `progress: ProgressCallback` параметр.
2. **Реестр опций (`presets.registry`) — единственный источник truth** для того, какие опции существуют, как их валидировать, какие у них defaults. Web UI v0.4+ читает реестр и рендерит формы.
3. **Никакого global state** в pipeline. `Config`, `TriggerConfig`, `QualityChecker` — параметры функций, не модули с module-level state. Так несколько pipeline-ов параллельно (что web UI потребует) не наступают друг другу на ноги.
4. **Все side-effects (файлы, сеть) — через injected dependencies**. `Downloader`, `Transcriber`, `VisionBackend`, `QualityChecker` принимаются как параметры конструктора `Pipeline` (или функции `run_pipeline`).

Это не прибавляет работы в v0.2, потому что v0.1 уже почти соответствует. Просто формализуем.

---

## 11. Тестирование

### Unit (CI на 3 ОС × 2 Python)

- `quality/spell.py` — мок словаря, проверка OOV ratio на синтетике.
- `quality/repetition.py` — синтетические циклы, разные длины.
- `quality/boh.py` — golden BoH list, проверка точного матчинга.
- `quality/heuristic_checker.py` — композитный score на 6 синтетических кейсах (good manual, good auto, mostly_music, looped, garbled, mixed).
- `detection/matcher.py` — мок embedding-encoder (deterministic stub), проверка raw/strict/soft/universal путей.
- `detection/triggers.py` — load + merge + override TOML.
- `vision/gemini.py` — мок Gemini-клиента, проверка batch-call'ов и parsing JSON.
- `presets/registry.py` — все поля имеют валидный default из choices.

### Integration (CI без сети)

- Полный pipeline на fixture (mp4 + готовый whisper-output) → проверка structure manifest, combined.md, frames/.
- Пресеты: eco/smart/standard/premium прогоняются, проверяется что нужные stage активированы.

### E2E smoke (RUN_E2E_SMOKE=1, manual)

- Реальный 19-секундный YouTube-ролик с visual mode на free Gemini key.
- Проверка: combined.md содержит ≥1 visual moment, frames/ непустой.

### Golden set для quality check калибровки

30 видео разных типов (подбираются вручную):
- 10 с manual subs (ожидаемо score ≈ 1.0)
- 5 с хорошими auto-subs (score 0.7-0.9)
- 5 с посредственными auto-subs (0.4-0.7)
- 5 с мусорными auto-subs или whisper-loops (< 0.3)
- 5 музыкальных (флаг `mostly_music`)

На этом наборе подбираем веса в композитной формуле и threshold по умолчанию. Результат — фиксированный JSON с ожидаемыми scores в `tests/data/quality_golden.json`. CI прогоняет проверку «ни один golden не дрейфанул больше чем на 0.1».

---

## 12. Backward compatibility

v0.1.x → v0.2 — пользователь:
- Существующий `~/.youtube-transcribe/config.toml` читается без изменений; новые поля с дефолтами добавляются при первом сохранении v0.2.
- Существующие `combined.md` и `manifest.json` остаются совместимыми — v0.2 только **добавляет** поля (`quality`, `visual_segments`), не меняет старые.
- `youtube-transcribe URL` без флагов → ведёт себя как раньше (subtitles → fallback whisper-local), потому что `presets.smart` — дефолт, и vision off (preset default = `vision_backend = "off"` в smart? — НЕТ, в smart vision_backend=gemini, см. §8).

**Решение по дефолтному поведению smart:** в smart по умолчанию `vision_backend = "gemini"`, но visual mode активируется **только если у пользователя есть Gemini key**. Если ключа нет — silent fallback на `vision_backend = "off"` с info-сообщением «set GEMINI_API_KEY to enable visual mode». То есть пользователь без Gemini получает то же поведение что в v0.1, плюс quality check.

Это решает «не сломать существующих юзеров» без необходимости инвазивной миграции.

---

## 13. Migration plan v0.1.x → v0.2

1. На первом запуске v0.2 — детектим старый `config.toml`. Если в нём нет поля `default_preset` — добавляем `default_preset = "smart"` и проставляем существующие поля (`whisper_model`, `language` etc.) в `[presets.custom_legacy]`, делаем его дефолтом. Чтобы пользователь, который правил конфиг руками, получил эквивалентное поведение.
2. Если есть Gemini key и `default_preset = "smart"` → показываем info-сообщение «v0.2 added visual mode. Try `--with-visuals`».
3. Старый wizard (`config wizard`) запускается заново только если пользователь явно вызвал — не показываем insistently.

---

## 14. Roadmap дальше

| v0.3 | Фильтры канала (`--since`, `--until`, `--no-shorts`), `--workers N`, `--skip-existing`, search by tags (`batch --search`), TUI редактор преcетов |
| v0.4 | Web UI (Gradio или FastAPI+vanilla), Instagram backend, ASR error correction через LLM, Visual mode на других multimodal моделях (Claude vision, GPT-4o) |
| v1.x | Diarization, потоковый режим, локальная LLM для саммари |

---

## 15. Решения по открытым вопросам (закрыто)

1. **Дефолт smart-преcета**: visual on с silent fallback. Если у пользователя есть `GEMINI_API_KEY` → visual mode работает. Если нет — тихо отключается с info-сообщением. Не блокирует основной pipeline.
2. **Built-in triggers**: только EN universal (≈25 фраз). Raw НЕ включён по умолчанию — пользователь добавляет сам через `triggers add --raw "..."` если нужен. Меньше навязывания, чище дефолт.
3. **OCR**: отдельная функция через флаг `--ocr` (или `[output] ocr = true`). **Off везде**, не зашит ни в один preset. Решает пользователь когда захочет.
4. **Скриншоты для видео с плохим транскриптом**: показываем всегда. Картинки реальные даже если текст мусор — могут пригодиться. Помечаем importance в каждом visual moment.
5. **Quality `low_quality` recommendation**: warning в combined.md, **НЕ failure**. Видео не дропается, не идёт в `errors.log`. Failure — только при технических ошибках (пустой транскрипт, упавший download, мёртвый API).

Quality check — диагностический инструмент для выбора источника (subtitles vs whisper), а не фильтр результатов. Финальный output идёт в файлы всегда.

---

## 16. Triggers CLI tool

Чтобы пользователь не редактировал TOML руками — встроенный CLI для управления `triggers.toml`. Парсит фразы через `;` или `,`, кладёт в нужную секцию, валидирует, дедупит, atomic save.

### Команды

```
youtube-transcribe triggers init [--force]
  Создаёт ~/.youtube-transcribe/triggers.toml с пустыми секциями и
  комментариями-подсказками над каждой. --force перезаписывает существующий.

youtube-transcribe triggers add --universal "look here; pay attention; demo time"
  Парсит phrases по ;/, чистит пробелы, добавляет в [triggers.universal].phrases.
  Дубликаты игнорируются (печать "already exists").

youtube-transcribe triggers add --raw "this is fine; TODO; FIXME"
  В [triggers.raw].phrases. Точное совпадение, любой язык.

youtube-transcribe triggers add --soft --lang ru "смотри сюда; вот тут код"
  В [triggers.languages.ru].soft. Совпадение по леммам.

youtube-transcribe triggers add --strict --lang ru "баг; PR; коммит"
  В [triggers.languages.ru].strict. Точное совпадение в указанном языке.

youtube-transcribe triggers weight set --universal "function" 1.5
youtube-transcribe triggers weight set --raw "TODO" 2.0
youtube-transcribe triggers weight set --strict --lang ru "PR" 2.0
  Поднимает (или опускает) вес фразы. Запись в TOML
  превращается из "function" в ["function", 1.5]. Дефолт = 1.0.
  Применяется при сортировке окон при превышении max_windows_per_video.

youtube-transcribe triggers weight set --universal "function:1.5; class:1.5; method:1.5"
  Батч — формат фраза:вес через ;. Удобно вешать веса сразу группе.

youtube-transcribe triggers weight unset --universal "function"
  Сбрасывает вес обратно к 1.0 — запись становится обычной строкой.

youtube-transcribe triggers weight list
  Печатает только non-default веса (всё что в []-форме).

youtube-transcribe triggers list [--section <name>]
  Печатает все секции и фразы в форматированной таблице (Rich).
  --section фильтрует.

youtube-transcribe triggers remove --universal "phrase"
youtube-transcribe triggers remove --strict --lang ru "phrase"
  Удаляет конкретную фразу из секции. Печатает что удалили.

youtube-transcribe triggers reset --universal
youtube-transcribe triggers reset --all
  Сбрасывает указанную секцию (или весь файл) к built-in defaults.

youtube-transcribe triggers edit
  Открывает triggers.toml в $EDITOR (default — vi на Unix, notepad на Windows).
  После выхода парсит TOML — если синтаксическая ошибка, восстанавливает backup
  и печатает строку с ошибкой.

youtube-transcribe triggers test "Привет, смотри сюда — это важно"
  Прогоняет фразу через matcher, печатает какие триггеры сработали и через
  какой метод. Полезно для отладки своих кастомных фраз.
```

### Реализация

- Click sub-group в `transcribe.py` (как `config` уже есть в v0.1).
- Парсер фраз: `re.split(r"[;,]", input_str)` → strip → отбрасываем пустые.
- Валидация: фраза не короче 2 символов и не длиннее 200. Нельзя добавить пустую.
- Сохранение: atomic write через `os.replace` (как `config.toml` в v0.1).
- Comments preservation: используем `tomlkit` вместо `tomli_w` для CLI-тула, чтобы пользовательские комментарии в `triggers.toml` не терялись при редактировании. (`tomli_w` пишет голый TOML без комментариев.) Новая зависимость, ~50KB.
- Dедуп: case-sensitive по умолчанию (раз пользователь так написал — значит хотел), флаг `--ignore-case` для case-insensitive дедупа.

### Конфликты и валидация

Tool печатает warning при подозрительных конфликтах:
- Фраза в `raw` (любой язык) уже есть в `universal` → warning «raw сильнее, universal не сработает».
- Фраза в `languages.<lang>.strict` дублирует `languages.<lang>.soft` → warning «strict победит soft на этом языке».
- Очень короткая universal-фраза (1 слово, < 4 буквы) → warning «короткая фраза в universal даст много false-positives через embeddings, рассмотри strict».

Это не блокирует операцию, просто советует.

### Где живёт built-in default

`skills/youtube_transcribe/detection/data/triggers_default.toml` — read-only, поставляется с пакетом. Read-merged при загрузке (не копируется в `~/.youtube-transcribe/triggers.toml`). Юзерский файл — **только override и дополнения**, чтобы при `triggers reset` мы могли откатиться к built-in без потери информации.

При `triggers add` если юзерский файл не существует — создаём его автоматически (не нужно отдельного `init`).

---

## 17. Объём работы (оценка)

- **Quality check**: 4-5 файлов, ~600 LOC + ~400 LOC тестов. 1.5 дня.
- **Triggers (matcher + загрузка + embedder)**: 3-4 файла, ~500 LOC + multilingual encoder integration + ~300 LOC тестов. 1 день.
- **Triggers CLI tool (init/add/list/remove/reset/edit/test)**: 2 файла, ~350 LOC + ~250 LOC тестов. 0.5 дня.
- **Detection (windows + scene + frame-diff)**: 4 файла, ~400 LOC + ~250 LOC тестов. 1 день.
- **Vision backend (Gemini)**: 3 файла, ~350 LOC + ~250 LOC тестов с mock-клиентом. 1 день.
- **Presets registry + CLI rewiring**: 2 файла, ~400 LOC + ~200 LOC тестов. 0.5 дня.
- **Output (embedded screenshots, extended combined.md)**: правка существующего `output_writer.py`, ~200 LOC + 100 LOC тестов. 0.5 дня.
- **OCR (опц. флаг `--ocr`)**: 1 файл, ~150 LOC + ~100 LOC тестов с моком pytesseract. 0.5 дня.
- **Migration + backward compat**: 1 файл, ~150 LOC + ~150 LOC тестов. 0.5 дня.
- **Документация (README, SKILL.md, CHANGELOG)**: 0.5 дня.
- **Real validation на Mac** (как в v0.1.2): 0.5-1 день.

Итого **~7-8 рабочих дней** до v0.2 release-candidate.
