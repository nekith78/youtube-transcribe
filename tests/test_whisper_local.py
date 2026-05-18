import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch, MagicMock

from skills.neurolearn.backends.whisper_local import WhisperLocalBackend


def _make_fake_faster_whisper_module() -> ModuleType:
    """Return a stub module that satisfies `import faster_whisper`."""
    mod = ModuleType("faster_whisper")
    mod.WhisperModel = MagicMock()  # type: ignore[attr-defined]
    return mod


def test_is_configured_when_faster_whisper_importable():
    fake_fw = _make_fake_faster_whisper_module()
    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
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

    fake_fw = _make_fake_faster_whisper_module()
    with patch.dict(sys.modules, {"faster_whisper": fake_fw}), patch(
        "skills.neurolearn.backends.whisper_local._load_faster_whisper_model",
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


def test_faster_model_load_cached_between_transcribe_calls(tmp_path: Path):
    """v0.10.4: in a batch, multiple videos transcribed by the same backend
    must NOT reload the model from disk each time. Cache keyed on
    (model_name, device, compute_type)."""
    from skills.neurolearn.backends.whisper_local import _load_faster_whisper_model
    # Clear any stale cache state from earlier tests.
    _load_faster_whisper_model.cache_clear()

    fake_segment = MagicMock(start=0.0, end=1.5, text="hi", words=None)
    fake_info = MagicMock(language="en", duration=1.5)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], fake_info)

    a1 = tmp_path / "a1.mp3"; a1.write_bytes(b"x")
    a2 = tmp_path / "a2.mp3"; a2.write_bytes(b"x")

    fake_fw = ModuleType("faster_whisper")
    fake_fw.WhisperModel = MagicMock(return_value=fake_model)  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        b = WhisperLocalBackend(
            model="turbo", device="cuda", compute_type="float16", impl="faster",
        )
        b.transcribe(a1, language="en")
        b.transcribe(a2, language="en")

    # Critical: WhisperModel constructor called ONCE despite two transcribe()
    # invocations with the same (model, device, compute_type) tuple.
    assert fake_fw.WhisperModel.call_count == 1
    # Both videos got transcribed via the cached model.
    assert fake_model.transcribe.call_count == 2

    _load_faster_whisper_model.cache_clear()


def test_faster_model_cache_separate_for_different_params(tmp_path: Path):
    """Different (model, device, compute_type) tuples → separate model loads."""
    from skills.neurolearn.backends.whisper_local import _load_faster_whisper_model
    _load_faster_whisper_model.cache_clear()

    fake_segment = MagicMock(start=0.0, end=1.0, text="x", words=None)
    fake_info = MagicMock(language="en", duration=1.0)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], fake_info)

    a = tmp_path / "a.mp3"; a.write_bytes(b"x")
    fake_fw = ModuleType("faster_whisper")
    fake_fw.WhisperModel = MagicMock(return_value=fake_model)  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        WhisperLocalBackend(model="turbo", device="cuda", compute_type="float16",
                            impl="faster").transcribe(a, language="en")
        WhisperLocalBackend(model="turbo", device="cpu", compute_type="int8",
                            impl="faster").transcribe(a, language="en")

    # Different device → different cache key → two constructor calls.
    assert fake_fw.WhisperModel.call_count == 2
    _load_faster_whisper_model.cache_clear()


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
