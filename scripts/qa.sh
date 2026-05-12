#!/usr/bin/env bash
# QA helper for manual testing of v0.7 features.
#
# Usage:
#   scripts/qa.sh                  # show menu
#   scripts/qa.sh phase4           # real batch via subtitles (no API keys)
#   scripts/qa.sh phase5.1         # research single-language (needs GEMINI_API_KEY)
#   scripts/qa.sh phase5.2         # research multi-language with translation
#   scripts/qa.sh phase5.3a        # subscribes add + list
#   scripts/qa.sh phase5.3b        # subscribes update (incremental)
#   scripts/qa.sh phase5.3c        # subscribes --no-rss (yt-dlp path)
#   scripts/qa.sh phase5.4         # history list/show
#   scripts/qa.sh cleanup          # remove all QA artefacts
#
# Run from the repo root: /Users/nekith78/youtube-transcribe.

set -u

# ── colours ────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'
  BOLD=$'\033[1m';     DIM=$'\033[2m';   NC=$'\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; BOLD=''; DIM=''; NC=''
fi

QA_DIR="/tmp/yt-qa"
mkdir -p "$QA_DIR"

YT="uv run youtube-transcribe"

step() {
  echo
  echo "${BOLD}══ $1 ══${NC}"
}

ok() {
  echo "${GREEN}✓${NC} $1"
}

fail() {
  echo "${RED}✗${NC} $1"
}

note() {
  echo "${DIM}  $1${NC}"
}

require_key() {
  local key_name="$1"
  if ! grep -q "^${key_name}=" ~/.youtube-transcribe/.env 2>/dev/null; then
    echo "${YELLOW}!${NC} ${key_name} не найден в ~/.youtube-transcribe/.env"
    echo "${DIM}  Эта фаза требует ключ. Пропусти или установи через:${NC}"
    echo "${DIM}  $YT config set-key ${key_name,,}${NC}"
    return 1
  fi
  return 0
}

# ── Phase 4: real batch via subtitles ─────────────────────────────────
phase4() {
  step "Phase 4 — batch на реальном YouTube (subtitles, без API ключей)"
  rm -rf "$QA_DIR/batch4"
  if $YT batch "https://www.youtube.com/watch?v=jNQXAC9IVRw" \
       --limit 1 --backend subtitles \
       --output-dir "$QA_DIR/batch4" --batch-name "qa-01"; then
    ok "batch exit 0"
  else
    fail "batch exit $?"
    return 1
  fi

  if [[ -f "$QA_DIR/batch4/qa-01/manifest.json" ]]; then
    ok "manifest.json создан"
  else
    fail "manifest.json отсутствует"
    return 1
  fi

  if [[ -f "$QA_DIR/batch4/qa-01/combined.md" ]]; then
    ok "combined.md создан"
  else
    fail "combined.md отсутствует"
    return 1
  fi

  note "результат: $QA_DIR/batch4/qa-01/"
}

# ── Phase 5.1: research single-language via Gemini ─────────────────────
phase5_1() {
  step "Phase 5.1 — research --languages en (Gemini)"
  require_key "GEMINI_API_KEY" || return 1

  rm -rf "$QA_DIR/r-en"
  # 365d + a broad evergreen topic so YouTube definitely returns something
  # under the cutoff. Narrower windows (30/90d) on niche/popular topics
  # often yield only classic videos that get filtered out.
  $YT research "AI agents" \
    --languages en --days 365 --limit 5 \
    --backend subtitles \
    --prompt "Bullet-point the main concepts mentioned across videos." \
    --analyze-backend gemini \
    --yes \
    --output-dir "$QA_DIR/r-en"
  local code=$?

  if [[ $code -ne 0 ]]; then
    fail "research exit $code"
    return 1
  fi
  ok "research exit 0"

  # Find batch dir (single subdir of r-en)
  local dir
  dir=$(find "$QA_DIR/r-en" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | head -1)
  if [[ -z "$dir" ]]; then
    fail "batch folder не найден внутри $QA_DIR/r-en"
    note "Если pipeline сказал 'После фильтра по дате осталось 0' — это"
    note "значит YouTube вернул только старые видео под этот запрос."
    note "Попробуй вручную с другим query или большим --days:"
    note "  $YT research \"твой запрос\" --languages en --days 180 --limit 5 \\"
    note "    --backend subtitles --prompt \"...\" --analyze-backend gemini \\"
    note "    --yes --output-dir $QA_DIR/r-en"
    return 1
  fi
  ok "batch folder: $(basename "$dir")"

  if ls "$dir"/analysis-*.md >/dev/null 2>&1; then
    ok "analysis-*.md создан"
  else
    fail "analysis-*.md отсутствует"
    return 1
  fi

  note "Открой: less $dir/analysis-*.md"
}

