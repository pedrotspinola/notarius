"""Alternative names: map the names people appear under to one person.

A person can show up under several display names — "Odete Prado" in one
Zoom meeting, "Odete P." or a phone model name in another.  This file maps
each person (the name used in transcripts and voice profiles) to the other
names they appear under.  Stored as JSON next to the voice profiles.
"""

from __future__ import annotations

import json
from pathlib import Path

from notarius.config import PROFILES_DIR

ALIASES_FILE = PROFILES_DIR / "apelidos.json"


def load_aliases(path: Path = ALIASES_FILE) -> dict[str, list[str]]:
    """``{person: [other names]}``; empty when the file does not exist."""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_aliases(aliases: dict[str, list[str]], path: Path = ALIASES_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(aliases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_display_name(display_name: str, aliases: dict[str, list[str]]) -> str:
    """The person a display name belongs to, or the name itself (case-insensitive)."""
    lower = display_name.lower()
    for person, names in aliases.items():
        if person.lower() == lower:
            return person
        if any(alias.lower() == lower for alias in names):
            return person
    return display_name


def add_alias(person: str, display_name: str, path: Path = ALIASES_FILE) -> None:
    """Record that *display_name* is *person*.  Duplicates are ignored."""
    aliases = load_aliases(path)
    names = aliases.setdefault(person, [])
    if not any(a.lower() == display_name.lower() for a in names):
        names.append(display_name)
        save_aliases(aliases, path)


def remove_alias(person: str, display_name: str, path: Path = ALIASES_FILE) -> bool:
    """Forget one alternative name.  True if it existed."""
    aliases = load_aliases(path)
    names = aliases.get(person, [])
    kept = [a for a in names if a.lower() != display_name.lower()]
    if len(kept) == len(names):
        return False
    if kept:
        aliases[person] = kept
    else:
        del aliases[person]
    save_aliases(aliases, path)
    return True
