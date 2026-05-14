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