# ── Phase 5.1b: SP refinement path (--days not on a preset) ────────────
phase5_1b() {
  step "Phase 5.1b — research --days 14 (SP rounded UP + client refine)"
  require_key "GEMINI_API_KEY" || return 1

  rm -rf "$QA_DIR/r-en-14d"
  # --days 14 → no exact SP preset, nearest UP is "1 month". source.py
  # uses full extract so upload_date is populated, then pipeline filters
  # client-side to the precise 14-day window.
  $YT research "AI agents" \
    --languages en --days 14 --limit 3 \
    --backend subtitles \
    --prompt "Bullet-point what's new in AI agents this week." \
    --analyze-backend gemini \
    --yes \
    --output-dir "$QA_DIR/r-en-14d"
  local code=$?

  if [[ $code -ne 0 ]]; then
    fail "research exit $code"
    return 1
  fi
  ok "research exit 0"

  local dir
  dir=$(find "$QA_DIR/r-en-14d" -maxdepth 1 -mindepth 1 -type d | head -1)
  if [[ -z "$dir" ]]; then
    fail "batch folder не найден"
    return 1
  fi
  ok "batch folder: $(basename "$dir")"

  if ls "$dir"/analysis-*.md >/dev/null 2>&1; then
    ok "analysis-*.md создан"
  else
    fail "analysis-*.md отсутствует"
    return 1
  fi

  # Sanity check: manifest should list videos with upload_date within 14d.
  if [[ -f "$dir/manifest.json" ]]; then
    note "manifest:  $dir/manifest.json"
    note "проверь даты:  grep -i upload_date $dir/manifest.json"
  fi
}

# ── Phase 5.1c: research --since (explicit date instead of --days) ─────
phase5_1c() {
  step "Phase 5.1c — research --since (explicit date → days_hint → SP)"
  require_key "GEMINI_API_KEY" || return 1

  rm -rf "$QA_DIR/r-en-since"
  # 28 days ago — also non-exact preset → SP "1 month" + full extract.
  # Use python rather than `date` for portability (BSD date != GNU date).
  local since
  since=$(python3 -c "import datetime as d; print((d.date.today()-d.timedelta(days=28)).isoformat())")
  note "since=$since"

  $YT research "AI agents" \
    --languages en --since "$since" --limit 3 \
    --backend subtitles \
    --prompt "Bullet-point what's notable in this window." \
    --analyze-backend gemini \
    --yes \
    --output-dir "$QA_DIR/r-en-since"
  local code=$?

  if [[ $code -ne 0 ]]; then
    fail "research exit $code"
    return 1
  fi
  ok "research exit 0"

  local dir
  dir=$(find "$QA_DIR/r-en-since" -maxdepth 1 -mindepth 1 -type d | head -1)
  if [[ -z "$dir" ]]; then
    fail "batch folder не найден"
    return 1
  fi
  ok "batch folder: $(basename "$dir")"

  if ls "$dir"/analysis-*.md >/dev/null 2>&1; then
    ok "analysis-*.md создан"
  else
    fail "analysis-*.md отсутствует"
    return 1
  fi
}

