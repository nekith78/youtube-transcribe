"""Tests for video_type_detect — multi-class video classifier."""
from dataclasses import dataclass

from skills.neurolearn.detection.video_type_detect import detect_video_type


@dataclass
class _Seg:
    start: float
    end: float
    text: str


def test_empty_segments_returns_generic():
    sig = detect_video_type([])
    assert sig.video_type == "generic"
    assert sig.confidence == 0.0


def test_tutorial_recognized():
    """Dense UI-action vocabulary → tutorial."""
    segs = [_Seg(i * 30, i * 30 + 5, "Click the Save button. Now press Enter.")
            for i in range(10)]
    sig = detect_video_type(segs)
    assert sig.video_type == "tutorial"
    assert sig.confidence >= 0.5


def test_lecture_recognized():
    """Pedagogical phrasing + slide references → lecture."""
    segs = [
        _Seg(0, 60,   "Today we'll discuss attention mechanisms."),
        _Seg(60, 120, "Research shows that transformers outperform RNNs."),
        _Seg(120, 180, "As you can see on the slide, the architecture has three layers."),
        _Seg(180, 240, "The next slide compares benchmark results."),
        _Seg(240, 300, "The hypothesis is that scale alone drives performance."),
        _Seg(300, 360, "Studies show consistent improvement across tasks."),
    ]
    sig = detect_video_type(segs)
    assert sig.video_type == "lecture"


def test_code_recognized():
    """Programming vocabulary → code."""
    segs = [
        _Seg(0, 20,   "Let me define a function that takes a parameter."),
        _Seg(20, 40,  "We import the class and create a new variable."),
        _Seg(40, 60,  "Return value handling needs an exception block."),
        _Seg(60, 80,  "Run the npm install command in your terminal."),
        _Seg(80, 100, "The error message is in the stack trace."),
        _Seg(100, 120, "Use git commit to save the changes."),
    ]
    sig = detect_video_type(segs)
    assert sig.video_type == "code"


def test_interview_recognized():
    """Welcome/guest/tell me about → interview."""
    segs = [
        _Seg(0, 30,   "Welcome to the show, thank you for joining me today."),
        _Seg(30, 60,  "My guest is a researcher in cognitive psychology."),
        _Seg(60, 90,  "So tell me about your latest work."),
        _Seg(90, 120, "In your opinion, what's the next breakthrough?"),
        _Seg(120, 150, "Thank you for being on the podcast."),
    ]
    sig = detect_video_type(segs)
    assert sig.video_type == "interview"


def test_vlog_recognized():
    """First-person daily-life narration → vlog."""
    segs = [
        _Seg(0, 30,   "Today I'm walking around the streets of Tokyo."),
        _Seg(30, 60,  "Yesterday I went to a great coffee shop."),
        _Seg(60, 90,  "This morning I made breakfast at home in my kitchen."),
        _Seg(90, 120, "Welcome back to my channel, subscribe for more."),
        _Seg(120, 150, "Let me show you my apartment."),
    ]
    sig = detect_video_type(segs)
    assert sig.video_type == "vlog"


def test_review_recognized():
    """Unboxing/specs/comparison → review."""
    segs = [
        _Seg(0, 30,    "Today I'm unboxing the new iPhone 15."),
        _Seg(30, 60,   "Let's look at the specs and compare to last year."),
        _Seg(60, 90,   "Is it worth the money? Pros and cons coming up."),
        _Seg(90, 120,  "Side by side comparison versus the competitor."),
        _Seg(120, 150, "In the box you get the cable and adapter."),
    ]
    sig = detect_video_type(segs)
    assert sig.video_type == "review"


def test_talking_head_for_long_low_signal_video():
    """Long video with no positive class signal → talking_head."""
    segs = [
        _Seg(i * 60, (i + 1) * 60,
             "And so I was thinking about life and what it means.")
        for i in range(5)   # 5 minutes
    ]
    sig = detect_video_type(segs)
    assert sig.video_type == "talking_head"


def test_short_clip_with_no_signal_returns_generic():
    """30 seconds of nothing categorical → generic, not talking_head."""
    segs = [_Seg(0, 30, "And so I was thinking.")]
    sig = detect_video_type(segs)
    assert sig.video_type == "generic"


def test_demo_recognized():
    """Product-launch vocabulary → demo."""
    segs = [
        _Seg(0, 30,   "Today we're announcing a new feature."),
        _Seg(30, 60,  "Introducing the public beta release."),
        _Seg(60, 90,  "Sign up for the free trial to try it."),
        _Seg(90, 120, "The new workflow saves time on every task."),
        _Seg(120, 150, "Check the pricing page for subscription details."),
    ]
    sig = detect_video_type(segs)
    assert sig.video_type == "demo"


def test_counts_and_densities_in_signal():
    """Counts/densities populated for debugging."""
    segs = [_Seg(i * 30, i * 30 + 5, "Click the button.") for i in range(10)]
    sig = detect_video_type(segs)
    assert sig.counts_per_type.get("tutorial", 0) >= 10
    assert sig.densities_per_type.get("tutorial", 0) > 1.5
