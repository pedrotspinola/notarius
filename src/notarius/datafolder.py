"""Prepare the user's Notarius folder.

Creates the folders, and puts the instructions for AI agents (AGENTS.md
and a CLAUDE.md that points to it) at the top, refreshed on every start so
updates reach them.  The notes templates in ``Notas`` are created only
when missing: from then on they belong to the user.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from notarius.config import DATA_DIR, MEETINGS_DIR, NOTES_DIR, PROFILES_DIR

_AGENT = resources.files("notarius") / "agent"
_MANAGED = ("AGENTS.md", "AGENTS.pt-BR.md")
# Claude Code reads CLAUDE.md, not AGENTS.md; one import line makes it read
# the same instructions.  Written from here rather than shipped as a file.
_CLAUDE_MD = b"@AGENTS.md\n"


def ensure_data_folder(root: Path = DATA_DIR) -> None:
    for d in (root, MEETINGS_DIR, PROFILES_DIR, NOTES_DIR):
        Path(d).mkdir(parents=True, exist_ok=True)
    files = {name: (_AGENT / name).read_bytes() for name in _MANAGED}
    files["CLAUDE.md"] = _CLAUDE_MD
    for name, content in files.items():
        target = root / name
        if not target.is_file() or target.read_bytes() != content:
            target.write_bytes(content)
    for template in (_AGENT / "notas").iterdir():
        target = NOTES_DIR / template.name
        if not target.exists():
            target.write_bytes(template.read_bytes())
