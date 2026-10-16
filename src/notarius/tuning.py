"""Settings measured for this machine, and time estimates that improve.

Setup looks at the hardware, picks the device and speech model, and times
a short sample to estimate how long a meeting will take.  Every real
transcription afterwards records its own speed, and estimates use the
median of the recent runs, so they get closer to reality with use.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path

from notarius.config import (
    APP_DIR,
    CPU_BATCH_SIZE,
    CPU_COMPUTE_TYPE,
    WHISPER_MODEL,
)

TUNING_FILE = APP_DIR / "tuning.json"
FAST_WHISPER_MODEL = "dropbox-dash/faster-whisper-large-v3-turbo"
# Below this much RAM the large model is not attempted (see measurements in
# the setup docs); the turbo model needs about half.
MIN_RAM_GB_LARGE = 8.0
# GPUs with less video memory than this run out of memory with the full
# pipeline; the CPU is used instead.
MIN_VRAM_GB = 6.0
HISTORY_KEEP = 10


@dataclass
class Tuning:
    device: str
    compute_type: str
    batch_size: int
    whisper_model: str
    # Processing seconds per minute of audio, by kind of source:
    # "file" (diarization) and "tracks" (Zoom, one file per person).
    seconds_per_audio_minute: float | None = None
    ram_gb: float | None = None
    vram_gb: float | None = None
    cpu_threads: int | None = None
    measured_at: str | None = None
    history: list[dict] = field(default_factory=list)

    def estimate_seconds(self, audio_seconds: float, kind: str = "file") -> float | None:
        """Expected processing time for *audio_seconds* of audio."""
        ratios = [h["ratio"] for h in self.history if h.get("kind") == kind]
        if ratios:
            ratio = statistics.median(ratios[-5:])
        elif self.seconds_per_audio_minute:
            # No real run yet: per-person tracks skip diarization, which
            # is about half of the work.
            ratio = self.seconds_per_audio_minute * (0.5 if kind == "tracks" else 1.0)
        else:
            return None
        return ratio * audio_seconds / 60.0

    def record_run(self, kind: str, audio_seconds: float, elapsed_seconds: float) -> None:
        if audio_seconds < 60:
            return  # too short: model loading would dominate the ratio
        self.history.append({
            "kind": kind,
            "ratio": round(elapsed_seconds / (audio_seconds / 60.0), 2),
            "at": time.strftime("%Y-%m-%d %H:%M"),
        })
        self.history = self.history[-HISTORY_KEEP:]


def load_tuning(path: Path = TUNING_FILE) -> Tuning | None:
    if not path.is_file():
        return None
    try:
        return Tuning(**json.loads(path.read_text(encoding="utf-8")))
    except (TypeError, ValueError):
        return None


def save_tuning(tuning: Tuning, path: Path = TUNING_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(tuning), indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------


def total_ram_gb() -> float | None:
    if sys.platform == "win32":
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return stat.ullTotalPhys / 1024**3
        return None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (ValueError, OSError, AttributeError):
        return None


def gpu_vram_gb() -> float | None:
    import torch

    if not torch.cuda.is_available():
        return None
    return torch.cuda.get_device_properties(0).total_memory / 1024**3


def choose_settings() -> Tuning:
    """Device and model for this machine, before any speed measurement."""
    ram = total_ram_gb()
    vram = gpu_vram_gb()
    if vram is not None and vram >= MIN_VRAM_GB:
        # int8 + batch 8 fits the whole pipeline in 8 GB of video memory
        # even with a browser holding some of it.
        device, compute, batch = "cuda", "int8", 8
    else:
        device, compute, batch = "cpu", CPU_COMPUTE_TYPE, CPU_BATCH_SIZE
    model = WHISPER_MODEL if ram is None or ram >= MIN_RAM_GB_LARGE else FAST_WHISPER_MODEL
    return Tuning(
        device=device, compute_type=compute, batch_size=batch, whisper_model=model,
        ram_gb=None if ram is None else round(ram, 1),
        vram_gb=None if vram is None else round(vram, 1),
        cpu_threads=os.cpu_count(),
    )


# ---------------------------------------------------------------------------
# Speed test
# ---------------------------------------------------------------------------


def sample_path() -> Path:
    """A two-minute public-domain sample shipped with Notarius."""
    return Path(str(resources.files("notarius") / "assets" / "amostra.opus"))


def run_speed_test(progress=None) -> Tuning:
    """Pick settings, time the full pipeline on the sample, save the result.

    The measured time includes loading the models, which a long meeting
    spreads over more audio, so the first estimate errs on the slow side;
    real runs correct it.
    """
    import tempfile

    from notarius.identify import identify_speakers
    from notarius.pipeline import probe_duration
    from notarius.transcribe import transcribe

    tuning = choose_settings()
    previous = load_tuning()
    if previous:
        tuning.history = previous.history
    config_sample = sample_path()
    duration = probe_duration(config_sample) or 120.0

    from notarius.config import PipelineConfig

    with tempfile.TemporaryDirectory() as empty_profiles:
        config = PipelineConfig(
            profiles_dir=Path(empty_profiles),
            whisper_model=tuning.whisper_model,
            compute_type=tuning.compute_type,
            batch_size=tuning.batch_size,
            device=tuning.device,
        )
        start = time.monotonic()
        segments = transcribe(config_sample, config, progress)
        identify_speakers(segments, str(config_sample), config)
        elapsed = time.monotonic() - start

    tuning.seconds_per_audio_minute = round(elapsed / (duration / 60.0), 1)
    tuning.measured_at = time.strftime("%Y-%m-%d %H:%M")
    save_tuning(tuning)
    return tuning