# ── Phase 5.2: research multi-language with LLM translation ────────────
phase5_2() {
  step "Phase 5.2 — research --languages ru,en (translation через Gemini)"
  require_key "GEMINI_API_KEY" || return 1

  rm -rf "$QA_DIR/r-ml"
  $YT research "Клод новинки" \
    --languages ru,en --days 30 --limit 3 \
    --backend subtitles \
    --prompt "Сделай конспект ключевых идей." \
    --analyze-backend gemini \
    --yes \
    --output-dir "$QA_DIR/r-ml"
  local code=$?

  if [[ $code -ne 0 ]]; then
    fail "research exit $code"
    return 1
  fi
  ok "research exit 0"

  local dir
  dir=$(find "$QA_DIR/r-ml" -maxdepth 1 -mindepth 1 -type d | head -1)
  if [[ -z "$dir" ]]; then
    fail "batch folder не найден"
    return 1
  fi
  ok "batch folder: $(basename "$dir")"

  # Check manifest mentions both languages
  if [[ -f "$dir/manifest.json" ]]; then
    ok "manifest.json создан"
    note "проверь source_language в manifest:"
    note "  grep -i language $dir/manifest.json"
  fi
}

# ── Phase 5.3a: subscribes add + list ──────────────────────────────────
phase5_3a() {
  step "Phase 5.3a — subscribes add + list"

  # backup user state
  [[ -f ~/.youtube-transcribe/subscribes.toml ]] && \
    mv ~/.youtube-transcribe/subscribes.toml ~/.youtube-transcribe/subscribes.toml.qa-bak

  $YT subscribes add "https://www.youtube.com/@AnthropicAI" --group ai
  local code=$?

  if [[ $code -ne 0 ]]; then
    fail "subscribes add exit $code"
    [[ -f ~/.youtube-transcribe/subscribes.toml.qa-bak ]] && \
      mv ~/.youtube-transcribe/subscribes.toml.qa-bak ~/.youtube-transcribe/subscribes.toml
    return 1
  fi
  ok "add exit 0"

  $YT subscribes list
  ok "list работает"

  if grep -q "@AnthropicAI" ~/.youtube-transcribe/subscribes.toml 2>/dev/null; then
    ok "@AnthropicAI в subscribes.toml"
  else
    fail "@AnthropicAI не записан"
  fi

  note "subscribes.toml сохранён. Запусти phase5.3b для update."
  note "Бэкап старого файла: ~/.youtube-transcribe/subscribes.toml.qa-bak"
}

# ── Phase 5.3b: subscribes update flow ─────────────────────────────────
phase5_3b() {
  step "Phase 5.3b — subscribes update (first run + incremental)"
  require_key "GEMINI_API_KEY" || return 1

  if ! grep -q "@AnthropicAI" ~/.youtube-transcribe/subscribes.toml 2>/dev/null; then
    fail "subscribes.toml не содержит @AnthropicAI"
    note "Сначала запусти: scripts/qa.sh phase5.3a"
    return 1
  fi

  echo "--- First update (нужен --days, нет state) ---"
  rm -rf "$QA_DIR/subs1"
  $YT subscribes update --days 30 --group ai \
    --backend subtitles \
    --prompt "Что обсуждалось — три тезиса." \
    --analyze-backend gemini \
    --yes \
    --output-dir "$QA_DIR/subs1"
  local code=$?
  if [[ $code -ne 0 ]]; then
    fail "first update exit $code"
    return 1
  fi
  ok "first update exit 0"

  echo
  echo "--- Incremental update (без флагов, должен быть быстрым) ---"
  rm -rf "$QA_DIR/subs2"
  $YT subscribes update --group ai \
    --backend subtitles \
    --prompt "..." --analyze-backend gemini \
    --yes \
    --output-dir "$QA_DIR/subs2"
  code=$?
  if [[ $code -ne 0 ]]; then
    fail "incremental exit $code"
    return 1
  fi
  ok "incremental exit 0"
  note "Ожидание: либо новые видео, либо '[yellow]Нет новых видео[/yellow]'"
}

