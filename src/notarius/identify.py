"""Match diarized speakers to enrolled voice profiles.

Three steps, each loading what it needs once:

1. Audio: decode the whole recording once; every clip is a slice of it.
2. Embeddings: one pass of the embedding model over the longest segments
   of each diarization label and over every segment long enough to verify.
3. Decisions (numpy only): score each label against every enrolled person,
   assign it to the best one above the accept threshold, then re-score each
   segment on its own to catch labels that contain more than one person.

Scores use AS-Norm: each raw cosine is rescaled against the scores of the
other enrolled people, so one threshold works across recording conditions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from notarius.config import (
    UNKNOWN_PREFIX,
    Candidate,
    IdentifiedSegment,
    LabelMatch,
    LabelVerification,
    PipelineConfig,
    SegmentVerification,
    SpeakerProfile,
    TranscriptionSegment,
)
from notarius.embedding import EmbeddingModel, cosine_similarity
from notarius.meeting import format_timestamp
from notarius.profiles import group_profiles_by_person, load_all_profiles

log = logging.getLogger(__name__)

_MAX_CHUNKS = 5  # longest segments per label used for the label embedding
_SAMPLE_RATE = 16000  # whisperx.load_audio output rate
_SNIPPET_LEN = 60  # max characters of segment text kept in events


def _longest_segments(
    segments: list[TranscriptionSegment], label: str
) -> list[TranscriptionSegment]:
    """The longest segments of *label*: its voice sample for matching."""
    own = [s for s in segments if s.speaker_label == label and s.end > s.start]
    return sorted(own, key=lambda s: s.end - s.start, reverse=True)[:_MAX_CHUNKS]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class MatchSpace:
    """The enrolled people and the thresholds in force for one run.

    ``use_asnorm`` is False while fewer than ``asnorm_min_cohort`` people
    are enrolled: AS-Norm needs other people to compare against, so raw
    cosine with ``similarity_threshold`` is used instead.
    """

    persons: dict[str, list[SpeakerProfile]]
    enroll_cohorts: dict[str, np.ndarray]
    use_asnorm: bool
    top_k: int
    accept: float  # label-level accept threshold
    hint: float  # label-level "possible" threshold
    verify_accept: float  # per-segment thresholds
    verify_hint: float
    label_embeddings: dict[str, np.ndarray] = field(default_factory=dict)
    segment_embeddings: dict[int, np.ndarray] = field(default_factory=dict)


def build_space(
    profiles: list[SpeakerProfile], config: PipelineConfig
) -> MatchSpace | None:
    persons = group_profiles_by_person(profiles)
    if not persons:
        return None
    use = config.asnorm_enabled and len(persons) >= config.asnorm_min_cohort
    accept = config.asnorm_accept if use else config.similarity_threshold
    space = MatchSpace(
        persons=persons,
        enroll_cohorts=_asnorm_cohorts(persons) if use else {},
        use_asnorm=use,
        top_k=config.asnorm_top_k,
        accept=accept,
        # The raw-cosine fallback has no calibrated hint band.
        hint=config.asnorm_hint if use else accept,
        verify_accept=config.verify_accept,
        verify_hint=config.verify_hint,
    )
    log.info(
        "Matching against %d people, %s, accept >= %g",
        len(persons), "AS-Norm" if use else "raw cosine", accept,
    )
    return space


def _asnorm_cohorts(persons: dict[str, list[SpeakerProfile]]) -> dict[str, np.ndarray]:
    """Enrollment-side cohort scores per person.

    For each person, one score per profile of every OTHER person: the best
    similarity between that profile and any of the person's own variants
    (the same max-over-variants rule as matching).
    """
    cohorts: dict[str, np.ndarray] = {}
    for name, own in persons.items():
        cohorts[name] = np.array([
            max(cosine_similarity(v.embedding, w.embedding) for v in own)
            for other, others in persons.items()
            if other != name
            for w in others
        ])
    return cohorts


def _asnorm(raw: float, enroll_cohort: np.ndarray, test_cohort: np.ndarray, top_k: int) -> float:
    """Adaptive symmetric score normalization.

    Z-normalizes *raw* against the top-K closest impostor scores on the
    enrollment side (profile vs. other profiles) and the test side (test
    embedding vs. other profiles), and averages the two.
    """
    ce = np.sort(enroll_cohort)[::-1][:top_k]
    ct = np.sort(test_cohort)[::-1][:top_k]
    return 0.5 * (
        (raw - ce.mean()) / (ce.std() + 1e-6)
        + (raw - ct.mean()) / (ct.std() + 1e-6)
    )


def score_embedding(emb: np.ndarray, space: MatchSpace, accept: float) -> list[Candidate]:
    """Score *emb* against every enrolled person, best first.

    Raw score per person = best cosine across the person's variants.
    """
    raw_scores = {
        name: max(cosine_similarity(emb, p.embedding) for p in profiles)
        for name, profiles in space.persons.items()
    }
    scored: list[Candidate] = []
    for name, raw in raw_scores.items():
        if space.use_asnorm:
            test_cohort = np.array([v for other, v in raw_scores.items() if other != name])
            norm = _asnorm(raw, space.enroll_cohorts[name], test_cohort, space.top_k)
        else:
            norm = raw
        scored.append(Candidate(name, raw, norm, norm - accept))
    scored.sort(key=lambda c: c.norm, reverse=True)
    return scored


def _score_labels(space: MatchSpace, segments: list[TranscriptionSegment]) -> list[LabelMatch]:
    """Decide every label independently.

    A person may be assigned to several labels: diarization often splits
    one voice across labels, and forcing one label per person would turn
    the extra labels into unknowns.
    """
    stats: dict[str, tuple[int, float]] = {}
    for s in segments:
        n, dur = stats.get(s.speaker_label, (0, 0.0))
        stats[s.speaker_label] = (n + 1, dur + max(0.0, s.end - s.start))

    matches: list[LabelMatch] = []
    for label in sorted(space.label_embeddings):
        scored = score_embedding(space.label_embeddings[label], space, space.accept)
        best = scored[0]
        n_segments, duration = stats.get(label, (0, 0.0))
        matches.append(
            LabelMatch(
                label=label,
                assigned=best.name if best.excess >= 0 else None,
                candidates=scored[:3],
                n_segments=n_segments,
                duration=duration,
                used_asnorm=space.use_asnorm,
            )
        )
    return matches


# ---------------------------------------------------------------------------
# Per-segment verification
# ---------------------------------------------------------------------------


def verify_decision(
    assigned: str | None,
    scored: list[Candidate],
    hint: float,
    allowed: set[str] | None = None,
) -> tuple[str, str | None, float | None, str, float]:
    """Per-segment decision rule (pure function).

    *scored* holds every person scored against the segment, best first,
    with ``excess`` measured against the per-segment accept threshold.
    *allowed* is the attendee gate: when given, a rename to anyone outside
    it is demoted to ``"gated"`` (reported, not applied).

    Returns ``(kind, new_name, own_norm, best_name, best_norm)``: *kind* is
    one of verified / reassigned / flagged / suspect / possible / kept /
    gated; *new_name* is set only for ``reassigned``; *best_name* and
    *best_norm* describe the best OTHER person for a matched label and the
    best person overall for an unknown label.  A segment is never moved to
    someone scoring below the accept threshold.
    """
    if allowed is not None:
        allowed = {name.lower() for name in allowed}
    if assigned is not None:
        own = next((c for c in scored if c.name == assigned), None)
        own_norm = own.norm if own is not None else float("-inf")
        own_excess = own.excess if own is not None else float("-inf")
        own_below_hint = own is None or own.norm < hint
        others = [c for c in scored if c.name != assigned]
        best = others[0] if others else None
        best_name = best.name if best is not None else ""
        best_norm = best.norm if best is not None else float("-inf")
        if own_below_hint and best is not None and best.excess >= 0:
            if allowed is not None and best_name.lower() not in allowed:
                return "gated", None, own_norm, best_name, best_norm
            return "reassigned", best_name, own_norm, best_name, best_norm
        if own_below_hint:
            return "flagged", None, own_norm, best_name, best_norm
        if best is not None and best.excess >= 0 and best.excess > own_excess:
            return "suspect", None, own_norm, best_name, best_norm
        return "verified", None, own_norm, best_name, best_norm

    best = scored[0]
    if best.excess >= 0:
        if allowed is not None and best.name.lower() not in allowed:
            return "gated", None, None, best.name, best.norm
        return "reassigned", best.name, None, best.name, best.norm
    if best.norm >= hint:
        return "possible", None, None, best.name, best.norm
    return "kept", None, None, best.name, best.norm


def _verify_segments(
    segments: list[TranscriptionSegment],
    matches: list[LabelMatch],
    label_to_name: dict[str, tuple[str, float]],
    space: MatchSpace,
    allowed: set[str] | None,
) -> dict[int, tuple[str, float]]:
    """Re-score each eligible segment on its own.

    Renames only clear cases: in a matched label, the owner scores below
    the hint while another person clears the accept threshold; in an
    unknown label, someone clears the accept threshold ("rescued").

    Returns ``{segment_index: (new_name, score)}`` for renamed segments and
    attaches a :class:`LabelVerification` to every match.
    """
    by_label: dict[str, list[int]] = {}
    for i, s in enumerate(segments):
        by_label.setdefault(s.speaker_label, []).append(i)

    overrides: dict[int, tuple[str, float]] = {}
    for m in matches:
        indices = by_label.get(m.label, [])
        ver = LabelVerification(n_segments=len(indices))
        from_name = label_to_name[m.label][0]
        for i in indices:
            emb = space.segment_embeddings.get(i)
            if emb is None:
                ver.inherited += 1
                continue
            scored = score_embedding(emb, space, space.verify_accept)
            scored.sort(key=lambda c: c.excess, reverse=True)
            kind, new_name, own_norm, best_name, best_norm = verify_decision(
                m.assigned, scored, space.verify_hint, allowed
            )
            if kind in ("verified", "suspect"):
                ver.verified += 1
            if kind == "suspect":
                ver.suspect += 1
            elif kind == "kept":
                ver.kept += 1
            elif kind == "flagged":
                ver.flagged += 1
            elif kind == "possible":
                ver.possible += 1
            elif kind == "gated":
                ver.gated += 1
            elif kind == "reassigned":
                ver.reassigned += 1
                overrides[i] = (new_name, best_norm)

            if kind in ("reassigned", "flagged", "suspect", "possible", "gated"):
                s = segments[i]
                text = s.text.strip()
                if len(text) > _SNIPPET_LEN:
                    text = text[: _SNIPPET_LEN - 1] + "…"
                ver.events.append(
                    SegmentVerification(
                        index=i,
                        start=s.start,
                        end=s.end,
                        kind=kind,
                        from_name=from_name,
                        # For gated events the rename did NOT happen; to_name
                        # records the blocked target for review.
                        to_name=best_name if kind == "gated" else new_name,
                        own_norm=own_norm if m.assigned is not None else None,
                        best_norm=best_norm,
                        best_name=best_name,
                        text=text,
                    )
                )
        m.verification = ver
    return overrides


# ---------------------------------------------------------------------------
# Reports (log only; the UI reads the structured data)
# ---------------------------------------------------------------------------


def format_match_report(matches: list[LabelMatch], config: PipelineConfig) -> str:
    if not matches:
        return "Speaker matching: no labels to match."
    mode = "AS-Norm" if matches[0].used_asnorm else "raw cosine"
    accept = matches[0].candidates[0].norm - matches[0].candidates[0].excess
    lines = [f"Speaker matching ({mode}, accept >= {accept:g}):"]
    for m in matches:
        mins, secs = divmod(int(m.duration), 60)
        stats = f"{m.n_segments} segs, {mins}m{secs:02d}s"
        cands = ", ".join(f"{c.name} norm {c.norm:.2f} raw {c.raw:.2f}" for c in m.candidates)
        display = m.display or m.assigned or "?"
        notes = []
        if m.assigned is not None:
            if m.candidates[0].raw < config.unproven_raw:
                notes.append(f"UNPROVEN raw {m.candidates[0].raw:.2f}")
            if len(m.candidates) > 1:
                gap = m.candidates[0].excess - m.candidates[1].excess
                if gap < 1.0:
                    notes.append(f"LOW MARGIN vs {m.candidates[1].name} ({gap:.2f})")
        elif m.used_asnorm and m.candidates and m.candidates[0].norm >= config.asnorm_hint:
            notes.append(f"POSSIBLE: {m.candidates[0].name}")
        suffix = f"  <- {'; '.join(notes)}" if notes else ""
        lines.append(f"  {m.label} -> {display}  ({stats})  [{cands}]{suffix}")
    return "\n".join(lines)


def format_verification_report(matches: list[LabelMatch]) -> str:
    lines = ["Per-segment verification:"]
    for m in matches:
        v = m.verification
        if v is None:
            continue
        counts = (
            f"{v.verified} verified, {v.reassigned} renamed, {v.flagged} flagged, "
            f"{v.suspect} suspect, {v.possible} possible, {v.gated} gated, "
            f"{v.inherited} too short"
        )
        lines.append(f"  {m.label} -> {m.display}: {counts}")
        for e in v.events:
            if e.kind in ("reassigned", "gated"):
                lines.append(
                    f"    {format_timestamp(e.start)} {e.kind} -> {e.to_name} "
                    f"({e.best_norm:.2f}): \"{e.text}\""
                )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def unknown_names(labels: list[str]) -> dict[str, str]:
    """Map labels to "Desconhecido 1", "Desconhecido 2", ... in label order."""
    return {label: f"{UNKNOWN_PREFIX} {i + 1}" for i, label in enumerate(sorted(labels))}


def identify_speakers(
    segments: list[TranscriptionSegment],
    audio_path: str,
    config: PipelineConfig,
    attendees: list[str] | None = None,
) -> tuple[list[IdentifiedSegment], list[LabelMatch]]:
    """Resolve each segment's speaker to an enrolled person or an unknown.

    *attendees* (already resolved to profile names) activates the attendee
    gate for per-segment renames: they may only target listed people or
    people already assigned a whole label.  Label-level matching is never
    gated — that is how late joiners and forgotten attendees are detected.

    Returns one :class:`IdentifiedSegment` per input segment, in order (not
    merged), plus per-label diagnostics.
    """
    if not segments:
        return [], []

    unique_labels = sorted({s.speaker_label for s in segments})
    space = build_space(load_all_profiles(config.profiles_dir), config)

    if space is None:
        # Nobody enrolled yet (a new user's first meetings): every speaker
        # is unknown, but each label is still reported, so review can ask
        # who they are.
        log.info("No voice profiles enrolled; every speaker is unknown")
        names = unknown_names(unique_labels)
        stats: dict[str, list[float]] = {}
        for s in segments:
            n, dur = stats.setdefault(s.speaker_label, [0, 0.0])
            stats[s.speaker_label] = [n + 1, dur + max(0.0, s.end - s.start)]
        matches = [
            LabelMatch(label, None, [], int(stats[label][0]), stats[label][1],
                       used_asnorm=False, display=names[label])
            for label in unique_labels
        ]
        return [
            IdentifiedSegment(s.start, s.end, s.text, names[s.speaker_label], -1.0,
                              label=s.speaker_label)
            for s in segments
        ], matches

    verify_on = config.verify_segments and space.use_asnorm
    sr = _SAMPLE_RATE
    import whisperx

    # One decode of the whole recording; every clip is a slice of it.
    wave = whisperx.load_audio(audio_path)

    def clip(s: TranscriptionSegment) -> np.ndarray:
        return wave[max(0, int(s.start * sr)):min(len(wave), int(s.end * sr))]

    eligible: list[int] = []
    if verify_on:
        min_samples = int(config.verify_min_duration * sr)
        eligible = [
            i for i, s in enumerate(segments)
            if s.end - s.start >= config.verify_min_duration and len(clip(s)) >= min_samples
        ]

    with EmbeddingModel(config.device) as emb_model:
        for label in unique_labels:
            chunks = [c for c in map(clip, _longest_segments(segments, label)) if len(c)]
            if not chunks:
                log.warning("No usable segments for label %s; it stays unknown", label)
                continue
            try:
                space.label_embeddings[label] = np.mean(
                    [emb_model.extract_waveform(c, sr) for c in chunks], axis=0
                )
            except Exception:
                log.warning("Embedding failed for %s; it stays unknown", label, exc_info=True)
        for i in eligible:
            s = segments[i]
            try:
                emb = emb_model.extract_waveform(clip(s), sr)
            except Exception:
                log.debug("Embedding failed for segment %.1f-%.1f", s.start, s.end,
                          exc_info=True)
                continue
            if np.isnan(emb).any() or np.linalg.norm(emb) == 0.0:
                continue
            space.segment_embeddings[i] = emb

    matches = _score_labels(space, segments)
    assigned = {m.label: m for m in matches if m.assigned is not None}
    unknown_map = unknown_names([lbl for lbl in unique_labels if lbl not in assigned])
    label_to_name: dict[str, tuple[str, float]] = {
        label: (
            (assigned[label].assigned, assigned[label].candidates[0].norm)
            if label in assigned
            else (unknown_map[label], -1.0)
        )
        for label in unique_labels
    }
    for m in matches:
        m.display = label_to_name[m.label][0]

    allowed: set[str] | None = None
    if attendees:
        allowed = set(attendees) | {m.assigned for m in matches if m.assigned}

    overrides: dict[int, tuple[str, float]] = {}
    if verify_on and matches:
        overrides = _verify_segments(segments, matches, label_to_name, space, allowed)
    elif config.verify_segments and not space.use_asnorm:
        log.info("Per-segment verification skipped: fewer than %d people enrolled",
                 config.asnorm_min_cohort)

    log.info("\n%s", format_match_report(matches, config))
    if any(m.verification is not None for m in matches):
        log.info("\n%s", format_verification_report(matches))

    identified = []
    for i, s in enumerate(segments):
        if i in overrides:
            name, conf = overrides[i]
            origin = "verified"
        else:
            name, conf = label_to_name[s.speaker_label]
            origin = "label"
        identified.append(
            IdentifiedSegment(s.start, s.end, s.text, name, conf,
                              label=s.speaker_label, origin=origin)
        )
    return identified, matches
