"""Smoke test: v0.2 module skeletons exist and import cleanly."""

def test_quality_module_imports():
    import skills.youtube_transcribe.quality  # noqa: F401

def test_detection_module_imports():
    import skills.youtube_transcribe.detection  # noqa: F401

def test_vision_module_imports():
    import skills.youtube_transcribe.vision  # noqa: F401

def test_presets_module_imports():
    import skills.youtube_transcribe.presets  # noqa: F401

def test_version_bumped():
    """v0.2 added these modules. Subsequent releases (0.3.x, ...) still ship
    them — check only that we're past v0.1.x."""
    import skills.youtube_transcribe
    v = skills.youtube_transcribe.__version__
    major_minor = v.split(".")
    assert int(major_minor[0]) >= 0 and int(major_minor[1]) >= 2, \
        f"expected >= 0.2.x, got {v}"
