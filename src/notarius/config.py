"""Shared types, paths and settings for Notarius."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import numpy as np

# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------
# Everything Notarius learns and produces lives in one visible folder that
# the user can find and back up: voice profiles, transcripts, notes.  The
# folder names are shown to Portuguese-speaking users, so they are in
# Portuguese.  NOTARIUS_HOME overrides the location (tests, portable use).
DATA_DIR = (
    Path(os.environ["NOTARIUS_HOME"]).expanduser()
    if os.environ.get("NOTARIUS_HOME")
    else Path.home() / "Notarius"
)
PROFILES_DIR = DATA_DIR / "Vozes"
MEETINGS_DIR = DATA_DIR / "Transcrições"
NOTES_DIR = DATA_DIR / "Notas"
LOGS_DIR = DATA_DIR / "Registros"

# Machine-specific state (tuned settings, model downloads) lives with the
# program, not with the user's data: %LOCALAPPDATA%\Notarius on Windows.
APP_DIR = (
    Path(os.environ["NOTARIUS_APP_DIR"]).expanduser()
    if os.environ.get("NOTARIUS_APP_DIR")
    else Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local/share") / "Notarius"
)

FFMPEG_MISSING = (
    "ffmpeg was not found. It is installed together with Notarius; "
    "running the installer again restores it."
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
LANGUAGE = "pt"
WHISPER_MODEL = "large-v3"
ALIGN_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-portuguese"
# Speaker embeddings (256-dim).  Used both inside diarization and for voice
# profiles, so diarization centroids and profiles share one space.
EMBEDDING_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"
EMBEDDING_DIM = 256

# Whisper settings per device.  CTranslate2 has no float16 on CPU (it
# supports float32, int16, int8, int8_float32 there) and refuses to load,
# so the GPU default cannot be reused.  int8 + batch 8 are the settings the
# CPU speed measurements were taken with.
GPU_COMPUTE_TYPE = "float16"
GPU_BATCH_SIZE = 16
CPU_COMPUTE_TYPE = "int8"
CPU_BATCH_SIZE = 8


def default_device() -> str:
    """``"cuda"`` when torch sees a CUDA GPU, else ``"cpu"``."""
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


# ---------------------------------------------------------------------------
# Profile names
# ---------------------------------------------------------------------------
_SAFE_NAME_RE = re.compile(r"^[\w\s\-\.]+$", re.UNICODE)

# Separator between a person's name and a variant tag in profile file names:
# "Odete Prado__zoom" is a second profile of "Odete Prado", recorded under
# different conditions.  Matching takes the best score across variants.
VARIANT_SEPARATOR = "__"

# Name given to speakers that matched nobody.  Shown to users.
UNKNOWN_PREFIX = "Desconhecido"


def profile_base_name(name: str) -> str:
    """``"Odete"`` → ``"Odete"``; ``"Odete__zoom"`` → ``"Odete"``."""
    return name.split(VARIANT_SEPARATOR, 1)[0]


def validate_profile_name(name: str) -> None:
    """Ensure a profile name is safe for use as a file name."""
    if not name or not name.strip():
        raise ValueError("Profile name must not be empty or whitespace-only.")
    if name.startswith("."):
        raise ValueError(f"Invalid profile name {name!r}: must not start with a dot.")
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid profile name {name!r}. Use only letters, digits, "
            "spaces, hyphens, underscores, or dots."
        )
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Invalid profile name {name!r}: path separators not allowed.")


def validate_base_name(name: str) -> None:
    """Validate a person's name (must not contain the variant separator)."""
    validate_profile_name(name)
    if VARIANT_SEPARATOR in name:
        raise ValueError(
            f"Person name {name!r} must not contain '{VARIANT_SEPARATOR}'."
        )


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TranscriptionSegment:
    """Raw segment from transcription + diarization."""

    start: float  # seconds
    end: float  # seconds
    text: str
    speaker_label: str  # diarization label, e.g. "SPEAKER_00"


@dataclass
class SpeakerProfile:
    """An enrolled voice profile."""

    name: str
    embedding: np.ndarray  # shape (EMBEDDING_DIM,)

    def save(self, profiles_dir: Path) -> Path:
        """Save the embedding to disk and return the file path."""
        validate_profile_name(self.name)
        profiles_dir.mkdir(parents=True, exist_ok=True)
        path = profiles_dir / f"{self.name}.npy"
        np.save(path, self.embedding)
        return path

    @classmethod
    def load(cls, path: Path) -> SpeakerProfile:
        return cls(name=path.stem, embedding=np.load(path))


