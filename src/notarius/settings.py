"""Run settings: the tuned values for this machine, overridable per run."""

from __future__ import annotations

from notarius.config import (
    CPU_BATCH_SIZE,
    CPU_COMPUTE_TYPE,
    GPU_BATCH_SIZE,
    GPU_COMPUTE_TYPE,
    WHISPER_MODEL,
    default_device,
)
from notarius.pipeline import RunSettings
from notarius.tuning import load_tuning


def run_settings(
    device: str | None = None,
    compute_type: str | None = None,
    batch_size: int | None = None,
    whisper_model: str | None = None,
) -> RunSettings:
    """Explicit values win; then the tuned ones; then safe defaults."""
    tuned = load_tuning()
    device = device or (tuned.device if tuned else default_device())
    same_device = tuned is not None and tuned.device == device
    on_cpu = device == "cpu"
    return RunSettings(
        device=device,
        compute_type=compute_type or (
            tuned.compute_type if same_device
            else CPU_COMPUTE_TYPE if on_cpu else GPU_COMPUTE_TYPE
        ),
        batch_size=batch_size if batch_size is not None else (
            tuned.batch_size if same_device
            else CPU_BATCH_SIZE if on_cpu else GPU_BATCH_SIZE
        ),
        whisper_model=whisper_model or (tuned.whisper_model if tuned else WHISPER_MODEL),
    )
