"""First-run setup: download every model once, then measure this machine.

Run by the installer (``notarius setup``) and again from the app's
settings.  Each model is downloaded by loading it, which fetches only the
files actually used and proves they work.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable

from notarius import env

log = logging.getLogger(__name__)

Progress = Callable[[str, str], None]


def download_models(whisper_model: str, progress: Progress | None = None) -> None:
    env.configure(offline=False)

    def report(stage: str, message: str) -> None:
        log.info(message)
        if progress:
            progress(stage, message)

    import tempfile
    from pathlib import Path

    from faster_whisper.utils import download_model

    from notarius.config import ALIGN_MODEL, LANGUAGE
    from notarius.embedding import EmbeddingModel
    from notarius.torchcompat import trusted_checkpoints
    from notarius.transcribe import write_diarization_config

    report("models", f"Downloading speech model ({whisper_model}, ~1.6-3 GB)...")
    download_model(whisper_model)

    with trusted_checkpoints():
        import whisperx

        report("models", "Downloading word alignment model (~1.3 GB)...")
        model, _ = whisperx.load_align_model(LANGUAGE, "cpu", model_name=ALIGN_MODEL)
        del model

        report("models", "Downloading voice model (~27 MB)...")
        with EmbeddingModel("cpu"):
            pass

        report("models", "Checking speaker separation model...")
        from whisperx.diarize import DiarizationPipeline

        with tempfile.TemporaryDirectory() as tmp:
            DiarizationPipeline(model_name=str(write_diarization_config(Path(tmp))),
                                use_auth_token=None, device="cpu")

    env.MODELS_READY.parent.mkdir(parents=True, exist_ok=True)
    env.MODELS_READY.write_text(
        json.dumps({"whisper_model": whisper_model, "at": time.strftime("%Y-%m-%d %H:%M")}),
        encoding="utf-8",
    )
    report("models", "All models ready.")


def run_setup(progress: Progress | None = None, speed_test: bool = True) -> dict:
    from notarius.datafolder import ensure_data_folder
    from notarius.tuning import choose_settings, run_speed_test

    ensure_data_folder()
    choice = choose_settings()
    download_models(choice.whisper_model, progress)
    result = {
        "device": choice.device,
        "whisper_model": choice.whisper_model,
        "ram_gb": choice.ram_gb,
        "vram_gb": choice.vram_gb,
    }
    if speed_test:
        if progress:
            progress("tune", "Measuring this computer's speed...")
        tuning = run_speed_test(progress)
        result["seconds_per_audio_minute"] = tuning.seconds_per_audio_minute
    return result
