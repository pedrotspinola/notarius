"""Zoom folders: track detection, rejoin duplicates, chat parsing."""

import subprocess
from pathlib import Path

import pytest

from notarius.pipeline import concat_audio_files, concat_quote, probe_duration, should_mix
from notarius.zoom import (
    _extract_display_name,
    extract_meeting_datetime,
    is_zoom_folder,
    parse_zoom_chat,
    parse_zoom_folder,
)

REF = 7614.93


def test_parallel_full_length_tracks_are_mixed():
    # Every track the length of the meeting: one shared timeline.
    assert should_mix([7614.93, 7614.93], REF)
    assert should_mix([7611.2, 7614.93], REF)  # < 5 s drift tolerated
    assert should_mix([7614.93, 7614.93], None)


def test_partial_rejoin_tracks_are_concatenated():
    assert not should_mix([1800.0, 5400.0], REF)
    assert not should_mix([3807.0, 3807.9], REF)  # even if they sum to the meeting
    assert not should_mix([1800.0, 5400.0], None)


def test_failed_probes_fall_back_to_concat():
    assert not should_mix([None, 7614.93], REF)
    assert not should_mix([None, None], None)
    assert should_mix([7614.93], REF)


def test_concat_quote():
    assert concat_quote("/a/b.m4a") == "'/a/b.m4a'"
    assert concat_quote("/x/Odete's Zoom/a.m4a") == "'/x/Odete'\\''s Zoom/a.m4a'"
    assert concat_quote(r"C:\Users\x\a.m4a") == r"'C:\Users\x\a.m4a'"


def _tone(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", str(path)],
        check=True,
    )


@pytest.mark.skipif(subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode,
                    reason="needs ffmpeg")
def test_concat_with_apostrophe_in_folder(tmp_path):
    # English Zoom names folders "<host>'s Zoom Meeting"; the unescaped
    # quote once made every rejoin concatenation fail.
    folder = tmp_path / "2026-03-16 11.00.31 Odete Prado's Zoom Meeting"
    folder.mkdir()
    a, b = folder / "a1.m4a", folder / "a2.m4a"
    _tone(a, 2.0)
    _tone(b, 3.0)
    out = concat_audio_files([str(a), str(b)], tmp_path / "joined.m4a")
    assert abs(probe_duration(out) - 5.0) < 0.2


def test_display_names_from_track_files():
    assert _extract_display_name("audioOdetePrado11028817842.m4a") == "Odete Prado"
    assert _extract_display_name("audioTeodoroLima21028817842.m4a") == "Teodoro Lima"
    assert _extract_display_name("audio1028817842.m4a") == "audio1028817842"


def test_folder_detection(tmp_path):
    folder = tmp_path / "2026-03-16 11.00.31 Reunião"
    tracks = folder / "Gravação de áudio"  # a client that names it differently
    tracks.mkdir(parents=True)
    (folder / "audio1028817842.m4a").write_bytes(b"")
    (tracks / "audioOdetePrado11028817842.m4a").write_bytes(b"")
    assert is_zoom_folder(folder)
    rec = parse_zoom_folder(folder)
    assert rec.mixed_audio.name == "audio1028817842.m4a"
    assert [p.display_name for p in rec.participant_audio] == ["Odete Prado"]
    assert extract_meeting_datetime(folder) == "2026-03-16_11-00-31"
    assert not is_zoom_folder(tmp_path)


def test_chat_formats(tmp_path):
    chat = tmp_path / "chat.txt"
    chat.write_text(
        "00:01:02\t From Odete Prado - Coletivo X : bom dia\n"
        "00:02:03 From Vicente to Everyone: oi\n"
        "segunda linha\n"
        "00:03:04 De Iolanda para Todos: olá\n"
        "00:04:05\t From Vicente : Reacted to \"oi\" with 👍\n",
        encoding="utf-8",
    )
    msgs = parse_zoom_chat(chat, {"odete prado": "Odete Prado"})
    assert [(m.sender, m.text) for m in msgs] == [
        ("Odete Prado", "bom dia"),
        ("Vicente", "oi\nsegunda linha"),
        ("Iolanda", "olá"),
    ]
