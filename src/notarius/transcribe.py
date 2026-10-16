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

    segments = split_at_speaker_changes(result["segments"])
    report("done", f"{len(segments)} segments, "
                   f"{len({s.speaker_label for s in segments})} speakers")
    return segments


# Word-level speakers are noisy at the edges of turns on real calls, so a
# split is only made where it looks like a real change of speaker.  Rule
# chosen on four hand-corrected meetings (about six hours): Whisper
# segments rarely cross a change of speaker (4 times), and a looser rule
# made 186 splits, mostly an edge word or half a sentence moved to the
# neighbour.  This rule made 8, of which 4 were clearly right, 1 partly and
# 3 not settled by the transcripts, and it still splits the case that
# prompted it (one segment across two people's turns).
MIN_RUN_WORDS = 3      # a run shorter than this, or than MIN_RUN_SECONDS,
MIN_RUN_SECONDS = 1.0  # folds into its larger neighbour
MIN_PAUSE = 0.5        # without sentence-final punctuation, a change of
SENTENCE_END = (".", "?", "!", "…")  # speaker needs a pause this long


def _seconds(words: list[dict]) -> float:
    starts = [w["start"] for w in words if "start" in w]
    ends = [w["end"] for w in words if "end" in w]
    return (max(ends) - min(starts)) if starts and ends else 0.0


def _coalesce(runs: list[list]) -> list[list]:
    out: list[list] = []
    for run in runs:
        if out and out[-1][0] == run[0]:
            out[-1][1].extend(run[1])
        else:
            out.append(run)
    return out


def _plausible_change(before: list[dict], after: list[dict]) -> bool:
    if before[-1]["word"].strip().endswith(SENTENCE_END):
        return True
    end = next((w["end"] for w in reversed(before) if "end" in w), None)
    start = next((w["start"] for w in after if "start" in w), None)
    return end is not None and start is not None and start - end >= MIN_PAUSE


def split_at_speaker_changes(raw_segments: list[dict]) -> list[TranscriptionSegment]:
    """Turn WhisperX segments into one segment per speaker run.

    Whisper sometimes makes one segment across a change of speaker, and the
    segment's speaker is whoever spoke most of it.  Every word carries its
    own speaker, so a segment is split where the speaker changes — but only
    where that change is believable: both sides long enough, and a sentence
    end or a pause between them.  Otherwise the pieces merge back and the
    longer one's speaker wins, which is the old whole-segment behaviour.
    """
    out: list[TranscriptionSegment] = []
    for seg in raw_segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        default = seg.get("speaker", "UNKNOWN")
        words = [w for w in seg.get("words") or [] if w.get("word", "").strip()]
        if not words:
            out.append(TranscriptionSegment(float(seg["start"]), float(seg["end"]), text, default))
            continue

        runs: list[list] = []  # [speaker, words]
        last = None
        for w in words:
            speaker = w.get("speaker") or last or default
            last = speaker
            if runs and runs[-1][0] == speaker:
                runs[-1][1].append(w)
            else:
                runs.append([speaker, [w]])

        changed = True
        while changed and len(runs) > 1:
            changed = False
            i = min(range(len(runs)), key=lambda k: (len(runs[k][1]), _seconds(runs[k][1])))
            ws = runs[i][1]
            if len(ws) < MIN_RUN_WORDS or _seconds(ws) < MIN_RUN_SECONDS:
                neighbours = [j for j in (i - 1, i + 1) if 0 <= j < len(runs)]
                j = max(neighbours, key=lambda k: (len(runs[k][1]), k < i))
                if j < i:
                    runs[j][1].extend(ws)
                else:
                    runs[j][1][:0] = ws
                del runs[i]
                runs = _coalesce(runs)
                changed = True
                continue
            for k in range(len(runs) - 1):
                if not _plausible_change(runs[k][1], runs[k + 1][1]):
                    a, b = runs[k], runs[k + 1]
                    keep = a[0] if _seconds(a[1]) >= _seconds(b[1]) else b[0]
                    runs[k:k + 2] = [[keep, a[1] + b[1]]]
                    runs = _coalesce(runs)
                    changed = True
                    break

        for speaker, ws in runs:
            starts = [w["start"] for w in ws if "start" in w]
            ends = [w["end"] for w in ws if "end" in w]
            out.append(TranscriptionSegment(
                start=float(min(starts)) if starts else float(seg["start"]),
                end=float(max(ends)) if ends else float(seg["end"]),
                text=" ".join(w["word"].strip() for w in ws),
                speaker_label=speaker,
            ))
    return out


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
                    # The label is the track key, so the segment's audio is
                    # found even after the user renames the speaker.
                    out.append(IdentifiedSegment(
                        float(seg["start"]), float(seg["end"]), text, name, 1.0,
                        label=name, origin="track",
                    ))
        del align_model, align_metadata
        _free_memory()

    out.sort(key=lambda s: s.start)
    report("done", f"{len(out)} segments from {len(audio_files)} participants")
    return out
