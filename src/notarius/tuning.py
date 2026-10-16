"""Settings measured for this machine (written by setup, read by every run)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from notarius.config import APP_DIR

TUNING_FILE = APP_DIR / "tuning.json"


@dataclass
class Tuning:
    device: str
    compute_type: str
    batch_size: int
    whisper_model: str
    # Measured processing time per minute of audio, for time estimates.
    seconds_per_audio_minute: float | None = None
    ram_gb: float | None = None
    cpu_threads: int | None = None
    measured_at: str | None = None


def load_tuning(path: Path = TUNING_FILE) -> Tuning | None:
    if not path.is_file():
        return None
    try:
        return Tuning(**json.loads(path.read_text(encoding="utf-8")))
    except (TypeError, ValueError):
        return None


def save_tuning(tuning: Tuning, path: Path = TUNING_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(tuning), indent=2) + "\n", encoding="utf-8")
