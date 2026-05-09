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
