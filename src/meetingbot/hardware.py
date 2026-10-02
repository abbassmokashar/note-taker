"""Hardware tier detection and model selection for faster-whisper.

Tiers (from the plan):
  A: NVIDIA GPU >= 8 GB VRAM   -> large-v3, float16
  B: NVIDIA GPU 4-8 GB         -> large-v3-turbo/medium, int8_float16
  C: CPU >= 8 cores, >= 16 GB  -> large-v3-turbo/medium, int8
  D: weak CPU                  -> small, int8
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

TIER_A = "A"
TIER_B = "B"
TIER_C = "C"
TIER_D = "D"


@dataclass(frozen=True)
class ResolvedTranscription:
    model: str
    device: str
    compute_type: str
    tier: str


_TIER_DEFAULTS: dict[str, tuple[str, str, str]] = {
    TIER_A: ("large-v3", "cuda", "float16"),
    TIER_B: ("large-v3-turbo", "cuda", "int8_float16"),
    TIER_C: ("large-v3-turbo", "cpu", "int8"),
    TIER_D: ("small", "cpu", "int8"),
}


def _gpu_vram_gb() -> float | None:
    """Best-effort VRAM detection via nvidia-smi. Returns None if unavailable."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip().splitlines()
    except (subprocess.SubprocessError, OSError):
        return None
    if not out:
        return None
    try:
        return float(out[0].strip()) / 1024.0  # MiB -> GiB
    except ValueError:
        return None


def _cpu_cores() -> int:
    return os.cpu_count() or 1


def _total_ram_gb() -> float | None:
    try:  # pragma: no cover - platform dependent
        import psutil  # type: ignore
    except ImportError:
        return None
    try:  # pragma: no cover
        return psutil.virtual_memory().total / (1024**3)
    except Exception:
        return None


def detect_tier() -> str:
    """Detect the hardware tier. Overridable with MEETINGBOT_TIER for testing."""
    override = os.environ.get("MEETINGBOT_TIER", "").strip().upper()
    if override in _TIER_DEFAULTS:
        return override

    vram = _gpu_vram_gb()
    if vram is not None:
        return TIER_A if vram >= 8 else TIER_B

    cores = _cpu_cores()
    ram = _total_ram_gb()
    if cores >= 8 and (ram is None or ram >= 16):
        return TIER_C
    if cores >= 4:
        return TIER_C
    return TIER_D


def resolve_transcription(
    *,
    model: str = "auto",
    device: str = "auto",
    compute_type: str = "auto",
    tier: str | None = None,
) -> ResolvedTranscription:
    """Resolve configured (possibly ``auto``) values into concrete ones."""
    resolved_tier = tier or detect_tier()
    default_model, default_device, default_compute = _TIER_DEFAULTS[resolved_tier]

    resolved_model = default_model if model in ("", "auto", None) else model
    resolved_device = default_device if device in ("", "auto", None) else device
    if compute_type in ("", "auto", None):
        resolved_compute = "float16" if resolved_device == "cuda" else "int8"
    else:
        resolved_compute = compute_type

    return ResolvedTranscription(
        model=resolved_model,
        device=resolved_device,
        compute_type=resolved_compute,
        tier=resolved_tier,
    )