@dataclass
class IdentifiedSegment:
    """A segment with its speaker resolved to a person or an unknown.

    ``label`` is the diarization label the segment came from (empty for
    per-participant recordings).  ``origin`` records how the name was
    decided: ``"label"`` (the label's match), ``"verified"`` (segment
    re-scored and moved to another person), ``"track"`` (per-participant
    recording) or ``"review"`` (set by the user).
    """

    start: float
    end: float
    text: str
    speaker_name: str  # person name or "Desconhecido N"
    confidence: float  # AS-Norm or raw cosine score, -1.0 for unknown
    label: str = ""
    origin: str = "label"


@dataclass
class SegmentVerification:
    """One reportable per-segment verification event.

    ``kind``: ``"reassigned"`` (segment renamed to ``to_name``),
    ``"flagged"`` (matched label, every person below hint), ``"suspect"``
    (another person outscores the owner above accept — report only),
    ``"possible"`` (unknown label, best person between hint and accept —
    report only), ``"gated"`` (would have been renamed to ``to_name``, but
    that person is not known to be present — kept, review by ear).
    """

    index: int  # position in the segment list
    start: float
    end: float
    kind: str
    from_name: str
    to_name: str | None
    own_norm: float | None  # assigned person's score (None for unknown labels)
    best_norm: float
    best_name: str
    text: str  # snippet, <= 60 chars


@dataclass
class LabelVerification:
    """Per-label summary of per-segment verification."""

    n_segments: int = 0
    verified: int = 0
    inherited: int = 0  # too short / failed embedding: keeps the label's name
    reassigned: int = 0
    flagged: int = 0
    suspect: int = 0
    possible: int = 0
    kept: int = 0  # unknown label, best person below hint
    gated: int = 0
    events: list[SegmentVerification] = field(default_factory=list)


class Candidate(NamedTuple):
    """One scored person for a label or segment.

    ``norm`` is the AS-Norm score (equals ``raw`` when AS-Norm is off);
    ``excess`` is ``norm`` minus the accept threshold in use, so a
    candidate is acceptable exactly when ``excess >= 0``.
    """

    name: str
    raw: float
    norm: float
    excess: float


@dataclass
class LabelMatch:
    """Matching diagnostics for one diarization label."""

    label: str
    assigned: str | None
    candidates: list[Candidate]  # top persons, best first
    n_segments: int
    duration: float
    used_asnorm: bool
    display: str | None = None  # final name in the transcript
    verification: LabelVerification | None = None


@dataclass
class MeetingAttendee:
    """A person present at a meeting."""

    name: str
    spoke: bool
    segments: int = 0


@dataclass
class PipelineConfig:
    """Settings for one transcription / identification run."""

    profiles_dir: Path = field(default_factory=lambda: PROFILES_DIR)
    whisper_model: str = WHISPER_MODEL
    language: str = LANGUAGE
    compute_type: str = GPU_COMPUTE_TYPE
    batch_size: int = GPU_BATCH_SIZE
    device: str = "cpu"
    num_speakers: int | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None
    # Raw cosine threshold, used only while fewer than asnorm_min_cohort
    # people are enrolled (AS-Norm needs other people to compare against).
    similarity_threshold: float = 0.55
    # AS-Norm: raw cosine scores shift with recording conditions (a phone
    # voice message vs. a meeting microphone), so a fixed cosine threshold
    # misses enrolled people.  AS-Norm rescales each score against the other
    # enrolled people, which lets one threshold work across conditions.
    # Calibrated on hand-verified meeting recordings: genuine label-level
    # scores >= 4.5 (profiles built from a single clip: ~3.3-3.7),
    # cross-person false accepts <= 1.96, unenrolled voices <= 2.61.
    asnorm_enabled: bool = True
    asnorm_accept: float = 3.0
    asnorm_hint: float = 2.0  # "possible" hint for unknown labels
    asnorm_top_k: int = 12
    asnorm_min_cohort: int = 10
    # A label accepted with a raw cosine below this is not proven: in
    # hand-verified meetings every false accept of an unenrolled voice sat
    # at raw 0.42-0.49 and every correct match at 0.57 or above, while the
    # AS-Norm scores of the two groups overlapped.  Not a gate (raw scores
    # drop for genuine speakers on bad microphones too) — a review flag.
    unproven_raw: float = 0.50
    # Per-segment verification: after label-level matching, every segment
    # long enough is re-scored on its own to catch labels that contain more
    # than one person.  The accept bar is higher than the label's because
    # single clips are noisier (unenrolled voices peaked at 3.21 per clip).
    verify_segments: bool = True
    verify_min_duration: float = 3.0
    verify_accept: float = 3.5
    verify_hint: float = 2.0
