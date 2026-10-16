"""Clues about who is speaking, read from the transcript text.

People say who they are and who they are talking to, and that is often
worth more than any voice score:

* self-introductions: "meu nome é Odete", "aqui é o Vicente";
* being called on: "pode falar, Iolanda" — the NEXT voice is probably
  Iolanda;
* a person addressing someone by their OWN name ("…, Odete?" inside a turn
  credited to Odete) means that turn probably belongs to someone else —
  nobody calls themselves by name.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from notarius.config import UNKNOWN_PREFIX, IdentifiedSegment

_NAME = r"[A-ZÁÂÃÀÉÊÍÓÔÕÚÜÇ][a-záâãàéêíóôõúüç]+"
_FULL_NAME = rf"{_NAME}(?:\s+(?:d[aeo]s?\s+)?{_NAME})?"
_SELF_INTRO = re.compile(
    rf"\b(?:meu nome é|me chamo|eu sou (?:o|a)|aqui é (?:o|a)|quem fala é (?:o|a)|"
    rf"aqui quem fala é (?:o|a))\s+({_FULL_NAME})"
)
_CALL = re.compile(
    rf"(?:pode falar|com a palavra|tem a palavra|a palavra é (?:sua|tua)|"
    rf"sua vez|vai lá|fala aí|por favor),?\s+(?:o |a )?({_NAME})\b"
)
_CALL_BEFORE = re.compile(rf"\b({_NAME}),\s+(?:pode falar|com a palavra|por favor|sua vez)")
_VOCATIVE_END = re.compile(rf",\s+({_NAME})\s*[.?!]\s*$")
# Capitalized words that follow these phrases without being names.
_NOT_NAMES = {
    "Prefeitura", "Secretaria", "Secretário", "Secretária", "Presidente",
    "Coordenador", "Coordenadora", "Conselheiro", "Conselheira", "Diretor",
    "Diretora", "Gente", "Senhor", "Senhora", "Dona", "Doutor", "Doutora",
}
CALL_WINDOW = 8.0  # seconds: a call must come shortly before the answer


def fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


def first_name(name: str) -> str:
    return name.split()[0] if name.split() else name


@dataclass
class Hint:
    name: str  # suggested name, as spoken (or the known person it matches)
    why: str  # "intro" | "called" | "listed" | "voice"
    time: float | None = None  # when it was said
    quote: str = ""
    known: bool = False  # matches an enrolled or listed person


class NameBook:
    """Known people, findable by first name or by any of their names."""

    def __init__(self, people: Iterable[str], aliases: dict[str, list[str]] | None = None):
        self.by_key: dict[str, set[str]] = {}
        for person in people:
            self._add(person, person)
        for person, names in (aliases or {}).items():
            self._add(person, person)
            for n in names:
                self._add(n, person)

    def _add(self, name: str, person: str) -> None:
        for key in {fold(name), fold(first_name(name))}:
            self.by_key.setdefault(key, set()).add(person)

    def match(self, spoken: str) -> list[str]:
        return sorted(self.by_key.get(fold(spoken), set()))


def _resolve(spoken: str, book: NameBook) -> list[tuple[str, bool]]:
    known = book.match(spoken)
    return [(p, True) for p in known] if known else [(spoken, False)]


def label_hints(
    segments: list[IdentifiedSegment], label: str, book: NameBook
) -> list[Hint]:
    """Clues for one diarization label, best first, deduplicated."""
    hints: list[Hint] = []
    for i, seg in enumerate(segments):
        if seg.label != label:
            continue
        m = _SELF_INTRO.search(seg.text)
        if m and m.group(1).split()[0] not in _NOT_NAMES:
            for name, known in _resolve(m.group(1), book):
                hints.append(Hint(name, "intro", seg.start, m.group(0), known))
        prev = _previous_turn(segments, i)
        if prev is not None:
            for spoken in _calls(prev.text):
                for name, known in _resolve(spoken, book):
                    hints.append(Hint(name, "called", prev.start, prev.text[-80:], known))
    return _rank(hints)


def _previous_turn(segments: list[IdentifiedSegment], i: int) -> IdentifiedSegment | None:
    seg = segments[i]
    for j in range(i - 1, -1, -1):
        prev = segments[j]
        if prev.label == seg.label and prev.speaker_name == seg.speaker_name:
            return None  # same voice continuing: no handover here
        if seg.start - prev.end > CALL_WINDOW:
            return None
        return prev
    return None


def _calls(text: str) -> list[str]:
    found = [m.group(1) for m in _CALL.finditer(text)]
    found += [m.group(1) for m in _CALL_BEFORE.finditer(text)]
    m = _VOCATIVE_END.search(text)
    if m:
        found.append(m.group(1))
    return [f for f in found if f not in _NOT_NAMES]


def _rank(hints: list[Hint]) -> list[Hint]:
    weight = {"intro": 3, "called": 1}
    score: dict[str, float] = {}
    first: dict[str, Hint] = {}
    for h in hints:
        score[h.name] = score.get(h.name, 0) + weight.get(h.why, 1) + (0.5 if h.known else 0)
        if h.name not in first or weight.get(h.why, 1) > weight.get(first[h.name].why, 1):
            first[h.name] = h
    return [first[n] for n in sorted(score, key=lambda n: -score[n])]


def self_address(segments: list[IdentifiedSegment], min_len: int = 4) -> list[int]:
    """Indices of segments where the speaker addresses their own first name.

    Two legitimate exceptions exist (someone naming themselves for the
    record, or quoting a question addressed to them), so these are review
    candidates, never automatic changes.
    """
    hits = []
    for i, seg in enumerate(segments):
        if seg.speaker_name.startswith(UNKNOWN_PREFIX):
            continue
        name = fold(first_name(seg.speaker_name))
        if len(name) < min_len:
            continue
        pattern = rf"(^|[,;:]\s*|\?\s*|!\s*){re.escape(name)}([,?!.]|\s*$)"
        if re.search(pattern, fold(seg.text)):
            hits.append(i)
    return hits
