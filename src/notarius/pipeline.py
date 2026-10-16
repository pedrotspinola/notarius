"""From a recording (file or Zoom folder) to a saved meeting record.

This is the one entry point both the command line and the app use.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from notarius.aliases import ALIASES_FILE, load_aliases, resolve_display_name
from notarius.config import (
    MEETINGS_DIR,
    PROFILES_DIR,
    WHISPER_MODEL,
    PipelineConfig,
)
from notarius.meeting import ChatMessage, Meeting
from notarius.zoom import (
    extract_meeting_datetime,
    is_zoom_folder,
    parse_zoom_chat,
    parse_zoom_folder,
)

log = logging.getLogger(__name__)

Progress = Callable[[str, str], None]

# Characters Windows does not allow in file names.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class RunSettings:
    """What the machine-dependent part of a run needs."""

    device: str = "cpu"
    compute_type: str = "int8"
    batch_size: int = 8
    whisper_model: str = WHISPER_MODEL
    profiles_dir: Path = field(default_factory=lambda: PROFILES_DIR)
    aliases_file: Path = field(default_factory=lambda: ALIASES_FILE)
    meetings_dir: Path = field(default_factory=lambda: MEETINGS_DIR)

    def pipeline_config(self) -> PipelineConfig:
        return PipelineConfig(
            profiles_dir=self.profiles_dir,
            whisper_model=self.whisper_model,
            compute_type=self.compute_type,
            batch_size=self.batch_size,
            device=self.device,
        )


def safe_file_name(text: str, limit: int = 80) -> str:
    cleaned = _UNSAFE_CHARS.sub("_", text).strip(" .")
    return cleaned[:limit] or "reuniao"


def probe_duration(path: str | Path) -> float | None:
    """Duration in seconds via ffprobe, or None."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, check=True, text=True,
        ).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return None


# ---------------------------------------------------------------------------
# Zoom rejoin duplicates
# ---------------------------------------------------------------------------


def should_mix(durations: list[float | None], ref: float | None) -> bool:
    """Whether a person's duplicate Zoom tracks are parallel or sequential.

    A participant who leaves and rejoins gets several tracks.  Usually Zoom
    strips muted time, so they are partial and must be concatenated; but
    some recordings keep every track at full meeting length, sharing one
    timeline, and concatenating those would push the second track's speech
    past the end of the meeting.  Parallel tracks (all within 5 s of the
    mixed audio's duration) are mixed instead.
    """
    if ref is None:
        if any(d is None for d in durations):
            return False
        ref = max(d for d in durations if d is not None)
    return all(d is not None and abs(d - ref) < 5.0 for d in durations)


def concat_quote(path: str) -> str:
    """Quote a path for an ffmpeg concat-demuxer list.

    Inside single quotes ffmpeg takes every character literally (Windows
    backslashes included) up to the next quote, so an apostrophe has to
    close the quote, appear escaped, and reopen it.  English-language Zoom
    folders always contain one ("<host>'s Zoom Meeting").
    """
    return "'" + path.replace("'", "'\\''") + "'"


def concat_audio_files(paths: list[str], out_path: Path) -> Path:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as listing:
        for p in paths:
            listing.write(f"file {concat_quote(str(p))}\n")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing.name,
             "-c", "copy", str(out_path)],
            capture_output=True, check=True,
        )
    finally:
        Path(listing.name).unlink(missing_ok=True)
    return out_path


def mix_audio_files(paths: list[str], out_path: Path) -> Path:
    """Overlay parallel tracks; normalize=0 keeps voice levels."""
    cmd = ["ffmpeg", "-y"]
    for p in paths:
        cmd += ["-i", str(p)]
    cmd += ["-filter_complex", f"amix=inputs={len(paths)}:duration=longest:normalize=0",
            "-c:a", "aac", "-b:a", "160k", str(out_path)]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_path


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def _meeting_path(meetings_dir: Path, date: str, title: str) -> Path:
    base = f"{date} {safe_file_name(title)}"
    path = meetings_dir / f"{base}.json"
    n = 2
    while path.exists():
        path = meetings_dir / f"{base} ({n}).json"
        n += 1
    return path


