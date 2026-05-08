# youtube-transcribe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать переиспользуемый skill `youtube-transcribe`: транскрибация YouTube/локальных медиа через 8 взаимозаменяемых бэкендов с дефолтом на локальный Whisper, first-run wizard, slash-команда, три способа установки, готовность к публикации в GitHub и валидации на Mac.

**Architecture:** Python-проект с абстракцией `Transcriber` (Protocol). Каждый бэкенд — один файл, реализующий интерфейс. CLI на Click с sub-командами. Конфиг — `~/.youtube-transcribe/config.toml` + `.env`. Тесты — pytest, моки на subprocess/SDK. Дистрибуция: Claude Code plugin, личный skill, uv tool — один репо обслуживает все три.

**Tech Stack:** Python 3.10+, uv, Click, Rich, faster-whisper, mlx-whisper, yt-dlp, youtube-transcript-api, google-genai, groq, openai, deepgram-sdk, assemblyai, pytest, tomli, python-dotenv.

**Spec:** `docs/specs/2026-05-08-youtube-transcribe-design.md`

---

## Структура файлов и порядок задач

```
youtube-transcribe/
├── .claude-plugin/plugin.json            ← Task 3
├── skills/youtube-transcribe/
│   ├── SKILL.md                          ← Task 22
│   ├── transcribe.py                     ← Task 20-21
│   ├── wizard.py                         ← Task 19
│   ├── config.py                         ← Task 6
│   ├── backends/
│   │   ├── base.py                       ← Task 8
│   │   ├── whisper_local.py              ← Task 9-10
│   │   ├── subtitles.py                  ← Task 11
│   │   ├── gemini.py                     ← Task 12
│   │   ├── groq.py                       ← Task 13
│   │   ├── openai_api.py                 ← Task 14
│   │   ├── deepgram.py                   ← Task 15
│   │   ├── assemblyai.py                 ← Task 16
│   │   └── custom.py                     ← Task 17
│   └── utils/
│       ├── platform_detect.py            ← Task 4
│       ├── output_writer.py              ← Task 5
│       └── downloader.py                 ← Task 7
├── commands/transcribe.md                ← Task 23
├── pyproject.toml                        ← Task 1
├── README.md                             ← Task 24
├── install.ps1                           ← Task 25
├── install.sh                            ← Task 25
├── .gitignore                            ← Task 2
├── LICENSE                               ← Task 2
└── tests/                                ← создаётся в Task 4 и далее
```

Phases:
- **Phase 1 (Tasks 1–3):** Repo bootstrap.
- **Phase 2 (Tasks 4–8):** Foundations — utils + backend interface.
- **Phase 3 (Tasks 9–17):** Backends — все 8.
- **Phase 4 (Tasks 18–21):** Сборка — composition, CLI, wizard.
- **Phase 5 (Tasks 22–25):** Claude Code интеграция и документация.
- **Phase 6 (Tasks 26–27):** Smoke-тест и handoff на Mac.
- **Phase 7 (Tasks 28–30):** Mac validation. Выполняется на Mac после `git pull`.

---

## Pre-flight (один раз перед началом)

- [ ] Проверить, что текущая директория — `E:\CLAUDE\youtube-transcribe` и git init уже сделан (commit `9a177ae` или новее видим в `git log`).
- [ ] Проверить наличие `uv`. Если нет — установить:
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
  Затем перезапустить shell, проверить: `uv --version` (ожидается `0.4+`).

---

# Phase 1 — Repo bootstrap

### Task 1: pyproject.toml — манифест проекта

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Создать pyproject.toml**

```toml
[project]
name = "youtube-transcribe"
version = "0.1.0"
description = "Transcribe YouTube videos and local media via 8 interchangeable backends (Whisper local / subtitles / Gemini / Groq / OpenAI / Deepgram / AssemblyAI / custom)."
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [{ name = "youtube-transcribe contributors" }]
keywords = ["whisper", "transcription", "youtube", "claude-code", "skill"]

dependencies = [
    "click>=8.1",
    "rich>=13.7",
    "tomli>=2.0; python_version < '3.11'",
    "tomli-w>=1.0",
    "python-dotenv>=1.0",
    "yt-dlp>=2024.10.0",
    "youtube-transcript-api>=0.6.2",
    # Cloud SDKs (small, install all by default)
    "google-genai>=0.3.0",
    "groq>=0.11.0",
    "openai>=1.50.0",
    "deepgram-sdk>=3.7.0",
    "assemblyai>=0.34.0",
    # Local Whisper — Windows/Linux/Intel-Mac path
    "faster-whisper>=1.0.3",
    # Apple Silicon path (only installs on macOS arm64)
    "mlx-whisper>=0.4.1; sys_platform == 'darwin' and platform_machine == 'arm64'",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[project.scripts]
youtube-transcribe = "skills.youtube_transcribe.transcribe:cli"

[build-system]
requires = ["hatchling>=1.24"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["skills/youtube_transcribe"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --tb=short"
```

- [ ] **Step 2: Создать пустой `__init__.py` для пакета**

```bash
mkdir -p skills/youtube_transcribe
touch skills/youtube_transcribe/__init__.py
```

Содержимое `skills/youtube_transcribe/__init__.py`:

```python
"""youtube-transcribe — universal transcription skill."""
__version__ = "0.1.0"
```

> **Замечание о пути:** в спеке папка называется `skills/youtube-transcribe/` (через дефис). В Python пакет должен быть с подчёркиванием: `skills/youtube_transcribe/`. Используем `youtube_transcribe` для импортов и `youtube-transcribe` для имени пакета/CLI/skill.

- [ ] **Step 3: Установить зависимости через uv**

Run: `uv sync --extra dev`
Expected: создаётся `.venv/`, ставятся пакеты, не падает.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml skills/youtube_transcribe/__init__.py
git commit -m "build: add pyproject.toml with dependencies and uv sync"
```

---

### Task 2: .gitignore + LICENSE

**Files:**
- Create: `.gitignore`
- Create: `LICENSE`

- [ ] **Step 1: Создать .gitignore**

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
build/
dist/
.venv/
venv/

# Tests
.pytest_cache/
.coverage
htmlcov/

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# User config (НЕ коммитить ни в коем случае)
.env
*.env.local

# Output (не нужно в репо)
transcripts/
*.srt
*.txt
!docs/**/*.txt
!README*.txt

# uv
.python-version
uv.lock
```

> uv.lock закомментирую — обычно его коммитят, но для skill'а с разными платформами он только мешает (pin'ит версии под платформу автора). Пользователи делают `uv sync` сами и получают свежие резолвы.

- [ ] **Step 2: Создать LICENSE (MIT)**

```
MIT License

Copyright (c) 2026 youtube-transcribe contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore LICENSE
git commit -m "chore: add .gitignore and MIT LICENSE"
```

---

### Task 3: plugin.json — Claude Code plugin manifest

**Files:**
- Create: `.claude-plugin/plugin.json`

- [ ] **Step 1: Создать .claude-plugin/plugin.json**

```bash
mkdir -p .claude-plugin
```

```json
{
  "name": "youtube-transcribe",
  "version": "0.1.0",
  "description": "Transcribe YouTube videos and local media via 8 interchangeable backends with offline default.",
  "author": {
    "name": "youtube-transcribe contributors"
  },
  "license": "MIT",
  "homepage": "https://github.com/<user>/youtube-transcribe",
  "skills": [
    "skills/youtube-transcribe"
  ],
  "commands": [
    "commands/transcribe.md"
  ]
}
```

> Замечание: в плагине skill называется через дефис (`skills/youtube-transcribe`) — это имя папки. Symlink/копия `skills/youtube_transcribe` → `skills/youtube-transcribe` сделаем в Task 22 (когда будет SKILL.md). Пока папка с подчёркиванием существует только для Python-импортов.

> **На самом деле:** проще держать одну папку с подчёркиванием и в `plugin.json` указать её. Claude Code не требует дефиса в имени папки. Изменим путь:

Финальный JSON:

```json
{
  "name": "youtube-transcribe",
  "version": "0.1.0",
  "description": "Transcribe YouTube videos and local media via 8 interchangeable backends with offline default.",
  "author": {
    "name": "youtube-transcribe contributors"
  },
  "license": "MIT",
  "homepage": "https://github.com/<user>/youtube-transcribe",
  "skills": [
    "skills/youtube_transcribe"
  ],
  "commands": [
    "commands/transcribe.md"
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "feat: add Claude Code plugin manifest"
```

---

# Phase 2 — Foundations (utils + backend interface)

### Task 4: utils/platform_detect.py — auto-detect OS/GPU/VRAM

**Files:**
- Create: `skills/youtube_transcribe/utils/__init__.py`
- Create: `skills/youtube_transcribe/utils/platform_detect.py`
- Create: `tests/__init__.py`
- Create: `tests/test_platform_detect.py`

- [ ] **Step 1: Создать пустой `__init__.py`**

```bash
mkdir -p skills/youtube_transcribe/utils tests
touch skills/youtube_transcribe/utils/__init__.py tests/__init__.py
```

- [ ] **Step 2: Написать failing-test**

`tests/test_platform_detect.py`:

```python
from unittest.mock import patch
from skills.youtube_transcribe.utils.platform_detect import detect_platform, PlatformInfo


def test_apple_silicon_returns_mlx():
    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"):
        info = detect_platform()
    assert info.backend_impl == "mlx"
    assert info.device == "mps"
    assert info.label == "apple-silicon"


def test_windows_with_nvidia_returns_faster_whisper_cuda():
    fake_run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "24564"})()
    with patch("platform.system", return_value="Windows"), \
         patch("platform.machine", return_value="AMD64"), \
         patch("subprocess.run", side_effect=[
             type("R", (), {"returncode": 0, "stdout": ""})(),
             type("R", (), {"returncode": 0, "stdout": "24564\n"})(),
         ]):
        info = detect_platform()
    assert info.backend_impl == "faster"
    assert info.device == "cuda"
    assert info.vram_mb == 24564
    assert info.label == "nvidia"


def test_no_gpu_falls_back_to_cpu():
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        info = detect_platform()
    assert info.backend_impl == "faster"
    assert info.device == "cpu"
    assert info.label == "cpu-only"


def test_compute_type_for_high_vram_is_float16():
    fake_run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "24564\n"})()
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"), \
         patch("subprocess.run", side_effect=[
             type("R", (), {"returncode": 0, "stdout": ""})(),
             type("R", (), {"returncode": 0, "stdout": "24564\n"})(),
         ]):
        info = detect_platform()
    assert info.recommended_compute_type == "float16"


def test_compute_type_for_low_vram_is_int8_float16():
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"), \
         patch("subprocess.run", side_effect=[
             type("R", (), {"returncode": 0, "stdout": ""})(),
             type("R", (), {"returncode": 0, "stdout": "4096\n"})(),
         ]):
        info = detect_platform()
    assert info.recommended_compute_type == "int8_float16"
```

- [ ] **Step 3: Run tests, verify FAIL**

Run: `uv run pytest tests/test_platform_detect.py -v`
Expected: 5 FAIL, "ModuleNotFoundError: No module named 'skills.youtube_transcribe.utils.platform_detect'"

- [ ] **Step 4: Implement platform_detect.py**

```python
"""Auto-detect OS, GPU, VRAM to pick the right Whisper implementation."""
from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PlatformInfo:
    label: Literal["apple-silicon", "nvidia", "cpu-only"]
    backend_impl: Literal["mlx", "faster"]
    device: Literal["mps", "cuda", "cpu"]
    vram_mb: int | None
    recommended_compute_type: Literal["float16", "int8_float16", "int8", "auto"]


def _query_nvidia_vram_mb() -> int | None:
    """Returns total VRAM in MiB if nvidia-smi works, else None."""
    try:
        # Probe: does nvidia-smi exist?
        subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            timeout=2,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        first_line = (result.stdout or "").strip().splitlines()[0]
        return int(first_line.strip())
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def detect_platform() -> PlatformInfo:
    system = platform.system()
    machine = platform.machine()

    # macOS Apple Silicon → mlx-whisper
    if system == "Darwin" and machine == "arm64":
        return PlatformInfo(
            label="apple-silicon",
            backend_impl="mlx",
            device="mps",
            vram_mb=None,
            recommended_compute_type="auto",
        )

    # NVIDIA on Windows/Linux → faster-whisper + CUDA
    vram_mb = _query_nvidia_vram_mb()
    if vram_mb is not None:
        if vram_mb >= 6 * 1024:
            compute = "float16"
        else:
            compute = "int8_float16"
        return PlatformInfo(
            label="nvidia",
            backend_impl="faster",
            device="cuda",
            vram_mb=vram_mb,
            recommended_compute_type=compute,
        )

    # Fallback: CPU
    return PlatformInfo(
        label="cpu-only",
        backend_impl="faster",
        device="cpu",
        vram_mb=None,
        recommended_compute_type="int8",
    )
```

- [ ] **Step 5: Run tests, verify PASS**

Run: `uv run pytest tests/test_platform_detect.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add skills/youtube_transcribe/utils/__init__.py skills/youtube_transcribe/utils/platform_detect.py tests/__init__.py tests/test_platform_detect.py
git commit -m "feat(utils): platform detection (OS / NVIDIA / Apple Silicon / CPU)"
```

---

### Task 5: utils/output_writer.py — .txt and .srt formatters

**Files:**
- Create: `skills/youtube_transcribe/utils/output_writer.py`
- Create: `tests/test_output_writer.py`

- [ ] **Step 1: Failing-test**

`tests/test_output_writer.py`:

```python
from pathlib import Path
from skills.youtube_transcribe.utils.output_writer import (
    Segment,
    write_txt_with_timestamps,
    write_txt_plain,
    write_srt,
    format_timestamp_srt,
    sanitize_filename,
)


def make_segments():
    return [
        Segment(start=0.0, end=2.5, text="Hello world."),
        Segment(start=2.5, end=5.0, text="Second segment."),
        Segment(start=8.0, end=10.0, text="After 3 second pause."),
    ]


def test_format_timestamp_srt_zero():
    assert format_timestamp_srt(0.0) == "00:00:00,000"


def test_format_timestamp_srt_with_ms():
    assert format_timestamp_srt(3725.123) == "01:02:05,123"


def test_write_txt_with_timestamps(tmp_path: Path):
    segs = make_segments()
    path = tmp_path / "out.txt"
    write_txt_with_timestamps(segs, path)
    text = path.read_text(encoding="utf-8")
    assert "[00:00:00.000 --> 00:00:02.500] Hello world." in text
    assert "[00:00:02.500 --> 00:00:05.000] Second segment." in text


def test_write_txt_plain_paragraphs_after_long_pause(tmp_path: Path):
    segs = make_segments()
    path = tmp_path / "out.txt"
    write_txt_plain(segs, path)
    text = path.read_text(encoding="utf-8")
    # 3-sec pause between seg 2 and seg 3 should split paragraph
    assert "\n\n" in text
    assert text.count("\n\n") >= 1


def test_write_srt_format(tmp_path: Path):
    segs = make_segments()
    path = tmp_path / "out.srt"
    write_srt(segs, path)
    text = path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:02,500"
    assert lines[2] == "Hello world."
    assert "" in lines  # blank between blocks


def test_sanitize_filename_strips_special_chars():
    assert sanitize_filename("Hello, World! [Official] / 2026?") == "Hello_World_Official_2026"


def test_sanitize_filename_unicode_ok():
    assert sanitize_filename("Привет мир") == "Привет_мир"
```

