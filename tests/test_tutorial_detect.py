"""Tests for tutorial_detect — does the transcript look like a UI tutorial?"""
from dataclasses import dataclass

from skills.neurolearn.detection.tutorial_detect import (
    detect_tutorial, TUTORIAL_DENSITY_THRESHOLD,
)


@dataclass
class _Seg:
    """Minimal stand-in for TranscriptionResult.Segment."""
    start: float
    end: float
    text: str


def test_empty_transcript_not_tutorial():
    """No segments → not a tutorial, no crash."""
    sig = detect_tutorial([])
    assert sig.is_tutorial is False
    assert sig.action_count == 0


def test_dense_english_tutorial_detected():
    """10 action mentions across 5 minutes = 2/min → above threshold."""
    segs = [
        _Seg(0, 30,    "Let me show you how to click on the Settings button."),
        _Seg(30, 60,   "Now we press Save and the dialog closes."),
        _Seg(60, 90,   "Select the file and drag it to the new folder."),
        _Seg(90, 120,  "Type your password and press Enter to continue."),
        _Seg(120, 150, "Open the menu and choose Preferences."),
        _Seg(150, 180, "Copy the link and paste it into the address bar."),
        _Seg(180, 210, "Click the OK button to save your changes."),
        _Seg(210, 240, "Scroll down to find the advanced options."),
        _Seg(240, 270, "Press the keyboard shortcut to switch tabs."),
        _Seg(270, 300, "Select all the entries and choose Delete."),
    ]
    sig = detect_tutorial(segs)
    assert sig.is_tutorial is True
    assert sig.action_count >= 10
    assert sig.density_per_min >= TUTORIAL_DENSITY_THRESHOLD


def test_dense_russian_tutorial_detected():
    """Russian action verbs (через pymorphy3 morphology) — должны срабатывать."""
    segs = [
        _Seg(0, 30,    "Кликаем на кнопку Настройки в правом верхнем углу."),
        _Seg(30, 60,   "Нажимаем сохранить и диалог закрывается."),
        _Seg(60, 90,   "Выбираем файл и перетаскиваем его в новую папку."),
        _Seg(90, 120,  "Вводим пароль и нажимаем Enter."),
        _Seg(120, 150, "Открываем меню и выбираем настройки."),
        _Seg(150, 180, "Копируем ссылку и вставляем в адресную строку."),
    ]
    sig = detect_tutorial(segs)
    assert sig.is_tutorial is True
    assert sig.action_count >= 6


def test_lecture_not_classified_as_tutorial():
    """Long lecture with 1 incidental 'click' over 10 minutes → not a tutorial."""
    segs = [
        _Seg(0, 60,    "Today we'll talk about cognitive psychology."),
        _Seg(60, 120,  "The research shows that attention is a limited resource."),
        _Seg(120, 180, "Studies from the 1990s established baseline patterns."),
        _Seg(180, 240, "If you click any of these links you'll find the papers."),
        _Seg(240, 300, "But the core insight is that prediction beats reaction."),
        _Seg(300, 360, "We'll come back to this in the next section."),
        _Seg(360, 420, "Now consider the implications for design."),
        _Seg(420, 480, "Interface designers should respect this limit."),
        _Seg(480, 540, "A famous example is the StroopTask paradigm."),
        _Seg(540, 600, "In summary, attention is your scarcest resource."),
    ]
    sig = detect_tutorial(segs)
    assert sig.is_tutorial is False
    assert sig.action_count <= 2
    assert sig.density_per_min < TUTORIAL_DENSITY_THRESHOLD


def test_very_short_clip_not_tutorial_even_if_dense():
    """A 20-second reel with 'click' isn't enough to be confident."""
    segs = [
        _Seg(0, 5,  "Click here. Now press save. Open the menu."),
        _Seg(5, 10, "Select all. Press delete. Click OK."),
    ]
    sig = detect_tutorial(segs)
    # Density is sky-high but duration too short to be reliable.
    assert sig.is_tutorial is False
    assert sig.duration_min < 0.5


def test_sample_matches_returned_for_debug():
    segs = [
        _Seg(0, 30, "Click here, then press Save."),
        _Seg(30, 60, "Now we type our password."),
    ]
    sig = detect_tutorial(segs)
    assert len(sig.sample_matches) > 0
    # At least one should be an English action verb (truncated form okay)
    flat = " ".join(s.lower() for s in sig.sample_matches)
    assert "click" in flat or "type" in flat or "press" in flat
