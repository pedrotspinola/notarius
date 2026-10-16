"""What to ask the user after a transcription, and applying the answers.

Review items, most important first:

``unknown``   a voice nobody recognized ("Desconhecido N"): who is it?
``confirm``   a voice matched to someone, but weakly: is it really them?
``segment``   one stretch the automatic second check changed or doubted.
``self``      a stretch where the speaker addresses their own name —
              probably someone else's words.

Each item carries clips to listen to and suggestions with a reason.  The
answers rename whole labels or single segments; the meeting record and its
text are rewritten.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from notarius.aliases import load_aliases
from notarius.config import (
    UNKNOWN_PREFIX,
    PipelineConfig,
    validate_base_name,
)
from notarius.hints import NameBook, label_hints, self_address
from notarius.meeting import Meeting, format_timestamp
from notarius.profiles import list_profiles

CLIP_MAX = 12.0  # seconds per clip
CLIPS_PER_VOICE = 3
MAX_SEGMENT_ITEMS = 20
FLAGGED_MIN = 6.0  # flagged segments shorter than this are not worth asking about


@dataclass
class Clip:
    start: float
    end: float
    text: str
    person: str  # whose track to play (Zoom per-participant); "" for mixed
    index: int | None = None  # segment index, for the transcript view


@dataclass
class Suggestion:
    name: str
    why: str  # "voice" | "intro" | "called" | "listed" | "current" | "verify"
    detail: str = ""
    score: float | None = None


@dataclass
class ReviewItem:
    id: str
    kind: str  # unknown | confirm | segment | self
    reason: str  # code: unknown, unproven, low_margin, not_listed, gated, ...
    current: str
    seconds: float
    clips: list[Clip]
    suggestions: list[Suggestion] = field(default_factory=list)
    context: list[dict] = field(default_factory=list)  # neighbouring lines


def _clips_for(meeting: Meeting, indices: list[int], n: int = CLIPS_PER_VOICE) -> list[Clip]:
    ranked = sorted(indices, key=lambda i: meeting.segments[i].end - meeting.segments[i].start,
                    reverse=True)[:n]
    out = []
    for i in sorted(ranked):
        s = meeting.segments[i]
        out.append(Clip(s.start, min(s.end, s.start + CLIP_MAX), s.text, track_of(meeting, i), i))
    return out


def track_of(meeting: Meeting, i: int) -> str:
    """The per-participant track a segment came from ("" for mixed audio)."""
    label = meeting.segments[i].label
    return label if label in meeting.tracks else ""


def _context(meeting: Meeting, i: int, around: int = 2) -> list[dict]:
    lo, hi = max(0, i - around), min(len(meeting.segments), i + around + 1)
    return [
        {"index": j, "speaker": meeting.segments[j].speaker_name,
         "time": format_timestamp(meeting.segments[j].start),
         "text": meeting.segments[j].text, "focus": j == i}
        for j in range(lo, hi)
    ]


def _name_book(meeting: Meeting, profiles_dir) -> NameBook:
    people = set(list_profiles(profiles_dir)) | set(meeting.listed_attendees)
    people |= {s.speaker_name for s in meeting.segments
               if not s.speaker_name.startswith(UNKNOWN_PREFIX)}
    return NameBook(people, load_aliases())


def _voice_suggestions(label: dict, hint: float, skip: str | None = None) -> list[Suggestion]:
    out = []
    for c in label.get("candidates", []):
        if c["person"] == skip:
            continue
        if label.get("scoring") == "asnorm" and c["norm"] < hint:
            break
        out.append(Suggestion(c["person"], "voice", f"{c['norm']:.1f}", c["norm"]))
    return out[:2]


def _text_suggestions(meeting: Meeting, label: str, book: NameBook) -> list[Suggestion]:
    out = []
    for h in label_hints(meeting.segments, label, book)[:3]:
        when = format_timestamp(h.time) if h.time is not None else ""
        out.append(Suggestion(h.name, h.why, f"{when} «{h.quote.strip()}»"))
    return out


def _merge(suggestions: list[Suggestion]) -> list[Suggestion]:
    seen: dict[str, Suggestion] = {}
    for s in suggestions:
        if s.name not in seen:
            seen[s.name] = s
    return list(seen.values())


def build_review(
    meeting: Meeting, profiles_dir, config: PipelineConfig | None = None
) -> list[ReviewItem]:
    config = config or PipelineConfig()
    book = _name_book(meeting, profiles_dir)
    by_label: dict[str, list[int]] = {}
    for i, s in enumerate(meeting.segments):
        by_label.setdefault(s.label, []).append(i)
    present = {s.speaker_name for s in meeting.segments}
    silent_listed = [n for n in meeting.listed_attendees if n not in present]
    listed = {n.lower() for n in meeting.listed_attendees}

    # Every diarization label still carrying an unknown name must be asked
    # about, even if the record has no diagnostics for it.
    labels = list(meeting.labels)
    known_labels = {lab["label"] for lab in labels}
    for label, indices in by_label.items():
        if label and label not in known_labels and label not in meeting.tracks and any(
            meeting.segments[i].origin == "label"
            and meeting.segments[i].speaker_name.startswith(UNKNOWN_PREFIX)
            for i in indices
        ):
            labels.append({"label": label, "matched": False, "candidates": [],
                           "scoring": "raw"})

    items: list[ReviewItem] = []
    for lab in labels:
        label = lab["label"]
        # Segments still carrying the label's automatic name.
        indices = [i for i in by_label.get(label, [])
                   if meeting.segments[i].origin == "label"]
        if not indices:
            continue
        current = meeting.segments[indices[0]].speaker_name
        seconds = sum(meeting.segments[i].end - meeting.segments[i].start for i in indices)
        clips = _clips_for(meeting, indices)
        text = _text_suggestions(meeting, label, book)
        if not lab["matched"]:
            listed_sugs = [Suggestion(n, "listed") for n in silent_listed]
            items.append(ReviewItem(
                f"label:{label}", "unknown", "unknown", current, seconds, clips,
                _merge(text + _voice_suggestions(lab, config.asnorm_hint) + listed_sugs),
            ))
            continue
        top = lab["candidates"][0]
        reason = None
        if top["raw"] < config.unproven_raw:
            reason = "unproven"
        elif len(lab["candidates"]) > 1 and top["excess"] - lab["candidates"][1]["excess"] < 1.0:
            reason = "low_margin"
        elif listed and current.lower() not in listed:
            reason = "not_listed"
        if reason:
            items.append(ReviewItem(
                f"label:{label}", "confirm", reason, current, seconds, clips,
                _merge([Suggestion(current, "current", f"{top['norm']:.1f}", top["norm"])]
                       + text + _voice_suggestions(lab, config.asnorm_hint, skip=current)),
            ))

    seg_items: list[ReviewItem] = []
    for e in meeting.events:
        i = e["index"]
        if i >= len(meeting.segments):
            continue
        s = meeting.segments[i]
        if s.origin == "review":
            continue
        dur = s.end - s.start
        if e["kind"] == "flagged" and dur < FLAGGED_MIN:
            continue
        if e["kind"] not in ("reassigned", "gated", "suspect", "flagged"):
            continue
        sugs = [Suggestion(s.speaker_name, "current")]
        other = e["to"] if e["kind"] in ("reassigned", "gated") else e["best"]
        if e["kind"] == "reassigned":
            sugs.append(Suggestion(e["from"], "before"))
        elif other:
            sugs.append(Suggestion(other, "verify", f"{e['best_norm']:.1f}", e["best_norm"]))
        seg_items.append(ReviewItem(
            f"seg:{i}", "segment", e["kind"], s.speaker_name, dur,
            _clips_for(meeting, [i], 1), _merge(sugs), _context(meeting, i),
        ))
    for i in self_address(meeting.segments):
        s = meeting.segments[i]
        if s.origin == "review" or any(it.id == f"seg:{i}" for it in seg_items):
            continue
        prev = meeting.segments[i - 1].speaker_name if i > 0 else None
        sugs = [Suggestion(s.speaker_name, "current")]
        if prev and prev != s.speaker_name:
            sugs.append(Suggestion(prev, "neighbour"))
        seg_items.append(ReviewItem(
            f"seg:{i}", "self", "self_address", s.speaker_name, s.end - s.start,
            _clips_for(meeting, [i], 1), _merge(sugs), _context(meeting, i),
        ))

    items.sort(key=lambda it: (it.kind != "unknown", it.kind != "confirm", -it.seconds))
    seg_items.sort(key=lambda it: it.clips[0].start if it.clips else 0)
    return items + seg_items[:MAX_SEGMENT_ITEMS]


def items_as_dicts(items: list[ReviewItem]) -> list[dict]:
    return [asdict(it) for it in items]


# ---------------------------------------------------------------------------
# Applying answers
# ---------------------------------------------------------------------------


def apply_answers(meeting: Meeting, answers: dict[str, str]) -> dict[str, int]:
    """Apply ``{item_id: name}`` answers.  Returns renamed counts per item.

    ``label:<L>`` renames every segment that still carries label L's
    automatic name; ``seg:<i>`` renames one segment.  Names that would be
    new people must be usable as profile names.
    """
    changed: dict[str, int] = {}
    for item_id, name in answers.items():
        name = " ".join(name.split())
        if not name:
            continue
        if not name.startswith(UNKNOWN_PREFIX):
            validate_base_name(name)
        if item_id.startswith("label:"):
            label = item_id[len("label:"):]
            n = 0
            for s in meeting.segments:
                if s.label == label and s.origin == "label":
                    if s.speaker_name != name:
                        n += 1
                    s.speaker_name, s.origin = name, "review"
            changed[item_id] = n
        elif item_id.startswith("seg:"):
            changed[item_id] = rename_segments(meeting, [int(item_id[4:])], name)
    meeting.updated = datetime.now().isoformat(timespec="seconds")
    return changed


def rename_segments(meeting: Meeting, indices: list[int], name: str) -> int:
    name = " ".join(name.split())
    if not name.startswith(UNKNOWN_PREFIX):
        validate_base_name(name)
    n = 0
    for i in indices:
        if 0 <= i < len(meeting.segments):
            s = meeting.segments[i]
            if s.speaker_name != name:
                n += 1
            s.speaker_name, s.origin = name, "review"
    meeting.updated = datetime.now().isoformat(timespec="seconds")
    return n


def merged_lines(meeting: Meeting) -> list[dict]:
    """The transcript as shown, with the segment indices behind each line."""
    from notarius.meeting import MERGE_GAP

    lines: list[dict] = []
    for i, s in enumerate(meeting.segments):
        last = lines[-1] if lines else None
        if (last and last["speaker"] == s.speaker_name and last["person"] == track_of(meeting, i)
                and s.start - meeting.segments[last["indices"][-1]].end <= MERGE_GAP):
            last["indices"].append(i)
            last["text"] += " " + s.text
            last["end"] = s.end
        else:
            lines.append({"speaker": s.speaker_name, "start": s.start, "end": s.end,
                          "time": format_timestamp(s.start), "text": s.text, "indices": [i],
                          "person": track_of(meeting, i)})
    return lines