- [ ] **Step 2: Run, verify FAIL**

Run: `uv run pytest tests/test_output_writer.py -v`
Expected: ImportError / 6 fails.

- [ ] **Step 3: Implement output_writer.py**

```python
"""Format transcription segments into .txt and .srt files."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PARAGRAPH_PAUSE_SECONDS = 2.0
PARAGRAPH_AFTER_N_SEGMENTS = 5


@dataclass(frozen=True)
class Segment:
    start: float  # seconds
    end: float
    text: str


def _format_timestamp_dotted(seconds: float) -> str:
    """01:02:03.456 — used in .txt with timestamps."""
    if seconds < 0:
        seconds = 0.0
    hh = int(seconds // 3600)
    mm = int((seconds % 3600) // 60)
    ss_full = seconds - hh * 3600 - mm * 60
    ss = int(ss_full)
    ms = int(round((ss_full - ss) * 1000))
    if ms == 1000:
        ss += 1
        ms = 0
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"


def format_timestamp_srt(seconds: float) -> str:
    """01:02:03,456 — used in .srt (note comma)."""
    return _format_timestamp_dotted(seconds).replace(".", ",")


def write_txt_with_timestamps(segments: Iterable[Segment], path: Path) -> None:
    lines = [
        f"[{_format_timestamp_dotted(s.start)} --> {_format_timestamp_dotted(s.end)}] {s.text.strip()}"
        for s in segments
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_txt_plain(segments: Iterable[Segment], path: Path) -> None:
    """Plain text, paragraph breaks on 2+ second pauses or every 5 segments."""
    segs = list(segments)
    if not segs:
        path.write_text("", encoding="utf-8")
        return

    paragraphs: list[list[str]] = [[]]
    last_end = segs[0].start
    in_para_count = 0

    for s in segs:
        gap = s.start - last_end
        if (gap >= PARAGRAPH_PAUSE_SECONDS or in_para_count >= PARAGRAPH_AFTER_N_SEGMENTS) and paragraphs[-1]:
            paragraphs.append([])
            in_para_count = 0
        paragraphs[-1].append(s.text.strip())
        last_end = s.end
        in_para_count += 1

    text = "\n\n".join(" ".join(p) for p in paragraphs if p)
    path.write_text(text + "\n", encoding="utf-8")


def write_srt(segments: Iterable[Segment], path: Path) -> None:
    blocks: list[str] = []
    for i, s in enumerate(segments, start=1):
        blocks.append(
            f"{i}\n"
            f"{format_timestamp_srt(s.start)} --> {format_timestamp_srt(s.end)}\n"
            f"{s.text.strip()}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")


_SAFE_NAME_RE = re.compile(r"[^\wЀ-ӿ\-]+", re.UNICODE)


def sanitize_filename(name: str) -> str:
    """Keep letters/digits/Cyrillic/-/_, collapse everything else into _."""
    cleaned = _SAFE_NAME_RE.sub("_", name).strip("_")
    return cleaned or "transcript"
```

- [ ] **Step 4: Run, verify PASS**

Run: `uv run pytest tests/test_output_writer.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/utils/output_writer.py tests/test_output_writer.py
git commit -m "feat(utils): output writer for .txt (with/without timestamps) and .srt"
```

---

### Task 6: config.py — load/save config.toml + .env, secrets handling

**Files:**
- Create: `skills/youtube_transcribe/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Failing-test**

`tests/test_config.py`:

```python
from pathlib import Path
import os
from unittest.mock import patch

from skills.youtube_transcribe.config import (
    Config,
    load_config,
    save_config,
    get_api_key,
    set_api_key,
    mask_key,
    DEFAULT_CONFIG,
)


def test_default_config_has_whisper_local_default():
    assert DEFAULT_CONFIG.default_backend == "whisper-local"
    assert DEFAULT_CONFIG.fallback_backend == "whisper-local"


def test_save_and_load_roundtrip(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg = Config(
        default_backend="gemini",
        fallback_backend="whisper-local",
        whisper_model="large",
        gemini_model="gemini-2.5-pro",
        groq_model="whisper-large-v3-turbo",
        openai_model="whisper-1",
        deepgram_model="nova-3",
        assemblyai_model="best",
        custom_base_url="",
        custom_model="",
        whisper_device="auto",
        whisper_compute_type="auto",
        beam_size=5,
        vad=True,
        language="auto",
        timestamps=True,
        srt=True,
        output_dir="./transcripts",
        keep_audio=False,
        yt_dlp_auto_update=True,
        cookies_browser="",
        fast_path_enabled=True,
    )
    save_config(cfg, cfg_path)
    loaded = load_config(cfg_path)
    assert loaded == cfg


def test_load_missing_file_returns_default(tmp_path: Path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg == DEFAULT_CONFIG


def test_get_api_key_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-value")
    assert get_api_key("gemini", env_path=tmp_path / ".env") == "env-value"


def test_get_api_key_from_env_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("GROQ_API_KEY=file-value\n")
    assert get_api_key("groq", env_path=env_path) == "file-value"


def test_set_api_key_writes_env(tmp_path: Path):
    env_path = tmp_path / ".env"
    set_api_key("openai", "sk-test", env_path=env_path)
    content = env_path.read_text()
    assert "OPENAI_API_KEY=sk-test" in content


def test_mask_key_short():
    assert mask_key("ab") == "***"


def test_mask_key_long():
    masked = mask_key("sk-1234567890abcdef")
    assert masked.startswith("sk-")
    assert masked.endswith("cdef")
    assert "*" in masked
```

- [ ] **Step 2: Run, verify FAIL**

Run: `uv run pytest tests/test_config.py -v`

- [ ] **Step 3: Implement config.py**

```python
"""Config loading/saving and API key handling.

Config layout (TOML):
  ~/.youtube-transcribe/config.toml — non-secret defaults
  ~/.youtube-transcribe/.env        — API keys (NOT committed, perms 0600)

API key precedence:
  1. process env var
  2. ~/.youtube-transcribe/.env
  3. None (caller must handle)
"""
from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w
from dotenv import dotenv_values

CONFIG_DIR = Path.home() / ".youtube-transcribe"
CONFIG_PATH = CONFIG_DIR / "config.toml"
ENV_PATH = CONFIG_DIR / ".env"

BackendName = Literal[
    "smart", "subtitles", "whisper-local",
    "gemini", "groq", "openai", "deepgram", "assemblyai", "custom",
]
WhisperModel = Literal["turbo", "large", "medium", "small", "distil"]


@dataclass
class Config:
    default_backend: BackendName = "whisper-local"
    fallback_backend: BackendName = "whisper-local"

    whisper_model: WhisperModel = "turbo"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    beam_size: int = 5
    vad: bool = True

    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "whisper-large-v3-turbo"
    openai_model: str = "whisper-1"
    deepgram_model: str = "nova-3"
    assemblyai_model: str = "best"
    custom_base_url: str = ""
    custom_model: str = ""

    language: str = "auto"
    timestamps: bool = True
    srt: bool = True
    output_dir: str = "./transcripts"

    keep_audio: bool = False
    yt_dlp_auto_update: bool = True
    cookies_browser: str = ""
    fast_path_enabled: bool = True


DEFAULT_CONFIG = Config()


_BACKEND_ENV_VAR = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
    "assemblyai": "ASSEMBLYAI_API_KEY",
    "custom": "CUSTOM_API_KEY",
}


def _to_toml_dict(cfg: Config) -> dict:
    """Pack Config into nested dict matching the spec layout."""
    d = asdict(cfg)
    return {
        "default_backend": d["default_backend"],
        "fallback_backend": d["fallback_backend"],
        "whisper-local": {
            "model": d["whisper_model"],
            "device": d["whisper_device"],
            "compute_type": d["whisper_compute_type"],
            "beam_size": d["beam_size"],
            "vad": d["vad"],
        },
        "gemini": {"model": d["gemini_model"]},
        "groq": {"model": d["groq_model"]},
        "openai": {"model": d["openai_model"]},
        "deepgram": {"model": d["deepgram_model"]},
        "assemblyai": {"model": d["assemblyai_model"]},
        "custom": {"base_url": d["custom_base_url"], "model": d["custom_model"]},
        "output": {
            "language": d["language"],
            "timestamps": d["timestamps"],
            "srt": d["srt"],
            "output_dir": d["output_dir"],
        },
        "behavior": {
            "keep_audio": d["keep_audio"],
            "yt_dlp_auto_update": d["yt_dlp_auto_update"],
            "cookies_browser": d["cookies_browser"],
            "fast_path_enabled": d["fast_path_enabled"],
        },
    }


def _from_toml_dict(d: dict) -> Config:
    wl = d.get("whisper-local", {})
    out = d.get("output", {})
    beh = d.get("behavior", {})
    return Config(
        default_backend=d.get("default_backend", DEFAULT_CONFIG.default_backend),
        fallback_backend=d.get("fallback_backend", DEFAULT_CONFIG.fallback_backend),
        whisper_model=wl.get("model", DEFAULT_CONFIG.whisper_model),
        whisper_device=wl.get("device", DEFAULT_CONFIG.whisper_device),
        whisper_compute_type=wl.get("compute_type", DEFAULT_CONFIG.whisper_compute_type),
        beam_size=wl.get("beam_size", DEFAULT_CONFIG.beam_size),
        vad=wl.get("vad", DEFAULT_CONFIG.vad),
        gemini_model=d.get("gemini", {}).get("model", DEFAULT_CONFIG.gemini_model),
        groq_model=d.get("groq", {}).get("model", DEFAULT_CONFIG.groq_model),
        openai_model=d.get("openai", {}).get("model", DEFAULT_CONFIG.openai_model),
        deepgram_model=d.get("deepgram", {}).get("model", DEFAULT_CONFIG.deepgram_model),
        assemblyai_model=d.get("assemblyai", {}).get("model", DEFAULT_CONFIG.assemblyai_model),
        custom_base_url=d.get("custom", {}).get("base_url", ""),
        custom_model=d.get("custom", {}).get("model", ""),
        language=out.get("language", DEFAULT_CONFIG.language),
        timestamps=out.get("timestamps", DEFAULT_CONFIG.timestamps),
        srt=out.get("srt", DEFAULT_CONFIG.srt),
        output_dir=out.get("output_dir", DEFAULT_CONFIG.output_dir),
        keep_audio=beh.get("keep_audio", DEFAULT_CONFIG.keep_audio),
        yt_dlp_auto_update=beh.get("yt_dlp_auto_update", DEFAULT_CONFIG.yt_dlp_auto_update),
        cookies_browser=beh.get("cookies_browser", DEFAULT_CONFIG.cookies_browser),
        fast_path_enabled=beh.get("fast_path_enabled", DEFAULT_CONFIG.fast_path_enabled),
    )


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return DEFAULT_CONFIG
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return _from_toml_dict(data)


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tomli_w.dumps(_to_toml_dict(cfg)).encode("utf-8"))


def get_api_key(backend: str, env_path: Path = ENV_PATH) -> str | None:
    var = _BACKEND_ENV_VAR.get(backend)
    if not var:
        return None
    # 1. process env
    val = os.environ.get(var)
    if val:
        return val
    # 2. ~/.youtube-transcribe/.env
    if env_path.exists():
        values = dotenv_values(env_path)
        v = values.get(var)
        if v:
            return v
    return None


