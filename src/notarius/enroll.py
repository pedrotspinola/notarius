"""Enroll voices from a reviewed meeting.

Once the speakers of a meeting are named correctly, their own speech is the
best material for voice profiles: same microphones, same call quality as
future meetings.  For each named speaker this module picks clean clips
(long segments that overlap nobody else), embeds them, drops clips that
disagree with the rest, and saves the average as a profile.

Who gets a profile:

* a person with no profile yet: a first profile, if they spoke enough;
* a person who already has profiles: a new variant only when the
  recognition in this meeting was weak (their voice here differs from the
  saved profiles — a different microphone, phone, room).  A person already
  recognized well gains nothing from another profile.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from notarius.config import (
    UNKNOWN_PREFIX,
    VARIANT_SEPARATOR,
    SpeakerProfile,
    profile_base_name,
    validate_base_name,
)
from notarius.embedding import EmbeddingModel, cosine_similarity
from notarius.meeting import Meeting
from notarius.profiles import list_profiles, load_all_profiles

log = logging.getLogger(__name__)

MIN_CLIP = 3.0  # seconds
MAX_CLIP = 12.0  # longer segments are cut to their first MAX_CLIP seconds
MAX_CLIPS = 10
MIN_TOTAL = 45.0  # seconds of clean speech for a trustworthy profile
MIN_CLIPS = 2
OUTLIER_SIM = 0.5  # clips below this cosine to the rest are dropped
# A new profile this close to another person's is reported for review.
CONFLICT_SIM = 0.65
# Below this raw cosine, an existing person's voice in this meeting is
# "not recognized well" and a variant profile is worth adding.
WEAK_RAW = 0.60
MAX_PROFILES_PER_PERSON = 6
_SAMPLE_RATE = 16000


@dataclass
class Clip:
    start: float
    end: float


@dataclass
class PersonPlan:
    person: str
    action: str  # "enroll" | "skip"
    reason: str  # short English reason code text; the UI translates codes
    code: str  # machine-readable reason
    target_profile: str = ""
    audio_path: str = ""
    clips: list[Clip] = field(default_factory=list)
    clean_seconds: float = 0.0
    best_raw: float | None = None  # how well existing profiles matched here

    @property
    def selected_seconds(self) -> float:
        return sum(c.end - c.start for c in self.clips)


@dataclass
class EnrollOutcome:
    plan: PersonPlan
    profile_path: Path | None
    reason: str = ""
    clips_used: int = 0
    clips_dropped: int = 0
    self_similarity: float | None = None
    closest_other: tuple[str, float] | None = None
    conflicts: list[tuple[str, float]] = field(default_factory=list)


def _clean_clips(meeting: Meeting, person: str) -> list[Clip]:
    """Segments of *person* that overlap no other speaker, longest first."""
    own = [s for s in meeting.segments if s.speaker_name == person]
    others = [s for s in meeting.segments if s.speaker_name != person]
    clips: list[Clip] = []
    for s in own:
        if s.end - s.start < MIN_CLIP:
            continue
        if any(o.start < s.end and s.start < o.end for o in others):
            continue
        clips.append(Clip(s.start, min(s.end, s.start + MAX_CLIP)))
    clips.sort(key=lambda c: c.end - c.start, reverse=True)
    return clips


def _best_raw_in_meeting(meeting: Meeting, person: str) -> float | None:
    """Raw score of *person* on the labels assigned to them, if any."""
    scores = [
        c["raw"]
        for lab in meeting.labels
        if lab.get("name") == person
        for c in lab.get("candidates", [])[:1]
        if c.get("person") == person
    ]
    return max(scores) if scores else None


def plan_enrollment(
    meeting: Meeting, profiles_dir: Path, variant_tag: str | None = None
) -> list[PersonPlan]:
    """Decide, for every named speaker, whether to create a profile."""
    existing = list_profiles(profiles_dir)
    tag = variant_tag or (meeting.date or meeting.created[:10]).split("_")[0]
    people = sorted({
        s.speaker_name for s in meeting.segments
        if not s.speaker_name.startswith(UNKNOWN_PREFIX)
    })
    plans: list[PersonPlan] = []
    for person in people:
        clips = _clean_clips(meeting, person)
        clean = sum(c.end - c.start for c in clips)
        audio = meeting.tracks.get(person, meeting.source_path)
        plan = PersonPlan(person, "skip", "", "", audio_path=audio, clean_seconds=clean)
        plans.append(plan)
        try:
            validate_base_name(person)
        except ValueError:
            plan.code, plan.reason = "invalid_name", "name cannot be used as a file name"
            continue

        has_profiles = existing.get(person, [])
        plan.best_raw = _best_raw_in_meeting(meeting, person)
        if has_profiles:
            if len(has_profiles) >= MAX_PROFILES_PER_PERSON:
                plan.code, plan.reason = "too_many", "person already has the maximum number of profiles"
                continue
            if person in meeting.tracks:
                # One-person track: no recognition happened, so there is no
                # score to judge by; enroll only people without profiles.
                plan.code, plan.reason = "already_enrolled", "already has a voice profile"
                continue
            if plan.best_raw is not None and plan.best_raw >= WEAK_RAW:
                plan.code, plan.reason = "recognized_well", "already recognized well"
                continue
            target = f"{person}{VARIANT_SEPARATOR}{tag}"
            if target in has_profiles:
                plan.code, plan.reason = "already_enrolled", "profile from this meeting exists"
                continue
            plan.target_profile = target
            plan.code = "new_variant"
        else:
            plan.target_profile = person
            plan.code = "new_person"

        if len(clips) < MIN_CLIPS or clean < MIN_TOTAL:
            plan.code, plan.reason = "too_little_speech", (
                f"only {clean:.0f}s of clean speech (needs {MIN_TOTAL:.0f}s)"
            )
            plan.target_profile = ""
            continue
        plan.clips = sorted(clips[:MAX_CLIPS], key=lambda c: c.start)
        plan.action = "enroll"
        plan.reason = f"{len(plan.clips)} clips, {plan.selected_seconds:.0f}s"
    return plans


def _drop_outliers(embeddings: list[np.ndarray]) -> tuple[list[np.ndarray], int]:
    """Drop clips whose cosine to the mean of the others is below OUTLIER_SIM.

    Such a clip is probably someone else (crosstalk, a naming mistake).
    Keeps at least two clips.
    """
    kept = list(embeddings)
    dropped = 0
    changed = True
    while changed and len(kept) > 2:
        changed = False
        for i in range(len(kept)):
            others = kept[:i] + kept[i + 1:]
            if cosine_similarity(kept[i], np.mean(others, axis=0)) < OUTLIER_SIM:
                kept.pop(i)
                dropped += 1
                changed = True
                break
    return kept, dropped


def execute(
    plans: list[PersonPlan],
    profiles_dir: Path,
    device: str = "cpu",
    progress: Callable[[str], None] | None = None,
) -> list[EnrollOutcome]:
    """Create the planned profiles.  Each source file is decoded once."""
    todo = [p for p in plans if p.action == "enroll"]
    if not todo:
        return []
    import whisperx

    existing = load_all_profiles(profiles_dir)
    audio_cache: dict[str, np.ndarray] = {}
    outcomes: list[EnrollOutcome] = []
    with EmbeddingModel(device) as model:
        for plan in todo:
            if progress:
                progress(plan.person)
            if plan.audio_path not in audio_cache:
                audio_cache[plan.audio_path] = whisperx.load_audio(plan.audio_path)
            audio = audio_cache[plan.audio_path]
            embeddings = []
            for clip in plan.clips:
                s = int(clip.start * _SAMPLE_RATE)
                e = min(int(clip.end * _SAMPLE_RATE), len(audio))
                if e - s < _SAMPLE_RATE:
                    continue
                emb = model.extract_waveform(audio[s:e], _SAMPLE_RATE)
                if np.isfinite(emb).all():
                    embeddings.append(emb)
            if len(embeddings) < MIN_CLIPS:
                outcomes.append(EnrollOutcome(plan, None, "not enough usable clips"))
                continue
            kept, dropped = _drop_outliers(embeddings)
            if len(kept) < MIN_CLIPS:
                outcomes.append(EnrollOutcome(
                    plan, None, "the clips disagree with each other — check the names",
                    clips_dropped=dropped,
                ))
                continue
            avg = np.mean(kept, axis=0)
            outcome = EnrollOutcome(
                plan, None, clips_used=len(kept), clips_dropped=dropped,
                self_similarity=float(np.mean([cosine_similarity(e, avg) for e in kept])),
            )
            for prof in existing:
                if profile_base_name(prof.name) == plan.person:
                    continue
                sim = cosine_similarity(avg, prof.embedding)
                if outcome.closest_other is None or sim > outcome.closest_other[1]:
                    outcome.closest_other = (prof.name, sim)
                if sim >= CONFLICT_SIM:
                    outcome.conflicts.append((prof.name, sim))
            outcome.profile_path = SpeakerProfile(plan.target_profile, avg).save(profiles_dir)
            outcomes.append(outcome)
    return outcomes
