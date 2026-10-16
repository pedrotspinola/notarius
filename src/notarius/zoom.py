"""Zoom local recording folders.

With "Record a separate audio file for each participant" enabled, Zoom
writes one ``audio<DisplayName><digits>.m4a`` per participant who spoke
(in an ``Audio Record`` subfolder) besides the mixed ``audio<digits>.m4a``.
Per-participant tracks need no diarization: the file says who is speaking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_TRACK_RE = re.compile(r"^audio(.*?)(\d+)\.m4a$", re.IGNORECASE)


@dataclass
class ZoomParticipantAudio:
    path: Path
    display_name: str  # best-effort, recovered from the file name


@dataclass
class ZoomRecording:
    folder: Path
    mixed_audio: Path | None
    participant_audio: list[ZoomParticipantAudio]

    @property
    def has_per_participant(self) -> bool:
        return bool(self.participant_audio)


def _camel_to_display_name(name: str) -> str:
    """``"OdetePrado"`` → ``"Odete Prado"``; ``"TeodoroLima"`` → ``"Teodoro Lima"``."""
    out: list[str] = []
    for i, char in enumerate(name):
        if i > 0 and char.isupper() and name[i - 1].islower():
            out.append(" ")
        out.append(char)
    return "".join(out)


def _extract_display_name(filename: str) -> str:
    """Display name from ``audio<NameWithoutSpaces><digits>.m4a``."""
    m = _TRACK_RE.match(Path(filename).name)
    if not m or not m.group(1):
        return Path(filename).stem
    return _camel_to_display_name(m.group(1))


def _track_folder(folder: Path) -> Path | None:
    """The subfolder holding per-participant tracks, if any.

    Usually "Audio Record"; any subfolder of named ``audio…<digits>.m4a``
    files is accepted, in case the client names it differently.
    """
    preferred = folder / "Audio Record"
    if preferred.is_dir():
        return preferred
    for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
        if any(_TRACK_RE.match(f.name) and _TRACK_RE.match(f.name).group(1)
               for f in sub.iterdir() if f.is_file()):
            return sub
    return None


def is_zoom_folder(folder: Path) -> bool:
    """True when *folder* looks like a Zoom local recording."""
    if not folder.is_dir():
        return False
    has_mixed = any(
        f.is_file() and _TRACK_RE.match(f.name) for f in folder.iterdir()
    )
    return has_mixed or _track_folder(folder) is not None


def parse_zoom_folder(folder: Path) -> ZoomRecording:
    if not folder.is_dir():
        raise FileNotFoundError(f"Zoom recording folder not found: {folder}")

    mixed_audio: Path | None = None
    for f in sorted(folder.iterdir()):
        if f.is_file() and _TRACK_RE.match(f.name):
            mixed_audio = f
            break

    participant_audio: list[ZoomParticipantAudio] = []
    tracks = _track_folder(folder)
    if tracks is not None:
        for f in sorted(tracks.iterdir()):
            if f.is_file() and f.suffix.lower() == ".m4a":
                participant_audio.append(
                    ZoomParticipantAudio(path=f, display_name=_extract_display_name(f.name))
                )

    if mixed_audio is None and not participant_audio:
        raise ValueError(f"No audio files found in Zoom recording folder: {folder}")
    return ZoomRecording(folder, mixed_audio, participant_audio)


@dataclass
class ZoomChatMessage:
    timestamp: str  # HH:MM:SS
    sender: str
    text: str


# "HH:MM:SS\t From Name : message" (older clients add " to Everyone"; the
# Portuguese client may say "De ... para Todos").
_CHAT_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2})\s+(?:From|De)\s+(.+?)"
    r"(?:\s+(?:to|para)\s+(?:Everyone|Todos))?\s*:\s(.*)$"
)


def parse_zoom_chat(chat_path: Path, known_names: dict[str, str] | None = None) -> list[ZoomChatMessage]:
    """Parse ``chat.txt``; senders are resolved through *known_names*.

    *known_names* maps lowercase display names to the names used in the
    transcript; a sender also matches a known name it starts with
    ("Odete Prado - Cidade X" → "Odete Prado").  Reactions are skipped.
    """
    if not chat_path.is_file():
        return []
    known = known_names or {}
    messages: list[ZoomChatMessage] = []
    for line in chat_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CHAT_RE.match(line)
        if m:
            ts, sender, text = m.group(1), m.group(2).strip(), m.group(3)
            if text.startswith(("Reacted to ", "Reagiu a ")):
                continue
            messages.append(ZoomChatMessage(ts, _resolve_chat_sender(sender, known), text))
        elif messages:
            messages[-1].text += "\n" + line
    return messages


def _resolve_chat_sender(sender: str, known: dict[str, str]) -> str:
    lower = sender.lower()
    if lower in known:
        return known[lower]
    best, best_resolved = "", sender
    for key, resolved in known.items():
        if lower.startswith(key) and len(key) > len(best):
            best, best_resolved = key, resolved
    return best_resolved


def extract_meeting_datetime(folder: Path) -> str | None:
    """``"2026-03-16 11.00.31 …"`` → ``"2026-03-16_11-00-31"``."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{2})\.(\d{2})\.(\d{2})", folder.name)
    if m:
        date, h, mi, s = m.groups()
        return f"{date}_{h}-{mi}-{s}"
    return None
