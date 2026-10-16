"""The meeting record: one JSON file per transcribed meeting.

The JSON file is the source of truth.  It keeps every segment unmerged,
with the diarization label it came from, its score and how its speaker was
decided, so the review page can rename a whole label or a single segment
and regenerate the readable transcript (``.txt``) at any time.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from notarius import __version__
from notarius.config import (
    UNKNOWN_PREFIX,
    IdentifiedSegment,
    LabelMatch,
    MeetingAttendee,
)

SCHEMA = 1
MERGE_GAP = 1.0  # seconds: same-speaker segments closer than this are joined


def format_timestamp(seconds: float) -> str:
    """Seconds → ``HH:MM:SS``."""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def merge_consecutive(
    segments: list[IdentifiedSegment], gap: float = MERGE_GAP
) -> list[IdentifiedSegment]:
    """Join consecutive segments of the same speaker less than *gap* apart."""
    merged: list[IdentifiedSegment] = []
    for seg in segments:
        prev = merged[-1] if merged else None
        if prev and seg.speaker_name == prev.speaker_name and seg.start - prev.end <= gap:
            merged[-1] = IdentifiedSegment(
                start=prev.start,
                end=seg.end,
                text=f"{prev.text} {seg.text}",
                speaker_name=prev.speaker_name,
                confidence=max(prev.confidence, seg.confidence),
                label=prev.label,
                origin=prev.origin,
            )
        else:
            merged.append(seg)
    return merged


def build_attendees(
    segments: list[IdentifiedSegment], listed: list[str] | None = None
) -> list[MeetingAttendee]:
    """Everyone who spoke, plus listed people who did not (spoke=False).

    Unknown speakers are left out.  Matching of listed names is
    case-insensitive, so "odete" does not duplicate "Odete" who spoke.
    """
    counts: dict[str, int] = {}
    for seg in segments:
        counts[seg.speaker_name] = counts.get(seg.speaker_name, 0) + 1
    attendees = {
        name: MeetingAttendee(name, True, n)
        for name, n in counts.items()
        if not name.startswith(UNKNOWN_PREFIX)
    }
    seen = {name.lower() for name in counts}
    for name in listed or []:
        if name.lower() not in seen:
            attendees[name] = MeetingAttendee(name, False, 0)
            seen.add(name.lower())
    return sorted(attendees.values(), key=lambda a: a.name.lower())


@dataclass
class ChatMessage:
    time: str  # HH:MM:SS
    sender: str
    text: str


@dataclass
class Meeting:
    """Everything known about one transcribed meeting."""

    title: str
    source_kind: str  # "file" or "zoom"
    source_path: str
    segments: list[IdentifiedSegment]
    date: str | None = None
    duration_seconds: float | None = None
    tracks: dict[str, str] = field(default_factory=dict)  # Zoom: person -> track file
    listed_attendees: list[str] = field(default_factory=list)
    labels: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    chat: list[ChatMessage] = field(default_factory=list)
    settings: dict = field(default_factory=dict)
    review_status: str = "pending"  # "pending" | "done"
    learned: list[str] = field(default_factory=list)  # voices already learned from it
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated: str | None = None

    # -- building ---------------------------------------------------------

    @staticmethod
    def labels_from_matches(matches: list[LabelMatch] | None) -> tuple[list[dict], list[dict]]:
        """Label diagnostics and verification events as JSON-ready dicts."""
        labels: list[dict] = []
        events: list[dict] = []
        for m in matches or []:
            entry = {
                "label": m.label,
                "name": m.display or m.assigned,
                "matched": m.assigned is not None,
                "segments": m.n_segments,
                "duration_seconds": round(m.duration, 1),
                "scoring": "asnorm" if m.used_asnorm else "raw",
                "candidates": [
                    {"person": c.name, "raw": round(c.raw, 3), "norm": round(c.norm, 2),
                     "excess": round(c.excess, 2)}
                    for c in m.candidates
                ],
            }
            if m.verification is not None:
                v = m.verification
                entry["verification"] = {
                    k: getattr(v, k)
                    for k in ("n_segments", "verified", "inherited", "reassigned",
                              "flagged", "suspect", "possible", "kept", "gated")
                }
                for e in v.events:
                    events.append({
                        "index": e.index,
                        "start": round(e.start, 2),
                        "end": round(e.end, 2),
                        "kind": e.kind,
                        "label": m.label,
                        "from": e.from_name,
                        "to": e.to_name,
                        "own_norm": None if e.own_norm is None else round(e.own_norm, 2),
                        "best": e.best_name,
                        "best_norm": round(e.best_norm, 2),
                        "text": e.text,
                    })
            labels.append(entry)
        events.sort(key=lambda e: e["start"])
        return labels, events

    # -- views ------------------------------------------------------------

    def attendees(self) -> list[MeetingAttendee]:
        return build_attendees(self.segments, self.listed_attendees)

    def render_text(self) -> str:
        """The readable transcript: attendance, speech, then chat."""
        lines: list[str] = []
        attendees = self.attendees()
        if attendees:
            spoke = [a.name for a in attendees if a.spoke]
            silent = [f"{a.name}*" for a in attendees if not a.spoke]
            lines.append(f"Presentes: {', '.join(spoke + silent)}")
            if silent:
                lines.append("(* não falou)")
            lines.append("")
        for seg in merge_consecutive(self.segments):
            lines.append(f"{seg.speaker_name} [{format_timestamp(seg.start)}]: {seg.text}")
        if self.chat:
            lines += ["", "--- Chat ---", ""]
            for msg in self.chat:
                text = msg.text.replace("\n", "\n    ")
                lines.append(f"{msg.sender} [{msg.time}]: {text}")
        return "\n".join(lines) + "\n"

    # -- storage ----------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "notarius_version": __version__,
            "title": self.title,
            "date": self.date,
            "created": self.created,
            "updated": self.updated,
            "review_status": self.review_status,
            "learned": self.learned,
            "source": {
                "kind": self.source_kind,
                "path": self.source_path,
                "duration_seconds": self.duration_seconds,
                "tracks": self.tracks,
            },
            "settings": self.settings,
            "listed_attendees": self.listed_attendees,
            "attendees": [asdict(a) for a in self.attendees()],
            "labels": self.labels,
            "events": self.events,
            "segments": [
                {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text,
                 "speaker": s.speaker_name, "confidence": round(s.confidence, 3),
                 "label": s.label, "origin": s.origin}
                for s in self.segments
            ],
            "chat": [asdict(c) for c in self.chat],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Meeting:
        if data.get("schema") != SCHEMA:
            raise ValueError(f"Unsupported meeting file schema: {data.get('schema')!r}")
        src = data["source"]
        return cls(
            title=data["title"],
            source_kind=src["kind"],
            source_path=src["path"],
            duration_seconds=src.get("duration_seconds"),
            tracks=src.get("tracks") or {},
            date=data.get("date"),
            created=data["created"],
            updated=data.get("updated"),
            review_status=data.get("review_status", "pending"),
            learned=data.get("learned") or [],
            settings=data.get("settings") or {},
            listed_attendees=data.get("listed_attendees") or [],
            labels=data.get("labels") or [],
            events=data.get("events") or [],
            segments=[
                IdentifiedSegment(s["start"], s["end"], s["text"], s["speaker"],
                                  s["confidence"], label=s.get("label", ""),
                                  origin=s.get("origin", "label"))
                for s in data["segments"]
            ],
            chat=[ChatMessage(**c) for c in data.get("chat") or []],
        )

    def save(self, json_path: Path) -> Path:
        """Write the JSON record and the ``.txt`` beside it.  Returns the txt path."""
        json_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        tmp.replace(json_path)
        txt_path = json_path.with_suffix(".txt")
        txt_path.write_text(self.render_text(), encoding="utf-8")
        return txt_path

    @classmethod
    def load(cls, json_path: Path) -> Meeting:
        return cls.from_dict(json.loads(json_path.read_text(encoding="utf-8")))
