"""WhatsApp chat exports: find a person's voice messages for enrollment.

Voice messages are close-microphone recordings of one person, which makes
them good material for a first voice profile.  Two export formats exist:

* iPhone:  ``[DD/MM/YYYY, HH:MM:SS] Name: <anexado: 00000012-AUDIO-….opus>``
* Android: ``DD/MM/YYYY HH:MM - Name: PTT-20260101-WA0001.opus (arquivo anexado)``

Both are recognized; the English variants ("attached") too.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from notarius.config import FFMPEG_MISSING

logger = logging.getLogger(__name__)

_IOS_RE = re.compile(r"^\[(\d{2}/\d{2}/\d{4}),\s(\d{2}:\d{2}(?::\d{2})?)\]\s(.+?):\s(.*)")
_ANDROID_RE = re.compile(r"^(\d{2}/\d{2}/\d{2,4}),?\s(\d{2}:\d{2})\s-\s(.+?):\s(.*)")
_IOS_ATTACH_RE = re.compile(r"<(?:anexado|attached):\s*(.+?)>")
_ANDROID_ATTACH_RE = re.compile(r"^(.+?\.\w+)\s\((?:arquivo anexado|file attached)\)")
_AUDIO_EXTENSIONS = (".opus", ".ogg", ".m4a", ".mp3", ".aac")


def find_chat_file(export_dir: Path) -> Path:
    """The chat text file of an export folder."""
    export_dir = Path(export_dir)
    for name in ("_chat.txt",):
        if (export_dir / name).is_file():
            return export_dir / name
    candidates = sorted(export_dir.glob("_chat*.txt")) + sorted(export_dir.glob("*.txt"))
    for txt in candidates:
        try:
            with txt.open("r", encoding="utf-8-sig") as f:
                first = f.readline().replace("‎", "")
        except (OSError, UnicodeDecodeError):
            continue
        if _IOS_RE.match(first) or _ANDROID_RE.match(first):
            return txt
    raise FileNotFoundError(f"No WhatsApp chat file found in {export_dir}.")


def parse_messages(chat_file: Path) -> list[tuple[str, str]]:
    """``(sender, content)`` for every message line, either format."""
    messages: list[tuple[str, str]] = []
    with chat_file.open("r", encoding="utf-8-sig") as f:
        for line in f:
            clean = line.replace("‎", "").rstrip("\n")
            m = _IOS_RE.match(clean) or _ANDROID_RE.match(clean)
            if m:
                messages.append((m.group(3).strip(), m.group(4)))
    return messages


def senders(export_dir: Path) -> list[tuple[str, int]]:
    """Every sender with the number of voice messages they sent."""
    counts: dict[str, int] = {}
    for sender, content in parse_messages(find_chat_file(export_dir)):
        if _attachment(content):
            counts[sender] = counts.get(sender, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def _attachment(content: str) -> str | None:
    m = _IOS_ATTACH_RE.search(content) or _ANDROID_ATTACH_RE.match(content)
    if not m:
        return None
    name = m.group(1).strip()
    return name if name.lower().endswith(_AUDIO_EXTENSIONS) else None


def _get_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except FileNotFoundError:
        raise RuntimeError(FFMPEG_MISSING)
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        logger.debug("ffprobe failed for %s: %s", path, exc)
    return None


def _locate_file(export_dir: Path, filename: str) -> Path | None:
    direct = export_dir / filename
    if direct.is_file():
        return direct
    for candidate in export_dir.rglob(filename):
        if candidate.is_file():
            return candidate
    return None


def find_audio_by_sender(export_dir: Path, sender_name: str) -> list[dict]:
    """Voice messages from *sender_name*, longest first.

    The sender matches case-insensitively and by substring ("Odete" matches
    "Odete Prado").  Returns ``[{"path", "duration", "filename"}, ...]``.
    """
    export_dir = Path(export_dir)
    wanted = sender_name.lower()
    results: list[dict] = []
    for sender, content in parse_messages(find_chat_file(export_dir)):
        if wanted not in sender.lower():
            continue
        filename = _attachment(content)
        if filename is None:
            continue
        path = _locate_file(export_dir, filename)
        if path is None:
            continue
        duration = _get_duration(path)
        if duration is not None:
            results.append({"path": path, "duration": duration, "filename": filename})
    results.sort(key=lambda x: x["duration"], reverse=True)
    return results


def select_enrollment_files(
    audio_files: list[dict], min_duration: float = 3.0, max_files: int = 10
) -> list[Path]:
    """The longest files of at least *min_duration* seconds."""
    return [f["path"] for f in audio_files if f["duration"] >= min_duration][:max_files]