def set_api_key(backend: str, value: str, env_path: Path = ENV_PATH) -> None:
    var = _BACKEND_ENV_VAR.get(backend)
    if not var:
        raise ValueError(f"Unknown backend for env var: {backend}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if env_path.exists():
        existing = dict(dotenv_values(env_path))
    existing[var] = value

    lines = [f"{k}={v}" for k, v in existing.items() if v is not None]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass


def mask_key(key: str) -> str:
    """sk-1234567890abcdef → sk-1***cdef"""
    if not key or len(key) < 8:
        return "***"
    return key[:4] + "***" + key[-4:]
```

- [ ] **Step 4: Run tests, PASS**

Run: `uv run pytest tests/test_config.py -v`

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/config.py tests/test_config.py
git commit -m "feat(config): TOML config + .env secrets with masking and env-var precedence"
```

---

### Task 7: utils/downloader.py — yt-dlp wrapper with anti-blocking defenses

**Files:**
- Create: `skills/youtube_transcribe/utils/downloader.py`
- Create: `tests/test_downloader.py`

- [ ] **Step 1: Failing-test**

`tests/test_downloader.py`:

```python
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from skills.youtube_transcribe.utils.downloader import (
    is_url,
    is_youtube_url,
    extract_youtube_video_id,
    build_ytdlp_command,
    DownloadError,
)


def test_is_url_true_for_http():
    assert is_url("https://youtu.be/dQw4w9WgXcQ")


def test_is_url_false_for_path():
    assert not is_url("C:/videos/file.mp4")
    assert not is_url("/home/user/file.mp3")


def test_is_youtube_url_short():
    assert is_youtube_url("https://youtu.be/abc123")


def test_is_youtube_url_long():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc123")


def test_is_youtube_url_false_for_vimeo():
    assert not is_youtube_url("https://vimeo.com/12345")


def test_extract_video_id_short():
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_long():
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s") == "dQw4w9WgXcQ"


def test_build_ytdlp_command_basic(tmp_path: Path):
    cmd = build_ytdlp_command(
        url="https://youtu.be/abc",
        output_template=str(tmp_path / "audio.%(ext)s"),
        cookies_browser="",
    )
    assert "yt-dlp" in cmd[0]
    assert "-x" in cmd
    assert "--audio-format" in cmd
    assert "mp3" in cmd
    assert "https://youtu.be/abc" in cmd
    assert "--cookies-from-browser" not in cmd  # only added when set


def test_build_ytdlp_command_with_cookies(tmp_path: Path):
    cmd = build_ytdlp_command(
        url="https://youtu.be/abc",
        output_template=str(tmp_path / "audio.%(ext)s"),
        cookies_browser="chrome",
    )
    assert "--cookies-from-browser" in cmd
    assert "chrome" in cmd
```

- [ ] **Step 2: Run, FAIL**

Run: `uv run pytest tests/test_downloader.py -v`

- [ ] **Step 3: Implement downloader.py**

```python
"""Wrapper around yt-dlp with cookies, retries, friendly errors, and auto-update."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from skills.youtube_transcribe.config import CONFIG_DIR


class DownloadError(Exception):
    """Raised on download failure with a friendly hint."""


_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_YOUTUBE_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w\-]{11})",
    re.IGNORECASE,
)
_STATE_PATH = CONFIG_DIR / "state.json"


def is_url(s: str) -> bool:
    return bool(_URL_RE.match(s))


def is_youtube_url(s: str) -> bool:
    return bool(_YOUTUBE_RE.match(s))


def extract_youtube_video_id(s: str) -> str | None:
    m = _YOUTUBE_RE.match(s)
    return m.group(1) if m else None


def build_ytdlp_command(
    *,
    url: str,
    output_template: str,
    cookies_browser: str = "",
    audio_format: str = "mp3",
) -> list[str]:
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", audio_format,
        "--audio-quality", "0",
        "--geo-bypass",
        "--no-playlist",
        "-o", output_template,
    ]
    if cookies_browser:
        cmd += ["--cookies-from-browser", cookies_browser]
    cmd.append(url)
    return cmd


def _load_state() -> dict:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def maybe_auto_update_ytdlp(enabled: bool, *, max_age_hours: int = 24) -> bool:
    """If `enabled` and last update was >max_age_hours ago, run `yt-dlp -U`.
    Returns True if an update was attempted."""
    if not enabled:
        return False
    state = _load_state()
    last_iso = state.get("yt_dlp_last_update")
    if last_iso:
        try:
            last = datetime.fromisoformat(last_iso)
            if datetime.now() - last < timedelta(hours=max_age_hours):
                return False
        except ValueError:
            pass

    try:
        subprocess.run(
            ["yt-dlp", "-U"],
            capture_output=True,
            timeout=60,
            check=False,
        )
        state["yt_dlp_last_update"] = datetime.now().isoformat()
        _save_state(state)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _diagnose_ytdlp_error(stderr: str) -> str:
    """Map common yt-dlp errors to actionable hints."""
    s = stderr.lower()
    if "sign in to confirm you" in s or "bot" in s or "403" in s:
        return ("YouTube заблокировал запрос как бот. Попробуй: "
                "--cookies-from-browser chrome (или firefox/edge). "
                "Также может помочь обновить yt-dlp: youtube-transcribe update-deps.")
    if "video is private" in s or "members-only" in s:
        return "Видео приватное или только для подписчиков. Нужны cookies залогиненного аккаунта."
    if "age" in s and "restrict" in s:
        return "Видео с возрастным ограничением. Используй --cookies-from-browser."
    if "country" in s or "geo" in s:
        return "Видео заблокировано в твоём регионе. Попробуй VPN или другой регион."
    if "unable to download" in s and "requested format" in s:
        return "Формат недоступен. Возможно, видео — только live-stream или premiere."
    return "Скачивание упало. См. полный stderr выше."


def download_audio(
    url: str,
    output_dir: Path,
    *,
    cookies_browser: str = "",
    timeout_seconds: int = 600,
) -> Path:
    """Download audio from URL via yt-dlp. Returns path to the audio file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "audio_%(id)s.%(ext)s")
    cmd = build_ytdlp_command(
        url=url,
        output_template=template,
        cookies_browser=cookies_browser,
    )

    if shutil.which("yt-dlp") is None:
        raise DownloadError("yt-dlp не найден в PATH. Установи через `uv sync` или `pip install yt-dlp`.")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired:
        raise DownloadError(f"Скачивание превысило {timeout_seconds} сек. Проверь интернет или используй --cookies.")

    if result.returncode != 0:
        hint = _diagnose_ytdlp_error(result.stderr or "")
        raise DownloadError(f"{hint}\n\n--- stderr ---\n{result.stderr}")

    # Find downloaded file
    candidates = sorted(output_dir.glob("audio_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise DownloadError("yt-dlp завершился успешно, но файл не найден.")
    return candidates[0]
```

- [ ] **Step 4: Run tests, PASS**

Run: `uv run pytest tests/test_downloader.py -v`

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/utils/downloader.py tests/test_downloader.py
git commit -m "feat(utils): yt-dlp wrapper with cookies, auto-update, friendly errors"
```

---

### Task 8: backends/base.py — Transcriber Protocol + TranscriptionResult

**Files:**
- Create: `skills/youtube_transcribe/backends/__init__.py`
- Create: `skills/youtube_transcribe/backends/base.py`
- Create: `tests/test_base.py`

- [ ] **Step 1: Создать `__init__.py`**

```bash
mkdir -p skills/youtube_transcribe/backends
touch skills/youtube_transcribe/backends/__init__.py
```

- [ ] **Step 2: Failing-test**

`tests/test_base.py`:

```python
from skills.youtube_transcribe.backends.base import (
    Transcriber,
    TranscriptionResult,
    BackendError,
    BackendNotConfigured,
)
from skills.youtube_transcribe.utils.output_writer import Segment


def test_transcription_result_construct():
    res = TranscriptionResult(
        text="hello world",
        segments=[Segment(0.0, 1.0, "hello"), Segment(1.0, 2.0, "world")],
        language_detected="en",
        backend_name="dummy",
        duration_seconds=2.0,
    )
    assert res.text == "hello world"
    assert len(res.segments) == 2


def test_backend_errors_are_distinct():
    assert issubclass(BackendNotConfigured, BackendError)
    assert not issubclass(BackendError, BackendNotConfigured)


def test_transcriber_is_protocol():
    # Should NOT be instantiable directly; just verify it's a Protocol
    import typing
    assert getattr(Transcriber, "_is_protocol", False) or hasattr(Transcriber, "__protocol_attrs__")
```

- [ ] **Step 3: Run, FAIL**

- [ ] **Step 4: Implement base.py**

```python
"""Base abstractions for all transcription backends."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from skills.youtube_transcribe.utils.output_writer import Segment


class BackendError(Exception):
    """Generic backend failure."""


class BackendNotConfigured(BackendError):
    """Raised when a backend is missing its API key or required config."""


@dataclass
class TranscriptionResult:
    text: str
    segments: list[Segment]
    language_detected: str | None
    backend_name: str
    duration_seconds: float


@runtime_checkable
class Transcriber(Protocol):
    name: str
    supports_url: bool       # True if backend can take a URL directly (subtitles)
    supports_local_file: bool

    def is_configured(self) -> tuple[bool, str | None]:
        """Return (True, None) if ready; (False, reason) otherwise."""
        ...

    def transcribe(
        self,
        audio_or_url: str | Path,
        *,
        language: str = "auto",
        **opts,
    ) -> TranscriptionResult:
        ...
```

- [ ] **Step 5: Run, PASS**

- [ ] **Step 6: Commit**

```bash
git add skills/youtube_transcribe/backends/__init__.py skills/youtube_transcribe/backends/base.py tests/test_base.py
git commit -m "feat(backends): Transcriber protocol + TranscriptionResult"
```

---

# Phase 3 — Backends

> **Convention for all backend tasks:**
> Each backend is one file under `skills/youtube_transcribe/backends/`.
> Each has a corresponding test file under `tests/test_<backend>.py`.
> Each test mocks the SDK / subprocess to avoid hitting real APIs in CI.
> Each implementation maps the SDK's response shape into our `TranscriptionResult` + `Segment[]`.

### Task 9: backends/whisper_local.py (faster-whisper path, Win/Linux/CPU)

**Files:**
- Create: `skills/youtube_transcribe/backends/whisper_local.py`
- Create: `tests/test_whisper_local.py`

- [ ] **Step 1: Failing-test (only faster-whisper path; mlx in Task 10)**

```python
from pathlib import Path
from unittest.mock import patch, MagicMock

from skills.youtube_transcribe.backends.whisper_local import WhisperLocalBackend


def test_is_configured_when_faster_whisper_importable():
    b = WhisperLocalBackend(model="turbo", device="auto", compute_type="auto", impl="faster")
    ok, reason = b.is_configured()
    assert ok is True
    assert reason is None


def test_resolve_model_name_faster_turbo():
    b = WhisperLocalBackend(model="turbo", device="auto", compute_type="auto", impl="faster")
    assert b._resolve_model_name() == "large-v3-turbo"


def test_resolve_model_name_distil_on_mlx_raises():
    b = WhisperLocalBackend(model="distil", device="mps", compute_type="auto", impl="mlx")
    import pytest
    with pytest.raises(ValueError, match="distil"):
        b._resolve_model_name()


def test_transcribe_calls_faster_whisper(tmp_path: Path):
    fake_segment = MagicMock(start=0.0, end=1.5, text="hello", words=None)
    fake_info = MagicMock(language="en", duration=1.5)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], fake_info)

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")

    with patch(
        "skills.youtube_transcribe.backends.whisper_local._load_faster_whisper_model",
        return_value=fake_model,
    ):
        b = WhisperLocalBackend(model="turbo", device="cuda", compute_type="float16", impl="faster")
        result = b.transcribe(audio, language="en")

    assert result.text.strip() == "hello"
    assert result.language_detected == "en"
    assert result.backend_name == "whisper-local"
    assert len(result.segments) == 1
    assert result.segments[0].start == 0.0
    fake_model.transcribe.assert_called_once()
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement whisper_local.py (faster-whisper part)**

```python
"""Local Whisper backend.

Two implementations:
  - faster-whisper for Windows/Linux/Intel-Mac (CUDA or CPU)
  - mlx-whisper for Apple Silicon  ← added in Task 10
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from skills.youtube_transcribe.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.youtube_transcribe.utils.output_writer import Segment


_MODEL_MAP = {
    "turbo":  {"mlx": "mlx-community/whisper-large-v3-turbo", "faster": "large-v3-turbo"},
    "large":  {"mlx": "mlx-community/whisper-large-v3-mlx",   "faster": "large-v3"},
    "medium": {"mlx": "mlx-community/whisper-medium-mlx",     "faster": "medium"},
    "small":  {"mlx": "mlx-community/whisper-small-mlx",      "faster": "small"},
    "distil": {"mlx": None,                                   "faster": "distil-large-v3"},
}


def _load_faster_whisper_model(name: str, device: str, compute_type: str):
    """Indirection to make this trivially mockable in tests."""
    from faster_whisper import WhisperModel
    return WhisperModel(name, device=device, compute_type=compute_type)


def _resolve_compute_type(compute_type: str, device: str) -> str:
    if compute_type != "auto":
        return compute_type
    if device == "cuda":
        # Default safe choice; platform_detect can pre-set explicit value
        return "float16"
    return "int8"


def _resolve_device(device: str, impl: str) -> str:
    if device != "auto":
        return device
    if impl == "mlx":
        return "mps"
    # Try CUDA, fall back to CPU
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    # faster-whisper has its own check via CTranslate2; default to cuda then fallback to cpu in transcribe
    return "cpu"


@dataclass
class WhisperLocalBackend:
    name: str = "whisper-local"
    supports_url: bool = False
    supports_local_file: bool = True

    model: Literal["turbo", "large", "medium", "small", "distil"] = "turbo"
    device: str = "auto"          # auto | cuda | cpu | mps
    compute_type: str = "auto"
    impl: Literal["mlx", "faster"] = "faster"
    beam_size: int = 5
    vad: bool = True

    def is_configured(self) -> tuple[bool, str | None]:
        if self.impl == "mlx":
            try:
                import mlx_whisper  # noqa: F401
                return True, None
            except ImportError:
                return False, "mlx-whisper не установлен (нужен macOS Apple Silicon)."
        try:
            import faster_whisper  # noqa: F401
            return True, None
        except ImportError:
            return False, "faster-whisper не установлен. Запусти `uv sync`."

    def _resolve_model_name(self) -> str:
        m = _MODEL_MAP.get(self.model)
        if not m:
            raise ValueError(f"Unknown model: {self.model}")
        name = m[self.impl]
        if name is None:
            raise ValueError(f"Model '{self.model}' is not supported for impl='{self.impl}'.")
        return name

    def transcribe(
        self,
        audio_or_url,
        *,
        language: str = "auto",
        **opts,
    ) -> TranscriptionResult:
        audio = Path(audio_or_url)
        if not audio.exists():
            raise BackendError(f"Audio file not found: {audio}")

        ok, reason = self.is_configured()
        if not ok:
            raise BackendNotConfigured(reason or "")

        model_name = self._resolve_model_name()

        if self.impl == "faster":
            return self._transcribe_faster(audio, model_name, language)
        elif self.impl == "mlx":
            return self._transcribe_mlx(audio, model_name, language)
        else:
            raise BackendError(f"Unknown impl: {self.impl}")

    def _transcribe_faster(self, audio: Path, model_name: str, language: str) -> TranscriptionResult:
        device = _resolve_device(self.device, "faster")
        compute_type = _resolve_compute_type(self.compute_type, device)
        model = _load_faster_whisper_model(model_name, device, compute_type)
        lang = None if language == "auto" else language
        segments_iter, info = model.transcribe(
            str(audio),
            language=lang,
            beam_size=self.beam_size,
            vad_filter=self.vad,
            word_timestamps=False,
        )
        segments: list[Segment] = []
        for s in segments_iter:
            segments.append(Segment(start=float(s.start), end=float(s.end), text=s.text))
        text = " ".join(s.text.strip() for s in segments)
        return TranscriptionResult(
            text=text,
            segments=segments,
            language_detected=getattr(info, "language", None),
            backend_name=self.name,
            duration_seconds=float(getattr(info, "duration", 0.0)),
        )

    def _transcribe_mlx(self, audio: Path, model_name: str, language: str) -> TranscriptionResult:
        # Implementation added in Task 10
        raise NotImplementedError("mlx implementation added in Task 10")
```

- [ ] **Step 4: Run tests, PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/backends/whisper_local.py tests/test_whisper_local.py
git commit -m "feat(backends): whisper-local — faster-whisper path"
```

---

### Task 10: backends/whisper_local.py — extend with mlx-whisper path (macOS)

**Files:**
- Modify: `skills/youtube_transcribe/backends/whisper_local.py` (`_transcribe_mlx`)
- Modify: `tests/test_whisper_local.py` (add mlx tests)

> **Note on testing:** mlx-whisper не доступен на Windows. Тесты замокают `mlx_whisper.transcribe`. Финальная валидация — на Mac (Phase 7).

- [ ] **Step 1: Add failing test for mlx path**

Append to `tests/test_whisper_local.py`:

```python
def test_transcribe_calls_mlx_whisper(tmp_path: Path):
    fake_response = {
        "text": "hello world",
        "segments": [
            {"start": 0.0, "end": 1.5, "text": "hello world"},
        ],
        "language": "en",
    }
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")

    fake_module = MagicMock()
    fake_module.transcribe.return_value = fake_response

    with patch.dict("sys.modules", {"mlx_whisper": fake_module}):
        b = WhisperLocalBackend(model="turbo", device="mps", compute_type="auto", impl="mlx")
        result = b.transcribe(audio, language="en")

    assert result.text.strip() == "hello world"
    assert result.backend_name == "whisper-local"
    assert result.segments[0].text == "hello world"
    fake_module.transcribe.assert_called_once()
```

- [ ] **Step 2: Run new test, FAIL with NotImplementedError**

- [ ] **Step 3: Implement `_transcribe_mlx`**

In `whisper_local.py`, replace the `NotImplementedError` body:

```python
    def _transcribe_mlx(self, audio: Path, model_name: str, language: str) -> TranscriptionResult:
        import mlx_whisper  # type: ignore
        lang = None if language == "auto" else language
        # mlx_whisper.transcribe returns dict with "text", "segments", "language"
        result = mlx_whisper.transcribe(
            str(audio),
            path_or_hf_repo=model_name,
            language=lang,
            word_timestamps=False,
        )
        segments: list[Segment] = []
        total_duration = 0.0
        for s in result.get("segments", []):
            seg = Segment(
                start=float(s.get("start", 0.0)),
                end=float(s.get("end", 0.0)),
                text=str(s.get("text", "")),
            )
            segments.append(seg)
            total_duration = max(total_duration, seg.end)
        text = result.get("text") or " ".join(s.text.strip() for s in segments)
        return TranscriptionResult(
            text=text,
            segments=segments,
            language_detected=result.get("language"),
            backend_name=self.name,
            duration_seconds=total_duration,
        )
```

- [ ] **Step 4: Run tests, PASS**

Run: `uv run pytest tests/test_whisper_local.py -v`

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/backends/whisper_local.py tests/test_whisper_local.py
git commit -m "feat(backends): whisper-local — mlx-whisper path for Apple Silicon"
```

---

### Task 11: backends/subtitles.py — youtube-transcript-api

**Files:**
- Create: `skills/youtube_transcribe/backends/subtitles.py`
- Create: `tests/test_subtitles.py`

- [ ] **Step 1: Failing-test**

```python
from unittest.mock import patch, MagicMock
from skills.youtube_transcribe.backends.subtitles import SubtitlesBackend
from skills.youtube_transcribe.backends.base import BackendError


def test_supports_url_true():
    assert SubtitlesBackend().supports_url is True


def test_only_youtube_urls_supported():
    b = SubtitlesBackend()
    import pytest
    with pytest.raises(BackendError, match="YouTube"):
        b.transcribe("https://vimeo.com/123", language="en")


def test_transcribe_returns_result():
    fake_segments = [
        {"start": 0.0, "duration": 2.5, "text": "Hello"},
        {"start": 2.5, "duration": 2.5, "text": "World"},
    ]
    fake_api = MagicMock()
    fake_api.get_transcript.return_value = fake_segments

    with patch(
        "skills.youtube_transcribe.backends.subtitles._get_transcript_api",
        return_value=fake_api,
    ):
        b = SubtitlesBackend()
        result = b.transcribe("https://youtu.be/dQw4w9WgXcQ", language="en")

    assert result.backend_name == "subtitles"
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hello"
    assert result.segments[0].end == 2.5
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement subtitles.py**

```python
from __future__ import annotations

from dataclasses import dataclass

from skills.youtube_transcribe.backends.base import (
    BackendError,
    TranscriptionResult,
)
from skills.youtube_transcribe.utils.downloader import (
    extract_youtube_video_id,
    is_youtube_url,
)
from skills.youtube_transcribe.utils.output_writer import Segment


def _get_transcript_api():
    from youtube_transcript_api import YouTubeTranscriptApi
    return YouTubeTranscriptApi


@dataclass
class SubtitlesBackend:
    name: str = "subtitles"
    supports_url: bool = True
    supports_local_file: bool = False

    def is_configured(self) -> tuple[bool, str | None]:
        try:
            import youtube_transcript_api  # noqa: F401
            return True, None
        except ImportError:
            return False, "youtube-transcript-api не установлен. Запусти `uv sync`."

    def transcribe(self, audio_or_url, *, language: str = "auto", **opts) -> TranscriptionResult:
        url = str(audio_or_url)
        if not is_youtube_url(url):
            raise BackendError("Бэкенд subtitles работает только с YouTube-ссылками.")

        video_id = extract_youtube_video_id(url)
        if not video_id:
            raise BackendError(f"Не смог извлечь ID YouTube-видео из URL: {url}")

        api = _get_transcript_api()
        languages = None if language == "auto" else [language]
        try:
            raw = api.get_transcript(video_id, languages=languages or ["en"])
        except Exception as e:
            raise BackendError(
                f"Субтитры недоступны для этого видео ({type(e).__name__}). "
                "Попробуй другой бэкенд."
            ) from e

        segments: list[Segment] = []
        for item in raw:
            start = float(item.get("start", 0.0))
            duration = float(item.get("duration", 0.0))
            segments.append(Segment(
                start=start,
                end=start + duration,
                text=str(item.get("text", "")).strip(),
            ))
        text = " ".join(s.text for s in segments)
        return TranscriptionResult(
            text=text,
            segments=segments,
            language_detected=language if language != "auto" else None,
            backend_name=self.name,
            duration_seconds=segments[-1].end if segments else 0.0,
        )
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/backends/subtitles.py tests/test_subtitles.py
git commit -m "feat(backends): subtitles — youtube-transcript-api fast path"
```

---

### Task 12: backends/gemini.py — Google AI Studio

**Files:**
- Create: `skills/youtube_transcribe/backends/gemini.py`
- Create: `tests/test_gemini.py`

- [ ] **Step 1: Failing-test**

```python
import json
from unittest.mock import patch, MagicMock
from pathlib import Path

from skills.youtube_transcribe.backends.gemini import GeminiBackend
from skills.youtube_transcribe.backends.base import BackendNotConfigured


def test_is_configured_without_key(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    fake_env = tmp_path / ".env"
    with patch("skills.youtube_transcribe.backends.gemini.get_api_key", return_value=None):
        b = GeminiBackend(model="gemini-2.5-flash")
        ok, reason = b.is_configured()
        assert ok is False
        assert "GEMINI_API_KEY" in reason


def test_is_configured_with_key():
    with patch("skills.youtube_transcribe.backends.gemini.get_api_key", return_value="x"):
        b = GeminiBackend(model="gemini-2.5-flash")
        ok, _ = b.is_configured()
        assert ok is True


def test_transcribe_parses_json_response(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    fake_response = MagicMock()
    fake_response.text = json.dumps({
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Hello"},
            {"start": 2.0, "end": 4.0, "text": "World"},
        ],
    })
    fake_client = MagicMock()
    fake_client.files.upload.return_value = MagicMock(name="files/abc")
    fake_client.models.generate_content.return_value = fake_response

    with patch("skills.youtube_transcribe.backends.gemini.get_api_key", return_value="x"), \
         patch("skills.youtube_transcribe.backends.gemini._build_client", return_value=fake_client):
        b = GeminiBackend(model="gemini-2.5-flash")
        result = b.transcribe(audio, language="en")

    assert result.backend_name == "gemini"
    assert result.language_detected == "en"
    assert len(result.segments) == 2
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement gemini.py**

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from skills.youtube_transcribe.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.youtube_transcribe.config import get_api_key
from skills.youtube_transcribe.utils.output_writer import Segment


_PROMPT = """\
Transcribe this audio precisely. Return ONLY valid JSON in this exact shape:
{
  "language": "<2-letter ISO code or 'unknown'>",
  "segments": [
    {"start": <seconds, float>, "end": <seconds, float>, "text": "<utterance>"},
    ...
  ]
}
Use precise timestamps. Do not add commentary, do not wrap in markdown fences."""


def _build_client(api_key: str):
    from google import genai
    return genai.Client(api_key=api_key)


def _extract_json(text: str) -> dict:
    """Strip markdown fences, parse JSON."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


@dataclass
class GeminiBackend:
    name: str = "gemini"
    supports_url: bool = False
    supports_local_file: bool = True

    model: str = "gemini-2.5-flash"
    language_hint: str = "auto"

    def is_configured(self) -> tuple[bool, str | None]:
        key = get_api_key("gemini")
        if not key:
            return False, ("GEMINI_API_KEY не задан. Получи ключ на https://aistudio.google.com/apikey "
                           "и пропиши его через `youtube-transcribe config set-key gemini`.")
        return True, None

    def transcribe(self, audio_or_url, *, language: str = "auto", **opts) -> TranscriptionResult:
        audio = Path(audio_or_url)
        if not audio.exists():
            raise BackendError(f"Audio file not found: {audio}")

        api_key = get_api_key("gemini")
        if not api_key:
            raise BackendNotConfigured("GEMINI_API_KEY missing.")

        client = _build_client(api_key)
        try:
            uploaded = client.files.upload(file=str(audio))
            response = client.models.generate_content(
                model=self.model,
                contents=[_PROMPT, uploaded],
            )
        except Exception as e:
            raise BackendError(f"Gemini API ошибка: {e}") from e

        try:
            data = _extract_json(getattr(response, "text", "") or "")
        except json.JSONDecodeError as e:
            raise BackendError(
                f"Gemini вернул не-JSON ответ. Пробуй другой движок или повтори запрос. "
                f"Ошибка: {e}"
            )

        segments: list[Segment] = []
        for s in data.get("segments", []):
            segments.append(Segment(
                start=float(s.get("start", 0.0)),
                end=float(s.get("end", 0.0)),
                text=str(s.get("text", "")).strip(),
            ))
        text = " ".join(s.text for s in segments)
        return TranscriptionResult(
            text=text,
            segments=segments,
            language_detected=data.get("language"),
            backend_name=self.name,
            duration_seconds=segments[-1].end if segments else 0.0,
        )
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/backends/gemini.py tests/test_gemini.py
git commit -m "feat(backends): gemini — Google AI Studio with file upload + JSON parse"
```

---

### Task 13: backends/groq.py — Groq Whisper API

**Files:**
- Create: `skills/youtube_transcribe/backends/groq.py`
- Create: `tests/test_groq.py`

- [ ] **Step 1: Failing-test**

```python
from unittest.mock import patch, MagicMock
from pathlib import Path

from skills.youtube_transcribe.backends.groq import GroqBackend


def test_is_configured_without_key():
    with patch("skills.youtube_transcribe.backends.groq.get_api_key", return_value=None):
        ok, reason = GroqBackend(model="whisper-large-v3-turbo").is_configured()
        assert not ok and "GROQ_API_KEY" in reason


def test_transcribe_maps_response(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")

    fake_resp = MagicMock(
        text="Hello world.",
        language="en",
        duration=2.5,
        segments=[
            {"start": 0.0, "end": 1.0, "text": "Hello"},
            {"start": 1.0, "end": 2.5, "text": "world."},
        ],
    )
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = fake_resp

    with patch("skills.youtube_transcribe.backends.groq.get_api_key", return_value="x"), \
         patch("skills.youtube_transcribe.backends.groq._build_client", return_value=fake_client):
        b = GroqBackend(model="whisper-large-v3-turbo")
        result = b.transcribe(audio, language="en")

    assert result.backend_name == "groq"
    assert result.text == "Hello world."
    assert len(result.segments) == 2
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement groq.py**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skills.youtube_transcribe.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.youtube_transcribe.config import get_api_key
from skills.youtube_transcribe.utils.output_writer import Segment


def _build_client(api_key: str):
    from groq import Groq
    return Groq(api_key=api_key)


@dataclass
class GroqBackend:
    name: str = "groq"
    supports_url: bool = False
    supports_local_file: bool = True

    model: str = "whisper-large-v3-turbo"

    def is_configured(self) -> tuple[bool, str | None]:
        if not get_api_key("groq"):
            return False, ("GROQ_API_KEY не задан. Получи на https://console.groq.com/keys "
                           "и пропиши через `youtube-transcribe config set-key groq`.")
        return True, None

    def transcribe(self, audio_or_url, *, language: str = "auto", **opts) -> TranscriptionResult:
        audio = Path(audio_or_url)
        if not audio.exists():
            raise BackendError(f"Audio file not found: {audio}")
        key = get_api_key("groq")
        if not key:
            raise BackendNotConfigured("GROQ_API_KEY missing.")

        client = _build_client(key)
        lang = None if language == "auto" else language
        try:
            with audio.open("rb") as f:
                resp = client.audio.transcriptions.create(
                    file=(audio.name, f.read()),
                    model=self.model,
                    language=lang,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
        except Exception as e:
            raise BackendError(f"Groq API ошибка: {e}") from e

        segments_data = getattr(resp, "segments", None) or []
        segments = [
            Segment(
                start=float(s.get("start", 0.0)) if isinstance(s, dict) else float(s.start),
                end=float(s.get("end", 0.0)) if isinstance(s, dict) else float(s.end),
                text=(s.get("text") if isinstance(s, dict) else s.text).strip(),
            )
            for s in segments_data
        ]
        return TranscriptionResult(
            text=getattr(resp, "text", "").strip(),
            segments=segments,
            language_detected=getattr(resp, "language", None),
            backend_name=self.name,
            duration_seconds=float(getattr(resp, "duration", 0.0) or 0.0),
        )
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/backends/groq.py tests/test_groq.py
git commit -m "feat(backends): groq — Whisper API on LPU"
```

---

### Task 14: backends/openai_api.py — OpenAI Whisper API

**Files:**
- Create: `skills/youtube_transcribe/backends/openai_api.py`
- Create: `tests/test_openai_api.py`

- [ ] **Step 1-5: Same TDD pattern as Task 13.** Implementation follows the same shape as Groq because both expose a similar `audio.transcriptions.create` interface (Groq is intentionally OpenAI-compatible).

`skills/youtube_transcribe/backends/openai_api.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skills.youtube_transcribe.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.youtube_transcribe.config import get_api_key
from skills.youtube_transcribe.utils.output_writer import Segment


def _build_client(api_key: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key)


@dataclass
class OpenAIBackend:
    name: str = "openai"
    supports_url: bool = False
    supports_local_file: bool = True

    model: str = "whisper-1"

    def is_configured(self) -> tuple[bool, str | None]:
        if not get_api_key("openai"):
            return False, "OPENAI_API_KEY не задан. Пропиши через `youtube-transcribe config set-key openai`."
        return True, None

    def transcribe(self, audio_or_url, *, language: str = "auto", **opts) -> TranscriptionResult:
        audio = Path(audio_or_url)
        if not audio.exists():
            raise BackendError(f"Audio file not found: {audio}")
        key = get_api_key("openai")
        if not key:
            raise BackendNotConfigured("OPENAI_API_KEY missing.")

        client = _build_client(key)
        lang = None if language == "auto" else language
        try:
            with audio.open("rb") as f:
                resp = client.audio.transcriptions.create(
                    file=f,
                    model=self.model,
                    language=lang,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
        except Exception as e:
            raise BackendError(f"OpenAI API ошибка: {e}") from e

        segments_data = getattr(resp, "segments", None) or []
        segments = [
            Segment(
                start=float(s.get("start", 0.0)) if isinstance(s, dict) else float(s.start),
                end=float(s.get("end", 0.0)) if isinstance(s, dict) else float(s.end),
                text=(s.get("text") if isinstance(s, dict) else s.text).strip(),
            )
            for s in segments_data
        ]
        return TranscriptionResult(
            text=getattr(resp, "text", "").strip(),
            segments=segments,
            language_detected=getattr(resp, "language", None),
            backend_name=self.name,
            duration_seconds=float(getattr(resp, "duration", 0.0) or 0.0),
        )
```

`tests/test_openai_api.py` — копия структуры `test_groq.py` с подменой имени бэкенда и переменной окружения. Полные шаги (failing test → run → impl → run → commit) идентичны Task 13.

```bash
git add skills/youtube_transcribe/backends/openai_api.py tests/test_openai_api.py
git commit -m "feat(backends): openai — Whisper API"
```

---

### Task 15: backends/deepgram.py — Deepgram Nova-3

**Files:**
- Create: `skills/youtube_transcribe/backends/deepgram.py`
- Create: `tests/test_deepgram.py`

- [ ] **Step 1: Failing-test**

```python
from unittest.mock import patch, MagicMock
from pathlib import Path
from skills.youtube_transcribe.backends.deepgram import DeepgramBackend


def test_is_configured_without_key():
    with patch("skills.youtube_transcribe.backends.deepgram.get_api_key", return_value=None):
        ok, reason = DeepgramBackend(model="nova-3").is_configured()
        assert not ok and "DEEPGRAM_API_KEY" in reason


def test_transcribe_maps_words_to_segments(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")

    # Deepgram returns words with start/end; we group into segments by punctuation/sentence
    fake_response = {
        "results": {
            "channels": [{
                "detected_language": "en",
                "alternatives": [{
                    "transcript": "Hello world. Second sentence.",
                    "words": [
                        {"word": "Hello", "start": 0.0, "end": 0.5, "punctuated_word": "Hello"},
                        {"word": "world", "start": 0.5, "end": 1.0, "punctuated_word": "world."},
                        {"word": "Second", "start": 1.5, "end": 2.0, "punctuated_word": "Second"},
                        {"word": "sentence", "start": 2.0, "end": 2.5, "punctuated_word": "sentence."},
                    ],
                }],
            }],
        },
    }
    fake_client = MagicMock()
    fake_client.listen.rest.v.return_value.transcribe_file.return_value.to_dict.return_value = fake_response

    with patch("skills.youtube_transcribe.backends.deepgram.get_api_key", return_value="x"), \
         patch("skills.youtube_transcribe.backends.deepgram._build_client", return_value=fake_client):
        b = DeepgramBackend(model="nova-3")
        result = b.transcribe(audio, language="en")

    assert result.backend_name == "deepgram"
    assert result.language_detected == "en"
    # Two sentences → two segments grouped by sentence-ending punctuation
    assert len(result.segments) == 2
    assert result.segments[0].text.startswith("Hello")
    assert result.segments[1].text.startswith("Second")
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement deepgram.py**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skills.youtube_transcribe.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.youtube_transcribe.config import get_api_key
from skills.youtube_transcribe.utils.output_writer import Segment


def _build_client(api_key: str):
    from deepgram import DeepgramClient
    return DeepgramClient(api_key)


def _group_words_into_sentences(words: list[dict]) -> list[Segment]:
    """Group word-level Deepgram output into sentence-level Segments."""
    segments: list[Segment] = []
    if not words:
        return segments
    cur_start = float(words[0].get("start", 0.0))
    cur_words: list[str] = []
    for w in words:
        pw = w.get("punctuated_word") or w.get("word", "")
        cur_words.append(pw)
        # End segment on sentence-ending punctuation
        if pw.rstrip().endswith((".", "!", "?", "…")):
            segments.append(Segment(
                start=cur_start,
                end=float(w.get("end", cur_start)),
                text=" ".join(cur_words).strip(),
            ))
            cur_words = []
            # next start is set on next iteration
            next_idx = words.index(w) + 1
            if next_idx < len(words):
                cur_start = float(words[next_idx].get("start", 0.0))
    if cur_words:
        segments.append(Segment(
            start=cur_start,
            end=float(words[-1].get("end", cur_start)),
            text=" ".join(cur_words).strip(),
        ))
    return segments


@dataclass
class DeepgramBackend:
    name: str = "deepgram"
    supports_url: bool = False
    supports_local_file: bool = True

    model: str = "nova-3"

    def is_configured(self) -> tuple[bool, str | None]:
        if not get_api_key("deepgram"):
            return False, ("DEEPGRAM_API_KEY не задан. Получи на https://console.deepgram.com/ "
                           "и пропиши через `youtube-transcribe config set-key deepgram`.")
        return True, None

    def transcribe(self, audio_or_url, *, language: str = "auto", **opts) -> TranscriptionResult:
        from deepgram import PrerecordedOptions, FileSource

        audio = Path(audio_or_url)
        if not audio.exists():
            raise BackendError(f"Audio file not found: {audio}")
        key = get_api_key("deepgram")
        if not key:
            raise BackendNotConfigured("DEEPGRAM_API_KEY missing.")

        client = _build_client(key)
        try:
            with audio.open("rb") as f:
                payload: FileSource = {"buffer": f.read()}
            options = PrerecordedOptions(
                model=self.model,
                smart_format=True,
                punctuate=True,
                detect_language=(language == "auto"),
                language=None if language == "auto" else language,
            )
            response = client.listen.rest.v("1").transcribe_file(payload, options).to_dict()
        except Exception as e:
            raise BackendError(f"Deepgram API ошибка: {e}") from e

        try:
            channel = response["results"]["channels"][0]
            alt = channel["alternatives"][0]
            words = alt.get("words", [])
            language_detected = channel.get("detected_language")
        except (KeyError, IndexError) as e:
            raise BackendError(f"Неожиданный формат ответа Deepgram: {e}")

        segments = _group_words_into_sentences(words)
        text = alt.get("transcript", "").strip()
        return TranscriptionResult(
            text=text,
            segments=segments,
            language_detected=language_detected,
            backend_name=self.name,
            duration_seconds=segments[-1].end if segments else 0.0,
        )
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/backends/deepgram.py tests/test_deepgram.py
git commit -m "feat(backends): deepgram — Nova-3 with sentence grouping"
```

---

### Task 16: backends/assemblyai.py — AssemblyAI

**Files:**
- Create: `skills/youtube_transcribe/backends/assemblyai.py`
- Create: `tests/test_assemblyai.py`

- [ ] **Step 1: Failing-test**

```python
from unittest.mock import patch, MagicMock
from pathlib import Path
from skills.youtube_transcribe.backends.assemblyai import AssemblyAIBackend


def test_is_configured_without_key():
    with patch("skills.youtube_transcribe.backends.assemblyai.get_api_key", return_value=None):
        ok, reason = AssemblyAIBackend(model="best").is_configured()
        assert not ok and "ASSEMBLYAI_API_KEY" in reason


def test_transcribe_uses_utterances(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")

    fake_transcript = MagicMock(
        text="Hello. World.",
        language_code="en",
        audio_duration=4.0,
        utterances=[
            MagicMock(start=0, end=2000, text="Hello."),
            MagicMock(start=2000, end=4000, text="World."),
        ],
    )
    fake_transcriber = MagicMock()
    fake_transcriber.transcribe.return_value = fake_transcript

    with patch("skills.youtube_transcribe.backends.assemblyai.get_api_key", return_value="x"), \
         patch("skills.youtube_transcribe.backends.assemblyai._build_transcriber", return_value=fake_transcriber):
        b = AssemblyAIBackend(model="best")
        result = b.transcribe(audio, language="en")

    assert result.backend_name == "assemblyai"
    assert result.language_detected == "en"
    # Utterance times are in milliseconds → seconds
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 2.0
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement assemblyai.py**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skills.youtube_transcribe.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.youtube_transcribe.config import get_api_key
from skills.youtube_transcribe.utils.output_writer import Segment


def _build_transcriber(api_key: str, model: str):
    import assemblyai as aai
    aai.settings.api_key = api_key
    config = aai.TranscriptionConfig(
        speech_model=aai.SpeechModel.best if model == "best" else aai.SpeechModel.nano,
        language_detection=True,
    )
    return aai.Transcriber(config=config)


@dataclass
class AssemblyAIBackend:
    name: str = "assemblyai"
    supports_url: bool = False
    supports_local_file: bool = True

    model: str = "best"

    def is_configured(self) -> tuple[bool, str | None]:
        if not get_api_key("assemblyai"):
            return False, ("ASSEMBLYAI_API_KEY не задан. Получи на https://www.assemblyai.com/dashboard/signup "
                           "и пропиши через `youtube-transcribe config set-key assemblyai`.")
        return True, None

    def transcribe(self, audio_or_url, *, language: str = "auto", **opts) -> TranscriptionResult:
        audio = Path(audio_or_url)
        if not audio.exists():
            raise BackendError(f"Audio file not found: {audio}")
        key = get_api_key("assemblyai")
        if not key:
            raise BackendNotConfigured("ASSEMBLYAI_API_KEY missing.")

        transcriber = _build_transcriber(key, self.model)
        try:
            transcript = transcriber.transcribe(str(audio))
        except Exception as e:
            raise BackendError(f"AssemblyAI API ошибка: {e}") from e

        utterances = getattr(transcript, "utterances", None) or []
        segments: list[Segment] = []
        for u in utterances:
            segments.append(Segment(
                start=float(u.start) / 1000.0,
                end=float(u.end) / 1000.0,
                text=str(u.text).strip(),
            ))
        return TranscriptionResult(
            text=str(getattr(transcript, "text", "") or "").strip(),
            segments=segments,
            language_detected=getattr(transcript, "language_code", None),
            backend_name=self.name,
            duration_seconds=float(getattr(transcript, "audio_duration", 0.0) or 0.0),
        )
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/backends/assemblyai.py tests/test_assemblyai.py
git commit -m "feat(backends): assemblyai — best/nano speech models"
```

---

### Task 17: backends/custom.py — generic OpenAI-compatible

**Files:**
- Create: `skills/youtube_transcribe/backends/custom.py`
- Create: `tests/test_custom.py`

- [ ] **Step 1: Failing-test**

```python
from unittest.mock import patch, MagicMock
from pathlib import Path
from skills.youtube_transcribe.backends.custom import CustomBackend
from skills.youtube_transcribe.backends.base import BackendNotConfigured


def test_is_configured_requires_base_url_and_key():
    with patch("skills.youtube_transcribe.backends.custom.get_api_key", return_value="x"):
        b = CustomBackend(base_url="", model="m")
        ok, reason = b.is_configured()
        assert not ok and "base_url" in reason


def test_is_configured_requires_model():
    with patch("skills.youtube_transcribe.backends.custom.get_api_key", return_value="x"):
        b = CustomBackend(base_url="https://api.example.com/v1", model="")
        ok, reason = b.is_configured()
        assert not ok and "model" in reason


def test_transcribe_uses_openai_sdk_with_base_url(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")

    fake_resp = MagicMock(text="Hi.", language="en", duration=1.0, segments=[])
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = fake_resp

    with patch("skills.youtube_transcribe.backends.custom.get_api_key", return_value="x"), \
         patch("skills.youtube_transcribe.backends.custom._build_client", return_value=fake_client):
        b = CustomBackend(base_url="https://api.example.com/v1", model="my-whisper")
        result = b.transcribe(audio, language="en")

    assert result.backend_name == "custom"
    assert result.text == "Hi."
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement custom.py**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skills.youtube_transcribe.backends.base import (
    BackendError,
    BackendNotConfigured,
    TranscriptionResult,
)
from skills.youtube_transcribe.config import get_api_key
from skills.youtube_transcribe.utils.output_writer import Segment


def _build_client(api_key: str, base_url: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=base_url)


@dataclass
class CustomBackend:
    name: str = "custom"
    supports_url: bool = False
    supports_local_file: bool = True

    base_url: str = ""
    model: str = ""

    def is_configured(self) -> tuple[bool, str | None]:
        if not self.base_url:
            return False, ("Не задан base_url для custom-бэкенда. "
                           "Пропиши: `youtube-transcribe config set custom.base_url <URL>`.")
        if not self.model:
            return False, "Не задана model для custom-бэкенда. Пропиши: `youtube-transcribe config set custom.model <NAME>`."
        if not get_api_key("custom"):
            return False, "CUSTOM_API_KEY не задан. Пропиши через `youtube-transcribe config set-key custom`."
        return True, None

    def transcribe(self, audio_or_url, *, language: str = "auto", **opts) -> TranscriptionResult:
        audio = Path(audio_or_url)
        if not audio.exists():
            raise BackendError(f"Audio file not found: {audio}")
        ok, reason = self.is_configured()
        if not ok:
            raise BackendNotConfigured(reason or "")

        client = _build_client(get_api_key("custom"), self.base_url)
        lang = None if language == "auto" else language
        try:
            with audio.open("rb") as f:
                resp = client.audio.transcriptions.create(
                    file=f,
                    model=self.model,
                    language=lang,
                    response_format="verbose_json",
                )
        except Exception as e:
            raise BackendError(f"Custom-бэкенд API ошибка: {e}") from e

        segments_data = getattr(resp, "segments", None) or []
        segments = [
            Segment(
                start=float(s.get("start", 0.0)) if isinstance(s, dict) else float(s.start),
                end=float(s.get("end", 0.0)) if isinstance(s, dict) else float(s.end),
                text=(s.get("text") if isinstance(s, dict) else s.text).strip(),
            )
            for s in segments_data
        ]
        return TranscriptionResult(
            text=getattr(resp, "text", "").strip(),
            segments=segments,
            language_detected=getattr(resp, "language", None),
            backend_name=self.name,
            duration_seconds=float(getattr(resp, "duration", 0.0) or 0.0),
        )
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/backends/custom.py tests/test_custom.py
git commit -m "feat(backends): custom — OpenAI-compatible escape hatch"
```

---

# Phase 4 — Composition + CLI

### Task 18: backends/factory.py — backend factory + smart-mode composition

**Files:**
- Create: `skills/youtube_transcribe/backends/factory.py`
- Create: `tests/test_factory.py`

- [ ] **Step 1: Failing-test**

```python
from unittest.mock import patch, MagicMock
from skills.youtube_transcribe.backends.factory import build_backend, run_smart
from skills.youtube_transcribe.config import Config


def test_build_backend_whisper_local():
    cfg = Config(default_backend="whisper-local")
    b = build_backend("whisper-local", cfg)
    assert b.name == "whisper-local"


def test_build_backend_unknown_raises():
    import pytest
    cfg = Config()
    with pytest.raises(ValueError, match="Unknown backend"):
        build_backend("not-a-backend", cfg)


def test_smart_uses_subtitles_for_youtube_when_available(tmp_path):
    cfg = Config(default_backend="smart", fallback_backend="whisper-local", fast_path_enabled=True)
    fake_subs = MagicMock()
    fake_subs.transcribe.return_value = MagicMock(backend_name="subtitles")
    fake_fallback = MagicMock()

    with patch("skills.youtube_transcribe.backends.factory.build_backend", side_effect=lambda n, c: fake_subs if n == "subtitles" else fake_fallback):
        result = run_smart("https://youtu.be/abc", cfg, language="en")

    assert result.backend_name == "subtitles"
    fake_fallback.transcribe.assert_not_called()


def test_smart_falls_back_when_subtitles_fail(tmp_path):
    cfg = Config(default_backend="smart", fallback_backend="whisper-local", fast_path_enabled=True)
    fake_subs = MagicMock()
    from skills.youtube_transcribe.backends.base import BackendError
    fake_subs.transcribe.side_effect = BackendError("no subs")
    fake_fallback = MagicMock()
    fake_fallback.transcribe.return_value = MagicMock(backend_name="whisper-local")

    with patch("skills.youtube_transcribe.backends.factory.build_backend", side_effect=lambda n, c: fake_subs if n == "subtitles" else fake_fallback):
        result = run_smart("https://youtu.be/abc", cfg, language="en")

    assert result.backend_name == "whisper-local"
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement factory.py**

```python
from __future__ import annotations

from pathlib import Path
from typing import Union

from skills.youtube_transcribe.backends.base import (
    BackendError,
    Transcriber,
    TranscriptionResult,
)
from skills.youtube_transcribe.config import Config
from skills.youtube_transcribe.utils.downloader import is_youtube_url


def build_backend(name: str, cfg: Config) -> Transcriber:
    if name == "whisper-local":
        from skills.youtube_transcribe.backends.whisper_local import WhisperLocalBackend
        from skills.youtube_transcribe.utils.platform_detect import detect_platform
        info = detect_platform()
        impl = info.backend_impl
        device = info.device if cfg.whisper_device == "auto" else cfg.whisper_device
        compute = info.recommended_compute_type if cfg.whisper_compute_type == "auto" else cfg.whisper_compute_type
        return WhisperLocalBackend(
            model=cfg.whisper_model,
            device=device,
            compute_type=compute,
            impl=impl,
            beam_size=cfg.beam_size,
            vad=cfg.vad,
        )
    if name == "subtitles":
        from skills.youtube_transcribe.backends.subtitles import SubtitlesBackend
        return SubtitlesBackend()
    if name == "gemini":
        from skills.youtube_transcribe.backends.gemini import GeminiBackend
        return GeminiBackend(model=cfg.gemini_model)
    if name == "groq":
        from skills.youtube_transcribe.backends.groq import GroqBackend
        return GroqBackend(model=cfg.groq_model)
    if name == "openai":
        from skills.youtube_transcribe.backends.openai_api import OpenAIBackend
        return OpenAIBackend(model=cfg.openai_model)
    if name == "deepgram":
        from skills.youtube_transcribe.backends.deepgram import DeepgramBackend
        return DeepgramBackend(model=cfg.deepgram_model)
    if name == "assemblyai":
        from skills.youtube_transcribe.backends.assemblyai import AssemblyAIBackend
        return AssemblyAIBackend(model=cfg.assemblyai_model)
    if name == "custom":
        from skills.youtube_transcribe.backends.custom import CustomBackend
        return CustomBackend(base_url=cfg.custom_base_url, model=cfg.custom_model)
    raise ValueError(f"Unknown backend: {name}")


def run_smart(
    audio_or_url: Union[str, Path],
    cfg: Config,
    *,
    language: str = "auto",
) -> TranscriptionResult:
    """Try subtitles first for YouTube URLs, then fall back to fallback_backend."""
    src = str(audio_or_url)
    if cfg.fast_path_enabled and is_youtube_url(src):
        try:
            subs = build_backend("subtitles", cfg)
            return subs.transcribe(src, language=language)
        except BackendError:
            pass  # fallthrough
    fb = build_backend(cfg.fallback_backend, cfg)
    return fb.transcribe(audio_or_url, language=language)
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/backends/factory.py tests/test_factory.py
git commit -m "feat(backends): factory + smart-mode composition"
```

---

### Task 19: wizard.py — first-run interactive setup

**Files:**
- Create: `skills/youtube_transcribe/wizard.py`
- Create: `tests/test_wizard.py`

- [ ] **Step 1: Failing-test (covers backend choice + key prompt)**

```python
from pathlib import Path
from unittest.mock import patch
import io
from skills.youtube_transcribe.wizard import run_wizard
from skills.youtube_transcribe.config import Config, load_config


def test_wizard_default_choice_writes_whisper_local(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("skills.youtube_transcribe.wizard.CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr("skills.youtube_transcribe.wizard.ENV_PATH", tmp_path / ".env")
    # Simulate user pressing Enter (default = whisper-local)
    with patch("rich.prompt.Prompt.ask", return_value="1"):
        run_wizard()
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.default_backend == "whisper-local"


def test_wizard_gemini_choice_prompts_for_key(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("skills.youtube_transcribe.wizard.CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr("skills.youtube_transcribe.wizard.ENV_PATH", tmp_path / ".env")
    with patch("rich.prompt.Prompt.ask", side_effect=["4", "test-key-123"]):
        run_wizard()
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.default_backend == "gemini"
    env = (tmp_path / ".env").read_text()
    assert "GEMINI_API_KEY=test-key-123" in env
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement wizard.py**

```python
"""First-run interactive setup wizard."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from skills.youtube_transcribe.config import (
    CONFIG_PATH,
    ENV_PATH,
    Config,
    load_config,
    save_config,
    set_api_key,
)
from skills.youtube_transcribe.utils.platform_detect import detect_platform


_BACKEND_CHOICES = [
    ("whisper-local", "⭐ Локальный Whisper (рекомендуется для сильного железа). Оффлайн, приватно."),
    ("smart",         "Умный: субтитры YouTube → fallback. Быстро на YouTube, надёжно вне его."),
    ("subtitles",     "Только субтитры YouTube. Мгновенно, среднее качество, только YouTube."),
    ("gemini",        "Google AI Studio. Бесплатный free tier. Нужен ключ."),
    ("groq",          "Groq Whisper API. Самый быстрый облачный. Free tier. Нужен ключ."),
    ("openai",        "OpenAI Whisper API. Платно (~$0.006/мин). Нужен ключ."),
    ("deepgram",      "Deepgram Nova-3. $200 стартовый кредит. Нужен ключ."),
    ("assemblyai",    "AssemblyAI. Free tier. Хорош для длинных интервью. Нужен ключ."),
    ("custom",        "OpenAI-совместимый API. Для продвинутых."),
]

_KEY_GUIDE = {
    "gemini":     "https://aistudio.google.com/apikey",
    "groq":       "https://console.groq.com/keys",
    "openai":     "https://platform.openai.com/api-keys",
    "deepgram":   "https://console.deepgram.com/",
    "assemblyai": "https://www.assemblyai.com/dashboard/signup",
    "custom":     "(укажешь свой URL+ключ)",
}


def run_wizard() -> None:
    console = Console()
    info = detect_platform()
    console.print(Panel.fit(
        f"[bold]youtube-transcribe — первая настройка[/bold]\n\n"
        f"Обнаружил: {info.label} (device={info.device}, "
        f"VRAM={info.vram_mb or 'n/a'} MiB)\n"
        f"Рекомендация: [green]whisper-local[/green] (оффлайн, приватно)",
        title="🎬",
    ))

    console.print("\nВыбери движок по умолчанию:\n")
    for i, (name, desc) in enumerate(_BACKEND_CHOICES, start=1):
        console.print(f"  [cyan]{i})[/cyan] [bold]{name}[/bold] — {desc}")

    choice_str = Prompt.ask(
        "\nНомер варианта",
        choices=[str(i) for i in range(1, len(_BACKEND_CHOICES) + 1)],
        default="1",
    )
    backend = _BACKEND_CHOICES[int(choice_str) - 1][0]

    cfg = load_config(CONFIG_PATH)
    cfg.default_backend = backend
    if backend == "smart":
        # Ask for fallback
        console.print("\n[dim]Какой движок использовать как fallback в smart-режиме?[/dim]")
        fb_choice = Prompt.ask(
            "Fallback (1=whisper-local, 2=gemini, 3=groq)",
            choices=["1", "2", "3"], default="1",
        )
        cfg.fallback_backend = {"1": "whisper-local", "2": "gemini", "3": "groq"}[fb_choice]
    save_config(cfg, CONFIG_PATH)

    # Prompt for API key if cloud backend
    if backend in _KEY_GUIDE:
        console.print(f"\n[yellow]Нужен API-ключ.[/yellow] Получить: {_KEY_GUIDE[backend]}")
        key = Prompt.ask(f"Введи {backend.upper()}_API_KEY (или Enter, чтобы пропустить)", default="")
        if key.strip():
            set_api_key(backend, key.strip(), env_path=ENV_PATH)
            console.print(f"[green]✓[/green] Ключ сохранён в {ENV_PATH}")

    console.print(f"\n[green]✓ Настроено.[/green] Дефолтный движок: [bold]{backend}[/bold]")
    console.print(f"Поменять выбор: [cyan]youtube-transcribe config wizard[/cyan]")
    console.print(f"Использовать другой движок разово: [cyan]--backend gemini[/cyan]\n")
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/wizard.py tests/test_wizard.py
git commit -m "feat: first-run wizard with hardware detection and key prompts"
```

---

### Task 20: transcribe.py — main CLI entry point (transcribe sub-command)

**Files:**
- Create: `skills/youtube_transcribe/transcribe.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Failing-test (CLI invocation via Click testing)**

```python
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from pathlib import Path

from skills.youtube_transcribe.transcribe import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "transcribe" in result.output.lower()


def test_transcribe_local_file_invokes_backend(tmp_path: Path):
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"f")
    fake_backend = MagicMock()
    fake_result = MagicMock(text="hi", segments=[], language_detected="en", backend_name="whisper-local", duration_seconds=1.0)
    fake_backend.transcribe.return_value = fake_result

    runner = CliRunner()
    with patch("skills.youtube_transcribe.transcribe.run_wizard"), \
         patch("skills.youtube_transcribe.transcribe.CONFIG_PATH") as cp, \
         patch("skills.youtube_transcribe.transcribe.build_backend", return_value=fake_backend), \
         patch("skills.youtube_transcribe.transcribe.is_url", return_value=False), \
         patch("skills.youtube_transcribe.transcribe.write_txt_with_timestamps"), \
         patch("skills.youtube_transcribe.transcribe.write_srt"):
        cp.exists.return_value = True  # skip wizard
        result = runner.invoke(cli, ["transcribe", str(audio), "--backend", "whisper-local", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    fake_backend.transcribe.assert_called_once()
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement transcribe.py (transcribe sub-command, plus skeleton for config sub-commands in Task 21)**

```python
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from skills.youtube_transcribe.backends.base import BackendError, BackendNotConfigured
from skills.youtube_transcribe.backends.factory import build_backend, run_smart
from skills.youtube_transcribe.config import (
    CONFIG_PATH,
    Config,
    load_config,
    save_config,
)
from skills.youtube_transcribe.utils.downloader import (
    download_audio,
    is_url,
    is_youtube_url,
    maybe_auto_update_ytdlp,
)
from skills.youtube_transcribe.utils.output_writer import (
    write_srt,
    write_txt_plain,
    write_txt_with_timestamps,
    sanitize_filename,
)
from skills.youtube_transcribe.wizard import run_wizard

console = Console()

BACKEND_CHOICES = [
    "smart", "subtitles", "whisper-local",
    "gemini", "groq", "openai", "deepgram", "assemblyai", "custom",
]


@click.group(invoke_without_command=False)
@click.version_option()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """youtube-transcribe — transcribe YouTube and local media via 8 backends."""
    pass


@cli.command(name="transcribe")
@click.argument("audio_or_url")
@click.option("--backend", type=click.Choice(BACKEND_CHOICES), default=None,
              help="Backend to use (overrides config default).")
@click.option("--whisper-model", type=click.Choice(["turbo", "large", "medium", "small", "distil"]),
              default=None, help="Whisper model (only with --backend whisper-local).")
@click.option("--gemini-model", default=None)
@click.option("--groq-model", default=None)
@click.option("--deepgram-model", default=None)
@click.option("--assemblyai-model", default=None)
@click.option("--language", default=None, help="Language code (ru/en/...) or 'auto'.")
@click.option("--output-dir", default=None, help="Output directory.")
@click.option("--timestamps/--no-timestamps", default=None)
@click.option("--srt/--no-srt", default=None)
@click.option("--keep-audio/--delete-audio", default=None)
@click.option("--cookies-from-browser", "cookies_browser", default=None,
              type=click.Choice(["", "chrome", "firefox", "edge", "safari"]))
@click.option("--no-fast-path", is_flag=True, help="Disable subtitles fast-path in smart mode.")
@click.option("--device", default=None)
@click.option("--compute-type", default=None)
@click.option("--beam-size", type=int, default=None)
@click.option("--vad/--no-vad", default=None)
@click.option("--verbose", is_flag=True)
def transcribe_cmd(audio_or_url: str, **opts) -> None:
    """Transcribe a YouTube URL or local audio/video file."""
    if not CONFIG_PATH.exists():
        run_wizard()

    cfg = load_config(CONFIG_PATH)
    cfg = _override_config(cfg, opts)

    backend_name = opts.get("backend") or cfg.default_backend
    output_dir = Path(opts.get("output_dir") or cfg.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    keep_audio = cfg.keep_audio if opts.get("keep_audio") is None else opts["keep_audio"]
    if opts.get("no_fast_path"):
        cfg.fast_path_enabled = False

    # If URL, prefer routing through smart (which knows about subtitles fast path)
    # or download first if backend doesn't support URL
    audio_path: Path
    cleanup_path: Path | None = None

    if is_url(audio_or_url):
        if backend_name == "subtitles":
            audio_path = audio_or_url  # type: ignore[assignment]
        elif backend_name == "smart":
            audio_path = audio_or_url  # type: ignore[assignment]
        else:
            maybe_auto_update_ytdlp(cfg.yt_dlp_auto_update)
            tmp_dir = output_dir / ".yt-cache"
            audio_path = download_audio(
                audio_or_url, tmp_dir,
                cookies_browser=cfg.cookies_browser,
            )
            if not keep_audio:
                cleanup_path = audio_path
    else:
        audio_path = Path(audio_or_url).expanduser().resolve()
        if not audio_path.exists():
            console.print(f"[red]Файл не найден:[/red] {audio_path}")
            sys.exit(2)

    language = opts.get("language") or cfg.language

    try:
        if backend_name == "smart":
            result = run_smart(audio_path, cfg, language=language)
        else:
            backend = build_backend(backend_name, cfg)
            result = backend.transcribe(audio_path, language=language)
    except BackendNotConfigured as e:
        console.print(f"[red]Бэкенд не настроен:[/red] {e}")
        sys.exit(3)
    except BackendError as e:
        console.print(f"[red]Ошибка транскрипции:[/red] {e}")
        sys.exit(4)

    # Write outputs
    base_name = sanitize_filename(_derive_basename(audio_or_url))
    txt_path = output_dir / f"{base_name}.txt"
    srt_path = output_dir / f"{base_name}.srt"

    timestamps = cfg.timestamps if opts.get("timestamps") is None else opts["timestamps"]
    write_srt_flag = cfg.srt if opts.get("srt") is None else opts["srt"]

    if timestamps:
        write_txt_with_timestamps(result.segments, txt_path)
    else:
        write_txt_plain(result.segments, txt_path)
    if write_srt_flag:
        write_srt(result.segments, srt_path)

    console.print(f"[green]✓[/green] {result.backend_name} | "
                  f"язык={result.language_detected or 'auto'} | "
                  f"длительность={result.duration_seconds:.1f}s")
    console.print(f"  [bold]{txt_path}[/bold]")
    if write_srt_flag:
        console.print(f"  [bold]{srt_path}[/bold]")

    if cleanup_path and cleanup_path.exists():
        try:
            cleanup_path.unlink()
        except OSError:
            pass


def _derive_basename(audio_or_url: str) -> str:
    if is_url(audio_or_url):
        from skills.youtube_transcribe.utils.downloader import extract_youtube_video_id
        vid = extract_youtube_video_id(audio_or_url)
        return f"yt_{vid}" if vid else "url_transcript"
    return Path(audio_or_url).stem


def _override_config(cfg: Config, opts: dict) -> Config:
    """Apply CLI overrides to a Config copy."""
    if opts.get("whisper_model"): cfg.whisper_model = opts["whisper_model"]
    if opts.get("gemini_model"): cfg.gemini_model = opts["gemini_model"]
    if opts.get("groq_model"): cfg.groq_model = opts["groq_model"]
    if opts.get("deepgram_model"): cfg.deepgram_model = opts["deepgram_model"]
    if opts.get("assemblyai_model"): cfg.assemblyai_model = opts["assemblyai_model"]
    if opts.get("device"): cfg.whisper_device = opts["device"]
    if opts.get("compute_type"): cfg.whisper_compute_type = opts["compute_type"]
    if opts.get("beam_size"): cfg.beam_size = opts["beam_size"]
    if opts.get("vad") is not None: cfg.vad = opts["vad"]
    if opts.get("cookies_browser") is not None: cfg.cookies_browser = opts["cookies_browser"]
    return cfg


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/transcribe.py tests/test_cli.py
git commit -m "feat(cli): main transcribe sub-command with URL/file routing and overrides"
```

---

### Task 21: Sub-команды config — show/set/set-key/test/wizard

**Files:**
- Modify: `skills/youtube_transcribe/transcribe.py` (добавить `config` группу)
- Create: `tests/test_config_cli.py`

- [ ] **Step 1: Failing-test**

```python
from click.testing import CliRunner
from unittest.mock import patch
from pathlib import Path

from skills.youtube_transcribe.transcribe import cli


def test_config_show(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("skills.youtube_transcribe.config.CONFIG_PATH", tmp_path / "config.toml")
    runner = CliRunner()
    r = runner.invoke(cli, ["config", "show"])
    assert r.exit_code == 0
    assert "default_backend" in r.output


def test_config_set_backend(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("skills.youtube_transcribe.transcribe.CONFIG_PATH", tmp_path / "config.toml")
    runner = CliRunner()
    r = runner.invoke(cli, ["config", "set", "backend", "groq"])
    assert r.exit_code == 0
    text = (tmp_path / "config.toml").read_text()
    assert "groq" in text


def test_config_set_key(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("skills.youtube_transcribe.transcribe.ENV_PATH", tmp_path / ".env")
    runner = CliRunner()
    r = runner.invoke(cli, ["config", "set-key", "gemini"], input="test-key\n")
    assert r.exit_code == 0
    assert "GEMINI_API_KEY=test-key" in (tmp_path / ".env").read_text()
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Append to `transcribe.py`**

```python
@cli.group()
def config():
    """Manage configuration and API keys."""


@config.command("show")
def config_show() -> None:
    cfg = load_config(CONFIG_PATH)
    from skills.youtube_transcribe.config import get_api_key, mask_key
    console.print(f"[bold]Config file:[/bold] {CONFIG_PATH}")
    for field_name, value in cfg.__dict__.items():
        console.print(f"  {field_name} = {value}")
    console.print("\n[bold]API keys:[/bold]")
    for backend in ["gemini", "groq", "openai", "deepgram", "assemblyai", "custom"]:
        k = get_api_key(backend)
        console.print(f"  {backend}: {mask_key(k) if k else '[dim]not set[/dim]'}")


_SET_KEY_TO_FIELD = {
    "backend": "default_backend",
    "fallback": "fallback_backend",
    "whisper-model": "whisper_model",
    "gemini-model": "gemini_model",
    "groq-model": "groq_model",
    "openai-model": "openai_model",
    "deepgram-model": "deepgram_model",
    "assemblyai-model": "assemblyai_model",
    "language": "language",
    "output-dir": "output_dir",
    "cookies-browser": "cookies_browser",
    "custom.base_url": "custom_base_url",
    "custom.model": "custom_model",
}


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    field = _SET_KEY_TO_FIELD.get(key)
    if not field:
        console.print(f"[red]Unknown key:[/red] {key}")
        console.print(f"Known keys: {', '.join(_SET_KEY_TO_FIELD.keys())}")
        sys.exit(2)
    cfg = load_config(CONFIG_PATH)
    setattr(cfg, field, value)
    save_config(cfg, CONFIG_PATH)
    console.print(f"[green]✓[/green] {key} = {value}")


@config.command("set-key")
@click.argument("backend", type=click.Choice(
    ["gemini", "groq", "openai", "deepgram", "assemblyai", "custom"]
))
def config_set_key(backend: str) -> None:
    from skills.youtube_transcribe.config import set_api_key, ENV_PATH
    key = click.prompt(f"{backend.upper()}_API_KEY", hide_input=True, default="")
    if key:
        set_api_key(backend, key, env_path=ENV_PATH)
        console.print(f"[green]✓[/green] saved to {ENV_PATH}")


@config.command("test")
@click.argument("backend", type=click.Choice(BACKEND_CHOICES))
def config_test(backend: str) -> None:
    """Run a quick configuration sanity check (no real audio)."""
    cfg = load_config(CONFIG_PATH)
    try:
        b = build_backend(backend, cfg)
    except Exception as e:
        console.print(f"[red]✗[/red] build_backend failed: {e}")
        sys.exit(2)
    ok, reason = b.is_configured()
    if ok:
        console.print(f"[green]✓[/green] {backend} is configured")
    else:
        console.print(f"[red]✗[/red] {backend}: {reason}")
        sys.exit(3)


@config.command("wizard")
def config_wizard() -> None:
    run_wizard()
```

Add `from skills.youtube_transcribe.config import ENV_PATH` to imports.

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add skills/youtube_transcribe/transcribe.py tests/test_config_cli.py
git commit -m "feat(cli): config sub-commands (show/set/set-key/test/wizard)"
```

---

# Phase 5 — Claude Code integration + docs

### Task 22: SKILL.md — triggers + anti-triggers + multilingual instructions

**Files:**
- Create: `skills/youtube_transcribe/SKILL.md`

- [ ] **Step 1: Создать SKILL.md**

```markdown
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
  or provides a local media file. Also use for explicit backend switching ("через gemini",
  "локально whisper large", "use groq"). DO NOT use for: general questions about
  transcription technology, requesting video recommendations, recording/creating videos,
  or operating on already-existing transcripts. Works in Russian, English, Ukrainian,
  Kazakh, German, Spanish, French — semantic match, not regex.
---

# youtube-transcribe Skill

## Trigger conditions

**Use this skill when** any of these are true in the user's message:

- A YouTube URL (`youtube.com/watch?v=...`, `youtu.be/...`, `youtube.com/shorts/...`) appears, with or without surrounding words.
- Any video URL (TikTok, Vimeo, Twitter/X video, Twitch VOD, etc.) appears with intent to extract content.
- A local file path ending in `.mp3 / .mp4 / .wav / .m4a / .mkv / .webm / .opus / .flac` appears with intent to extract speech.
- Direct request: "транскрибируй", "расшифруй", "сделай текст", "transcribe", "get transcript", "розшифруй", "yazıya geçir".
- Request for subtitles: ".srt", "сделай субтитры", "make subtitles", "give me subs".
- Content-question about a linked video: "о чём это видео", "what's in this video", "что говорят".
- Request to summarize/analyze a video by URL (transcribe first, then Claude analyzes).
- Request for timestamps, quotes, or time-coded references in a video.
- Backend switching: "через gemini", "локально whisper", "use groq", "switch to subtitles".

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

```
youtube-transcribe transcribe <URL_or_path> [flags]
```

### Default behavior

- No flags → uses configured default backend (usually `whisper-local`).
- First-run automatically launches `wizard` (interactive setup).
- Output goes to `./transcripts/<name>.txt` and `<name>.srt`.

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

Always read the generated `.txt` file and offer the user a short summary or answer their original question (was the URL with "о чём это видео"? answer that). Do NOT echo the entire transcript back unless asked.

If the run fails, the CLI prints a friendly hint (yt-dlp blocked → cookies, key missing → set-key, etc.). Relay the hint to the user clearly.

## Privacy note

The default backend (`whisper-local`) processes everything locally — nothing is sent to the network. Cloud backends (gemini, groq, openai, deepgram, assemblyai, custom) DO send the audio to the respective provider. Mention this if the user asks about privacy or seems sensitive about the content.
```

- [ ] **Step 2: Commit**

```bash
git add skills/youtube_transcribe/SKILL.md
git commit -m "feat(skill): SKILL.md with multilingual triggers, anti-triggers, and 3-level backend switching"
```

---

### Task 23: commands/transcribe.md — slash command

**Files:**
- Create: `commands/transcribe.md`

- [ ] **Step 1: Создать commands/transcribe.md**

```bash
mkdir -p commands
```

```markdown
---
description: Transcribe a YouTube URL or local media file. Usage — /transcribe <URL_or_path> [--backend X] [--whisper-model Y] [--language ru]
argument-hint: <URL_or_path> [flags]
---

Run `youtube-transcribe transcribe $ARGUMENTS` and report results back to the user.

If `$ARGUMENTS` is empty, prompt the user for a URL or file path.

After the command finishes:
1. Read the generated `.txt` file from `./transcripts/`.
2. Give the user a brief one-paragraph summary of what's in the transcript.
3. Offer follow-up actions: full text, search inside, translate, generate subtitles, summarize per timestamp.

If the command exits non-zero, the stdout/stderr will contain a friendly hint — relay it to the user (e.g., "API key missing", "yt-dlp blocked, try `--cookies-from-browser chrome`").
```

- [ ] **Step 2: Commit**

```bash
git add commands/transcribe.md
git commit -m "feat(commands): /transcribe slash command"
```

---

### Task 24: README.md — двухслойный

**Files:**
- Create: `README.md`

- [ ] **Step 1: Создать README.md**

(Это длинный файл — около 500 строк. Реализатор пишет согласно структуре спеки раздел 14. Минимально: заголовок, одно предложение, три способа установки, быстрый старт, какое железо нужно (таблица), управление движками (три уровня), частые ошибки (с блоком про YouTube anti-bot updates), потом более детальный слой: архитектура, сравнение моделей, как работают облачные бэкенды, smart-режим внутри, тонкая настройка, расширение, roadmap.)

Минимальный шаблон-стартер для реализатора (на нём раскрывать остальное):

```markdown
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

## Install

### Option A — Claude Code plugin (recommended)

```bash
git clone https://github.com/<your-github-username>/youtube-transcribe ~/.claude/plugins/youtube-transcribe
cd ~/.claude/plugins/youtube-transcribe
uv sync
```

Then `youtube-transcribe config wizard` to set up. Reload Claude Code if needed.

### Option B — Personal skill folder

```bash
git clone https://github.com/<your-github-username>/youtube-transcribe /tmp/yt-transcribe
cp -r /tmp/yt-transcribe/skills/youtube_transcribe ~/.claude/skills/
cd ~/.claude/skills/youtube_transcribe && uv sync
```

### Option C — Standalone CLI (no Claude needed)

```bash
uv tool install git+https://github.com/<your-github-username>/youtube-transcribe
```

[See INSTALL.md for fallback paths if you don't have `uv`.]

---

## Quick start

```bash
# Default: offline whisper-local
youtube-transcribe transcribe https://youtu.be/dQw4w9WgXcQ --language en

# Use cloud backend
youtube-transcribe transcribe video.mp4 --backend gemini

# In Claude chat
"Расшифруй вот это: https://youtu.be/abc"
"Use gemini for this one: <URL>"
"/transcribe https://youtu.be/xyz"
```

---

## Hardware guide

[Insert table from spec section 14.]

---

## Backends overview

[Brief table summarizing all 8.]

---

## Switching backends in chat (3 levels)

[Per-call / session / persistent — copy from spec section 7.]

---

## Common errors

### "Sign in to confirm you're not a bot" (yt-dlp 403)

YouTube periodically rotates anti-bot measures, breaking yt-dlp once every 1–3 months globally. **This is not a bug in this tool.** Fix:

1. `youtube-transcribe update-deps` — updates yt-dlp to the latest release.
2. If still failing: `youtube-transcribe transcribe <URL> --cookies-from-browser chrome`.
3. If still failing: open an issue, fix usually lands in a few days.

### Other errors

[List from spec.]

---

## Privacy

| Backend | Audio leaves your machine? |
|---|---|
| `whisper-local` | ❌ never |
| `subtitles` (YouTube) | ❌ but YouTube sees the request |
| `gemini`, `groq`, `openai`, `deepgram`, `assemblyai`, `custom` | ✅ uploaded to provider |

Read the provider's ToS. We never log/print full API keys; they're masked in `config show`.

---

## Architecture (for developers)

[Diagram + description of `Transcriber` Protocol and how to add a new backend.]

---

## Roadmap

- v2: Diarization (who-said-what) via `pyannote-audio`
- v2: Chunking for >2h videos
- v2: Built-in summarization via local or cloud LLM
- v2: PyPI publication
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with three install paths, hardware guide, and error troubleshooting"
```

---

### Task 25: install.ps1 + install.sh — bootstrap fallback

**Files:**
- Create: `install.ps1`
- Create: `install.sh`

- [ ] **Step 1: install.ps1**

```powershell
# install.ps1 — bootstrap installer for Windows
param(
    [string]$InstallMethod = "plugin"  # plugin | skill | cli
)

$ErrorActionPreference = "Stop"

Write-Host "==> Checking for uv..." -ForegroundColor Cyan
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "==> Syncing dependencies..." -ForegroundColor Cyan
uv sync

Write-Host "==> Running wizard..." -ForegroundColor Cyan
uv run youtube-transcribe config wizard

Write-Host "==> Done!" -ForegroundColor Green
Write-Host "Try: uv run youtube-transcribe transcribe https://youtu.be/<id>"
```

- [ ] **Step 2: install.sh**

```bash
#!/usr/bin/env bash
# install.sh — bootstrap installer for macOS/Linux
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
    echo "==> Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> Checking ffmpeg..."
if ! command -v ffmpeg >/dev/null 2>&1; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew >/dev/null 2>&1; then
            brew install ffmpeg
        else
            echo "WARNING: ffmpeg not found and Homebrew not installed."
            echo "Install ffmpeg manually before transcribing."
        fi
    else
        echo "WARNING: ffmpeg not found. Install via your package manager (apt, dnf, pacman)."
    fi
fi

echo "==> Syncing dependencies..."
uv sync

echo "==> Running wizard..."
uv run youtube-transcribe config wizard

echo "==> Done!"
echo "Try: uv run youtube-transcribe transcribe https://youtu.be/<id>"
```

- [ ] **Step 3: Make install.sh executable + commit**

```bash
chmod +x install.sh 2>/dev/null || true
git add install.ps1 install.sh
git commit -m "chore: install scripts for Win and macOS/Linux fallback"
```

---

# Phase 6 — Smoke test + handoff

### Task 26: End-to-end smoke test on a short YouTube video

**Files:** none — manual verification + `tests/test_e2e_smoke.py` (skipped by default)

- [ ] **Step 1: Pick a short public YouTube video (≤60 sec, e.g. official trailers, government PSAs, or a Creative Commons short).**

Suggested test URL: `https://www.youtube.com/watch?v=jNQXAC9IVRw` ("Me at the zoo", 19 seconds, public domain).

- [ ] **Step 2: Run the full pipeline manually**

```powershell
# From E:\CLAUDE\youtube-transcribe
uv run youtube-transcribe transcribe https://www.youtube.com/watch?v=jNQXAC9IVRw --backend whisper-local --language en --output-dir ./test-output
```

Expected:
- yt-dlp downloads audio to `./test-output/.yt-cache/`
- whisper-local transcribes
- `./test-output/yt_jNQXAC9IVRw.txt` and `.srt` are created
- Console shows `✓ whisper-local | язык=en | длительность=...`

- [ ] **Step 3: Verify each output**

- [ ] `.txt` exists, has timestamps in `[HH:MM:SS.mmm --> HH:MM:SS.mmm]` format, contains recognizable English text.
- [ ] `.srt` exists, has `1\n00:00:00,000 --> ...` blocks.
- [ ] Audio cache cleaned up (or kept if `--keep-audio`).

- [ ] **Step 4: Run the same with `--backend subtitles`**

```powershell
uv run youtube-transcribe transcribe https://www.youtube.com/watch?v=jNQXAC9IVRw --backend subtitles --language en --output-dir ./test-output
```

Expected: completes in <5 sec, produces same kind of output.

- [ ] **Step 5: Run the unit suite end-to-end**

```powershell
uv run pytest -q
```

Expected: All tests pass, no skipped failures.

- [ ] **Step 6: Add `tests/test_e2e_smoke.py` (marked as skip-by-default)**

```python
import os
import shutil
import subprocess
from pathlib import Path
import pytest


@pytest.mark.skipif(
    os.environ.get("RUN_E2E_SMOKE") != "1",
    reason="Set RUN_E2E_SMOKE=1 to run end-to-end smoke against YouTube",
)
def test_e2e_short_youtube(tmp_path: Path):
    if not shutil.which("yt-dlp"):
        pytest.skip("yt-dlp not on PATH")
    out = tmp_path / "out"
    r = subprocess.run(
        [
            "uv", "run", "youtube-transcribe", "transcribe",
            "https://www.youtube.com/watch?v=jNQXAC9IVRw",
            "--backend", "subtitles",
            "--language", "en",
            "--output-dir", str(out),
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert any(out.glob("*.txt"))
    assert any(out.glob("*.srt"))
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_e2e_smoke.py
git commit -m "test: end-to-end smoke (skipped by default; run with RUN_E2E_SMOKE=1)"
```

---

### Task 27: Pre-Mac handoff — clean state + push to GitHub

**Files:** none — git operations + checklist

- [ ] **Step 1: Run full test suite**

```powershell
uv run pytest -v
```

Expected: ALL pass. No fail, no error. Skipped tests OK only for `e2e_smoke`.

- [ ] **Step 2: Verify git status is clean**

```powershell
git status
git log --oneline | Select-Object -First 30
```

Should see all the commits from Tasks 1–26. No untracked files except possibly `transcripts/` (gitignored) and `.venv/`.

- [ ] **Step 3: Quick manual smoke verification**

In PowerShell:
```powershell
uv run youtube-transcribe --help
uv run youtube-transcribe transcribe --help
uv run youtube-transcribe config show
```

All three should print clean output without errors.

- [ ] **Step 4: Create GitHub repo (manual step by user)**

User goes to https://github.com/new, creates `youtube-transcribe` (public or private — user's choice). Do NOT initialize with README/LICENSE/.gitignore (we already have them).

- [ ] **Step 5: Add remote + push**

```bash
git remote add origin https://github.com/<your-username>/youtube-transcribe.git
git branch -M main
git push -u origin main
```

- [ ] **Step 6: Verify push**

```bash
git log --oneline origin/main | Select-Object -First 5
```

Should mirror local main.

- [ ] **Step 7: Tag a v0.1.0-pre-mac release**

```bash
git tag -a v0.1.0-pre-mac -m "Pre-Mac validation release. Windows tests pass; mlx-whisper untested."
git push origin v0.1.0-pre-mac
```

This gives a recovery point if anything breaks during Mac validation.

---

# Phase 7 — Mac validation (выполняется на Mac)

> **Контекст:** Phase 1–6 выполнены на Windows. Реализатор переключается на Mac (Apple Silicon). Все следующие задачи — на Mac.

### Task 28: Mac setup — clone, install, run wizard

**Pre-requisites:** macOS Apple Silicon (M1/M2/M3/M4), macOS 13+, Xcode Command Line Tools (`xcode-select --install`), Homebrew.

- [ ] **Step 1: Clone the repo**

```bash
cd ~/Projects        # or any folder you like
git clone https://github.com/<your-username>/youtube-transcribe.git
cd youtube-transcribe
```

- [ ] **Step 2: Install ffmpeg via Homebrew (required for yt-dlp)**

```bash
brew install ffmpeg
ffmpeg -version  # should print version
```

- [ ] **Step 3: Install uv (if not already)**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Reopen terminal or:
source ~/.zshrc
uv --version  # should print 0.4+
```

- [ ] **Step 4: Sync deps (this triggers mlx-whisper install on Apple Silicon)**

```bash
uv sync
```

Expected: ~1–3 minutes. Watch for any error in mlx-whisper install. If install fails, common causes:
- macOS too old (mlx requires 13.5+) → upgrade macOS.
- Not actually arm64 (e.g. running x86_64 Python under Rosetta) → check with `python -c "import platform; print(platform.machine())"` — must print `arm64`.

- [ ] **Step 5: Run smoke check on platform_detect**

```bash
uv run python -c "from skills.youtube_transcribe.utils.platform_detect import detect_platform; print(detect_platform())"
```

Expected: `PlatformInfo(label='apple-silicon', backend_impl='mlx', device='mps', vram_mb=None, recommended_compute_type='auto')`

If `backend_impl` says `faster` instead of `mlx` — your Python is x86_64 under Rosetta. Fix Python before continuing.

- [ ] **Step 6: Run wizard, choose whisper-local**

```bash
uv run youtube-transcribe config wizard
```

Pick option 1 (whisper-local). Verify config saved at `~/.youtube-transcribe/config.toml`.

- [ ] **Step 7: Run unit tests on Mac**

```bash
uv run pytest -v
```

Expected: ALL pass, including `test_transcribe_calls_mlx_whisper` (which uses mock — should still pass).

If any test fails: capture stdout/stderr, paste into a new commit message body for context, and proceed to debug. Do NOT proceed to Task 29 with red tests.

---

### Task 29: Mac validation — run real mlx-whisper transcription

- [ ] **Step 1: Run the same 19-sec YouTube video through mlx-whisper**

```bash
uv run youtube-transcribe transcribe https://www.youtube.com/watch?v=jNQXAC9IVRw \
    --backend whisper-local \
    --whisper-model turbo \
    --language en \
    --output-dir ./test-output
```

Expected:
- Phrase like `Loading mlx model: mlx-community/whisper-large-v3-turbo` (model download on first run, ~600 MB).
- Transcription completes in <30 seconds total (incl. download).
- `./test-output/yt_jNQXAC9IVRw.txt` and `.srt` populated with English text matching the video.

- [ ] **Step 2: Verify output quality**

Open `.txt` — recognizable English. If you see gibberish, something's off — capture and report.

- [ ] **Step 3: Try a longer Russian video (optional but valuable)**

If you have time and a 2–5 minute Russian YouTube video on hand:

```bash
uv run youtube-transcribe transcribe <URL> --backend whisper-local --language ru
```

Verify output is coherent Russian.

- [ ] **Step 4: Run all 5 Whisper models to confirm MODEL_MAP**

```bash
for m in turbo large medium small; do
    uv run youtube-transcribe transcribe https://www.youtube.com/watch?v=jNQXAC9IVRw \
        --backend whisper-local --whisper-model $m --language en --output-dir ./test-output-$m
done
```

(`distil` is faster-whisper-only; will produce a friendly error on Mac — that's expected and correct behavior.)

For `distil`, verify the error message:

```bash
uv run youtube-transcribe transcribe https://www.youtube.com/watch?v=jNQXAC9IVRw \
    --backend whisper-local --whisper-model distil --language en --output-dir ./tmp
```

Expected: exit code 4, error mentions "distil" + "mlx" not supported.

- [ ] **Step 5: Note Mac specifics in README**

Update the hardware table or "Mac note" with the actual M-series model used (e.g., "Tested on M2 Pro, macOS 14.5 — turbo runs in ~20 sec for 60 sec video").

```bash
# Example edit to README.md
git commit -am "docs: confirm Mac validation on <your-model> macOS <version>"
```

- [ ] **Step 6: Push the doc update**

```bash
git push origin main
```

---

### Task 30: Final sign-off

- [ ] **Step 1: Run full test suite one more time**

```bash
uv run pytest -v
RUN_E2E_SMOKE=1 uv run pytest -v   # optional, hits real YouTube
```

- [ ] **Step 2: Tag v0.1.0**

```bash
git tag -a v0.1.0 -m "First public release. Windows + Mac validated."
git push origin v0.1.0
```

- [ ] **Step 3: (Optional) Polish README, add screenshots, finalize hardware table**

- [ ] **Step 4: Announce/share**

Repo is ready. Anyone can install via:
- `git clone https://github.com/<user>/youtube-transcribe ~/.claude/plugins/youtube-transcribe`
- `uv tool install git+https://github.com/<user>/youtube-transcribe`

---

## Self-review (writer's checklist — fix inline)

**Spec coverage:** Each spec section maps to one or more tasks:

- §3 Distribution → Task 1 (pyproject), Task 3 (plugin.json), Task 25 (install scripts)
- §4 Architecture → file structure listed at plan top
- §5 All 8 backends → Tasks 9–17
- §6 Wizard → Task 19
- §7 Three-level switching → Task 22 (SKILL.md), Task 21 (config CLI)
- §8 CLI flags → Tasks 20–21
- §9 Slash command → Task 23
- §10 Triggers → Task 22
- §11 Downloader → Task 7
- §12 Output writer → Task 5
- §13 Config + secrets → Task 6
- §14 README → Task 24
- §15 Tests → Tasks 4–18 (unit), Task 26 (e2e)
- §16 Out of scope → not implemented (correct)
- §17 Risks → addressed in Task 7 (yt-dlp), Tasks 28–29 (Mac validation)
- §18 Final checklist → Task 30

**Placeholder scan:** No "TBD" / "TODO". Task 24 README is a "starter template" by design — full content is left for the implementer to flesh out from the spec, but every section heading is concrete and the content rules are spelled out (hardware table, switching examples, etc.). Task 17 `_resolve_compute_type` uses default safe choice — explicit, not a placeholder.

**Type consistency:** `Segment` defined in Task 5, used identically in Tasks 8–18. `TranscriptionResult` defined in Task 8, returned by every backend with same fields. `Config` defined in Task 6, mutated only via `_override_config` (Task 20) and `config set` (Task 21). `BackendError` / `BackendNotConfigured` raised consistently.

---

## Что дальше

После сохранения этого плана — выбор способа исполнения.
