"""Smoke test: v0.7 packages exist and import cleanly."""


def test_shared_imports():
    import skills.neurolearn.shared  # noqa: F401


def test_research_imports():
    import skills.neurolearn.research  # noqa: F401


def test_subscribes_imports():
    import skills.neurolearn.subscribes  # noqa: F401


def test_history_imports():
    import skills.neurolearn.history  # noqa: F401


def test_version_matches_pyproject():
    """v0.9 renamed the project to neurolearn; version pinned at 0.9.x.
    Bumps should land here so the package-level __version__ doesn't drift
    from `pyproject.toml`.
    """
    import skills.neurolearn
    assert skills.neurolearn.__version__.startswith("0.10.")