def run(
    source: Path,
    settings: RunSettings,
    attendees: list[str] | None = None,
    progress: Progress | None = None,
) -> Path:
    """Transcribe *source* and save the meeting.  Returns the JSON path."""
    aliases = load_aliases(settings.aliases_file)
    listed = [resolve_display_name(n, aliases) for n in attendees or []]
    config = settings.pipeline_config()
    settings.meetings_dir.mkdir(parents=True, exist_ok=True)

    if source.is_dir() and is_zoom_folder(source):
        date = extract_meeting_datetime(source) or _mtime_date(source)
        out = _meeting_path(settings.meetings_dir, date, source.name)
        meeting = _run_zoom(source, config, aliases, listed, out, progress)
        meeting.date = date
    elif source.is_file():
        date = _mtime_date(source)
        out = _meeting_path(settings.meetings_dir, date, source.stem)
        meeting = _run_file(source, config, listed, progress)
        meeting.date = date
    else:
        raise ValueError(f"Not an audio/video file or a Zoom recording folder: {source}")

    meeting.settings = {
        "whisper_model": config.whisper_model,
        "compute_type": config.compute_type,
        "device": config.device,
    }
    meeting.save(out)
    return out


def _mtime_date(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d_%H-%M-%S")


def _run_file(
    source: Path, config: PipelineConfig, listed: list[str], progress: Progress | None
) -> Meeting:
    from notarius.identify import identify_speakers
    from notarius.transcribe import transcribe

    segments = transcribe(source, config, progress)
    if progress:
        progress("identify", "Identifying speakers...")
    identified, matches = identify_speakers(segments, str(source), config, attendees=listed)
    labels, events = Meeting.labels_from_matches(matches)
    return Meeting(
        title=source.stem,
        source_kind="file",
        source_path=str(source),
        segments=identified,
        duration_seconds=probe_duration(source),
        listed_attendees=listed,
        labels=labels,
        events=events,
    )


def _run_zoom(
    folder: Path,
    config: PipelineConfig,
    aliases: dict[str, list[str]],
    listed: list[str],
    out: Path,
    progress: Progress | None,
) -> Meeting:
    recording = parse_zoom_folder(folder)
    ref = probe_duration(recording.mixed_audio) if recording.mixed_audio else None

    if not recording.has_per_participant:
        if recording.mixed_audio is None:
            raise ValueError(f"No audio in Zoom folder {folder}")
        meeting = _run_file(recording.mixed_audio, config, listed, progress)
        meeting.title, meeting.source_kind = folder.name, "zoom"
        names: dict[str, str] = {}
    else:
        from notarius.transcribe import transcribe_per_participant

        groups: dict[str, list[str]] = {}
        for pa in recording.participant_audio:
            groups.setdefault(resolve_display_name(pa.display_name, aliases), []).append(
                str(pa.path)
            )
        tracks: dict[str, str] = {}
        combined_dir = out.with_suffix("")  # "<meeting> /" next to the JSON
        for person, paths in groups.items():
            if len(paths) == 1:
                tracks[person] = paths[0]
                continue
            # Rejoined participant: keep the combined track, it is the
            # timeline the segments refer to (and enrollment needs it).
            combined_dir.mkdir(parents=True, exist_ok=True)
            target = combined_dir / f"{safe_file_name(person)}.m4a"
            if should_mix([probe_duration(p) for p in paths], ref):
                mix_audio_files(paths, target)
            else:
                concat_audio_files(paths, target)
            tracks[person] = str(target)

        segments = transcribe_per_participant(tracks, config, progress)
        meeting = Meeting(
            title=folder.name,
            source_kind="zoom",
            source_path=str(folder),
            segments=segments,
            duration_seconds=ref,
            tracks=tracks,
            listed_attendees=listed,
        )
        names = {pa.display_name.lower(): resolve_display_name(pa.display_name, aliases)
                 for pa in recording.participant_audio}

    known = dict(names)
    for person, alias_list in aliases.items():
        known[person.lower()] = person
        for a in alias_list:
            known[a.lower()] = person
    for seg in meeting.segments:
        known.setdefault(seg.speaker_name.lower(), seg.speaker_name)
    meeting.chat = [
        ChatMessage(m.timestamp, m.sender, m.text)
        for m in parse_zoom_chat(folder / "chat.txt", known)
    ]
    # source_path stays the mixed audio file in the fallback: clips for
    # review and enrollment are cut from it.
    return meeting
