"""End to end on real models: enroll, transcribe, review, enroll again.

Slow (downloads ~5 GB of models on first use and transcribes ~5 minutes of
audio), so it only runs with ``pytest -m slow``.  The recordings are
public-domain LibriVox readers (tests/fixtures; see THIRD_PARTY_NOTICES).

The cycle it checks is the one the app offers:

1. 11 voices are enrolled (enough for AS-Norm scoring).
2. A meeting of four enrolled voices and one stranger is transcribed:
   the four must be named correctly, the stranger must stay unknown.
3. The stranger is named, as the review page does, and enrolled from the
   meeting itself; a new run must now recognize them.
4. A Zoom folder with one track per participant is transcribed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from notarius.config import UNKNOWN_PREFIX, default_device
from notarius.meeting import Meeting
from notarius.pipeline import RunSettings, run

pytestmark = pytest.mark.slow

FIXTURES = Path(__file__).parent / "fixtures"
TRUTH = json.loads((FIXTURES / "meeting.truth.json").read_text(encoding="utf-8"))
MODEL = os.environ.get("NOTARIUS_TEST_MODEL", "large-v3")


def _settings(tmp: Path) -> RunSettings:
    device = default_device()
    return RunSettings(
        device=device,
        compute_type="int8",
        batch_size=8,
        whisper_model=MODEL,
        profiles_dir=tmp / "Vozes",
        aliases_file=tmp / "Vozes" / "apelidos.json",
        meetings_dir=tmp / "Transcrições",
    )


def _speaker_time(meeting: Meeting) -> dict[str, dict[str, float]]:
    """Seconds of each true speaker's turns attributed to each name."""
    out: dict[str, dict[str, float]] = {}
    for turn in TRUTH["turns"]:
        names = out.setdefault(turn["speaker"], {})
        for s in meeting.segments:
            overlap = min(s.end, turn["end"]) - max(s.start, turn["start"])
            if overlap > 0:
                names[s.speaker_name] = names.get(s.speaker_name, 0.0) + overlap
    return out


def _share(names: dict[str, float], wanted) -> float:
    total = sum(names.values())
    return sum(v for k, v in names.items() if wanted(k)) / total if total else 0.0


@pytest.fixture(scope="module")
def workdir(tmp_path_factory) -> Path:
    from notarius.profiles import enroll_from_files

    tmp = tmp_path_factory.mktemp("notarius")
    settings = _settings(tmp)
    for name in TRUTH["enrolled"]:
        enroll_from_files(name, [FIXTURES / "voices" / f"{name}.opus"],
                          settings.profiles_dir, settings.device)
    yield tmp
    keep = os.environ.get("NOTARIUS_TEST_KEEP")
    if keep:  # CI uploads these, so a failure can be read afterwards
        import shutil

        shutil.copytree(settings.meetings_dir, Path(keep) / "Transcrições", dirs_exist_ok=True)


def test_meeting_identifies_enrolled_and_keeps_stranger_unknown(workdir):
    settings = _settings(workdir)
    meeting = Meeting.load(run(FIXTURES / "meeting.opus", settings))
    assert meeting.labels and meeting.labels[0]["scoring"] == "asnorm"
    by_speaker = _speaker_time(meeting)
    for name in ("Voz 01", "Voz 02", "Voz 03", "Voz 04"):
        share = _share(by_speaker[name], lambda k, n=name: k == n)
        assert share >= 0.9, (name, by_speaker[name])
    stranger = by_speaker[TRUTH["unenrolled"][0]]
    assert _share(stranger, lambda k: k.startswith(UNKNOWN_PREFIX)) >= 0.9, stranger
    assert meeting.render_text().startswith("Presentes: ")


def test_naming_the_stranger_then_enrolling_makes_them_recognized(workdir):
    from notarius.enroll import execute, plan_enrollment

    settings = _settings(workdir)
    path = sorted(settings.meetings_dir.glob("*.json"))[0]
    meeting = Meeting.load(path)
    stranger = TRUTH["unenrolled"][0]
    for s in meeting.segments:  # what the review page does for an unknown label
        if s.speaker_name.startswith(UNKNOWN_PREFIX):
            s.speaker_name, s.origin = stranger, "review"
    meeting.save(path)

    plans = {p.person: p for p in plan_enrollment(meeting, settings.profiles_dir)}
    assert plans[stranger].action == "enroll", plans[stranger]
    outcomes = execute(list(plans.values()), settings.profiles_dir, settings.device)
    assert [o.plan.person for o in outcomes if o.profile_path] == [stranger]

    again = Meeting.load(run(FIXTURES / "meeting.opus", settings))
    share = _share(_speaker_time(again)[stranger], lambda k: k == stranger)
    assert share >= 0.9, _speaker_time(again)[stranger]


def test_zoom_folder_with_one_track_per_participant(workdir, tmp_path):
    names = {"Voz 01": "OdetePrado", "Voz 02": "VicenteRocha", "Voz 12": "IolandaLima"}
    folder = tmp_path / "2026-03-16 11.00.31 Teodoro's Zoom Meeting"
    tracks = folder / "Audio Record"
    tracks.mkdir(parents=True)
    src = FIXTURES / "meeting.opus"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-c:a", "aac",
                    str(folder / "audio1028817842.m4a")], check=True)
    for i, (voice, camel) in enumerate(names.items(), 1):
        # Each track keeps only its own turns; everything else is silence,
        # as when Zoom records muted time.
        spans = [t for t in TRUTH["turns"] if t["speaker"] == voice]
        keep = "+".join(f"between(t,{t['start']},{t['end']})" for t in spans)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src),
                        "-af", f"volume=enable='not({keep})':volume=0", "-c:a", "aac",
                        str(tracks / f"audio{camel}{i}1028817842.m4a")], check=True)
    (folder / "chat.txt").write_text("00:00:05\t From Odete Prado : bom dia\n", encoding="utf-8")

    meeting = Meeting.load(run(folder, _settings(workdir)))
    assert meeting.source_kind == "zoom" and len(meeting.tracks) == 3
    by_speaker = _speaker_time(meeting)
    expected = {"Voz 01": "Odete Prado", "Voz 02": "Vicente Rocha", "Voz 12": "Iolanda Lima"}
    for voice, display in expected.items():
        assert _share(by_speaker[voice], lambda k, d=display: k == d) >= 0.95, by_speaker[voice]
    assert [(m.sender, m.text) for m in meeting.chat] == [("Odete Prado", "bom dia")]