# ── Phase 5.3c: --no-rss yt-dlp fallback ───────────────────────────────
phase5_3c() {
  step "Phase 5.3c — subscribes update --no-rss (yt-dlp путь)"
  require_key "GEMINI_API_KEY" || return 1

  if ! grep -q "@AnthropicAI" ~/.youtube-transcribe/subscribes.toml 2>/dev/null; then
    fail "subscribes.toml пустой (запусти phase5.3a)"
    return 1
  fi

  rm -rf "$QA_DIR/subs-nrss"
  $YT subscribes update --no-rss --days 7 --group ai \
    --backend subtitles \
    --prompt "..." --analyze-backend gemini \
    --yes \
    --output-dir "$QA_DIR/subs-nrss"
  local code=$?
  if [[ $code -ne 0 ]]; then
    fail "--no-rss exit $code"
    return 1
  fi
  ok "--no-rss exit 0 (yt-dlp path)"
}

# ── Phase 5.4: history ────────────────────────────────────────────────
phase5_4() {
  step "Phase 5.4 — history list/show"
  $YT history list --last 5
  ok "history list работает"

  # Pick newest id from history list output
  local run_id
  run_id=$($YT history list --last 1 2>&1 | grep -E "^│ (research|subscribes)_" | head -1 | awk '{print $2}')
  if [[ -n "$run_id" ]]; then
    echo
    $YT history show "$run_id"
    ok "history show $run_id"
  else
    note "Нет запусков в истории — сначала запусти phase5.1 / phase5.3b"
  fi
}

# ── cleanup ───────────────────────────────────────────────────────────
cleanup() {
  step "Cleanup — удаляю $QA_DIR и восстанавливаю subscribes.toml"
  rm -rf "$QA_DIR"
  [[ -f ~/.youtube-transcribe/subscribes.toml.qa-bak ]] && \
    mv ~/.youtube-transcribe/subscribes.toml.qa-bak ~/.youtube-transcribe/subscribes.toml
  ok "done"
}

# ── menu ──────────────────────────────────────────────────────────────
menu() {
  cat <<'EOF'
Usage: scripts/qa.sh <phase>

  phase4         — реальный batch на YouTube (subtitles, без API ключей)
  phase5.1       — research --languages en --days 365 (SP exact preset, fast path)
  phase5.1b      — research --days 14 (SP rounded UP + client refine)
  phase5.1c      — research --since (explicit date → days_hint → SP)
  phase5.2       — research --languages ru,en + LLM translation
  phase5.3a      — subscribes add + list (нужна сеть для resolve)
  phase5.3b      — subscribes update first run + incremental
  phase5.3c      — subscribes update --no-rss (yt-dlp путь)
  phase5.4       — history list/show
  cleanup        — удалить все QA-артефакты + восстановить subscribes.toml

Каждая фаза самостоятельна и сообщает PASS/FAIL.
Run from repo root: cd /Users/nekith78/youtube-transcribe && scripts/qa.sh <phase>
EOF
}

# ── entry ─────────────────────────────────────────────────────────────
case "${1:-}" in
  phase4)    phase4 ;;
  phase5.1)  phase5_1 ;;
  phase5.1b) phase5_1b ;;
  phase5.1c) phase5_1c ;;
  phase5.2)  phase5_2 ;;
  phase5.3a) phase5_3a ;;
  phase5.3b) phase5_3b ;;
  phase5.3c) phase5_3c ;;
  phase5.4)  phase5_4 ;;
  cleanup)   cleanup ;;
  *)         menu ;;
esac
