"""Speech to text, word alignment and diarization (via WhisperX).

Stages run one after another and each frees its model before the next one
loads, so peak memory stays at one model at a time:

1. decode the audio (ffmpeg, 16 kHz mono)
2. transcribe (faster-whisper)
3. align words to the audio (wav2vec2, Portuguese)
4. diarize: who speaks when (pyannote)
5. assign each segment to a diarization label

Progress goes to an optional callback as ``(stage, message)``; *stage* is
one of ``load``, ``transcribe``, ``align``, ``diarize``, ``assign``,
``done`` so a user interface can show its own wording.
"""

from __future__ import annotations

import gc
import logging
import tempfile
from collections.abc import Callable
from importlib import resources
from pathlib import Path

import torch
import whisperx

from notarius.config import (
    ALIGN_MODEL,
    EMBEDDING_MODEL,
    IdentifiedSegment,
    PipelineConfig,
    TranscriptionSegment,
)
from notarius.torchcompat import trusted_checkpoints

logger = logging.getLogger(__name__)

Progress = Callable[[str, str], None]

# pyannote/speaker-diarization-3.1, with its segmentation model shipped
# inside Notarius (MIT licence) so no Hugging Face account is needed.  The
# embedding model it uses is public and downloads without an account.
_DIARIZATION_CONFIG = """\
version: 3.1.0
pipeline:
  name: pyannote.audio.pipelines.SpeakerDiarization
  params:
    clustering: AgglomerativeClustering
    embedding: {embedding}
    embedding_batch_size: 32
    embedding_exclude_overlap: true
    segmentation: {segmentation}
    segmentation_batch_size: 32
params:
  clustering:
    method: centroid
    min_cluster_size: 12
    threshold: 0.7045654963945799
  segmentation:
    min_duration_off: 0.0
"""


def segmentation_model_path() -> Path:
    """Absolute path of the bundled pyannote segmentation-3.0 checkpoint."""
    return Path(str(resources.files("notarius") / "models" / "segmentation-3.0.bin"))


def write_diarization_config(directory: Path) -> Path:
    """Write the diarization pipeline config with absolute model paths.

    pyannote resolves a relative path in the config against the current
    folder, not the config file, so the path must be absolute.
    """
    seg = segmentation_model_path()
    if not seg.is_file():
        raise FileNotFoundError(f"Bundled segmentation model missing: {seg}")
    path = directory / "diarization.yaml"
    # Forward slashes are valid on Windows and need no YAML escaping.
    path.write_text(
        _DIARIZATION_CONFIG.format(segmentation=seg.as_posix(), embedding=EMBEDDING_MODEL),
        encoding="utf-8",
    )
    return path


def _free_memory() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _whisper(config: PipelineConfig):
    return whisperx.load_model(
        config.whisper_model,
        device=config.device,
        compute_type=config.compute_type,
        language=config.language,
    )


def _align_model(config: PipelineConfig):
    return whisperx.load_align_model(
        language_code=config.language, device=config.device, model_name=ALIGN_MODEL
    )


def transcribe(
    audio_path: str | Path,
    config: PipelineConfig,
    progress: Progress | None = None,
) -> list[TranscriptionSegment]:
    """Transcribe and diarize one recording.  Segments in time order."""

    def report(stage: str, message: str) -> None:
        logger.info(message)
        if progress is not None:
            progress(stage, message)

    with trusted_checkpoints():
        report("load", "Decoding audio...")
        audio = whisperx.load_audio(str(audio_path))

        report("transcribe", "Transcribing...")
        model = _whisper(config)
        result = model.transcribe(audio, batch_size=config.batch_size, language=config.language)
        del model
        _free_memory()

        report("align", "Aligning words...")
        align_model, align_metadata = _align_model(config)
        result = whisperx.align(
            result["segments"], align_model, align_metadata, audio,
            device=config.device, return_char_alignments=False,
        )
        del align_model, align_metadata
        _free_memory()

        report("diarize", "Separating speakers...")
        from whisperx.diarize import DiarizationPipeline

        with tempfile.TemporaryDirectory(prefix="notarius_") as tmp:
            pipeline = DiarizationPipeline(
                model_name=str(write_diarization_config(Path(tmp))),
                use_auth_token=None,
                device=config.device,
            )
        hints = {
            k: v for k, v in (
                ("num_speakers", config.num_speakers),
                ("min_speakers", config.min_speakers),
                ("max_speakers", config.max_speakers),
            ) if v is not None
        }
        diarized = pipeline(audio, **hints)
        del pipeline
        _free_memory()

        report("assign", "Assigning speakers...")
        result = whisperx.assign_word_speakers(diarized, result)

    segments = [
        TranscriptionSegment(
            start=float(seg["start"]),
            end=float(seg["end"]),
            text=seg.get("text", "").strip(),
            speaker_label=seg.get("speaker", "UNKNOWN"),
        )
        for seg in result["segments"]
        if seg.get("text", "").strip()
    ]
    report("done", f"{len(segments)} segments, "
                   f"{len({s.speaker_label for s in segments})} speakers")
    return segments


def transcribe_per_participant(
    audio_files: dict[str, str | Path],
    config: PipelineConfig,
    progress: Progress | None = None,
) -> list[IdentifiedSegment]:
    """Transcribe one-person tracks (Zoom "separate audio per participant").

    No diarization: each file says who is speaking.  Whisper and the
    alignment model are each loaded once for all files.  Returns segments
    from every track in time order (not merged).
    """
    if not audio_files:
        return []

    def report(stage: str, message: str) -> None:
        logger.info(message)
        if progress is not None:
            progress(stage, message)

    with trusted_checkpoints():
        report("transcribe", "Loading speech model...")
        model = _whisper(config)
        raw: dict[str, list[dict]] = {}
        for i, (name, path) in enumerate(audio_files.items(), 1):
            report("transcribe", f"Transcribing {name} ({i}/{len(audio_files)})...")
            audio = whisperx.load_audio(str(path))
            raw[name] = model.transcribe(
                audio, batch_size=config.batch_size, language=config.language
            )["segments"]
            del audio
        del model
        _free_memory()

        report("align", "Aligning words...")
        align_model, align_metadata = _align_model(config)
        out: list[IdentifiedSegment] = []
        for name, segs in raw.items():
            if not segs:
                continue
            audio = whisperx.load_audio(str(audio_files[name]))
            aligned = whisperx.align(
                segs, align_model, align_metadata, audio,
                device=config.device, return_char_alignments=False,
            )
            del audio
            for seg in aligned["segments"]:
                text = seg.get("text", "").strip()
                if text:
                    out.append(IdentifiedSegment(
                        float(seg["start"]), float(seg["end"]), text, name, 1.0,
                        label="", origin="track",
                    ))
        del align_model, align_metadata
        _free_memory()

    out.sort(key=lambda s: s.start)
    report("done", f"{len(out)} segments from {len(audio_files)} participants")
    return out
