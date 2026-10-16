"""Who gets a voice profile after a meeting is reviewed."""

from notarius.config import IdentifiedSegment
from notarius.enroll import MIN_TOTAL, plan_enrollment
from notarius.meeting import Meeting


def long_turns(name, start, n, each=10.0, gap=20.0, label=""):
    """*n* turns of *each* seconds, *gap* apart, overlapping nobody."""
    return [IdentifiedSegment(start + i * gap, start + i * gap + each, "fala", name, 5.0,
                              label=label)
            for i in range(n)]


def meeting(segments, labels=None, tracks=None):
    return Meeting("Reunião", "file", "/r.mkv", segments, date="2026-03-16_11-00-31",
                   labels=labels or [], tracks=tracks or {})


def label(name, raw):
    return {"name": name, "candidates": [{"person": name, "raw": raw}]}


def plans_by_person(m, profiles_dir):
    return {p.person: p for p in plan_enrollment(m, profiles_dir)}


def test_new_person_with_enough_speech(tmp_path):
    p = plans_by_person(meeting(long_turns("Odete", 0, 6)), tmp_path)["Odete"]
    assert (p.action, p.code, p.target_profile) == ("enroll", "new_person", "Odete")
    assert p.selected_seconds >= MIN_TOTAL


def test_too_little_speech(tmp_path):
    p = plans_by_person(meeting(long_turns("Odete", 0, 2)), tmp_path)["Odete"]
    assert (p.action, p.code) == ("skip", "too_little_speech")


def test_unknowns_are_never_enrolled(tmp_path):
    assert "Desconhecido 1" not in plans_by_person(
        meeting(long_turns("Desconhecido 1", 0, 8)), tmp_path)


def test_overlapping_turns_are_not_clean(tmp_path):
    segs = long_turns("Odete", 0, 6) + [
        IdentifiedSegment(s.start + 1, s.start + 2, "aham", "Vicente", 5.0)
        for s in long_turns("Odete", 0, 6)
    ]
    p = plans_by_person(meeting(segs), tmp_path)["Odete"]
    assert (p.code, p.clean_seconds) == ("too_little_speech", 0)


def test_variant_only_when_recognition_was_weak(tmp_path):
    (tmp_path / "Odete.npy").write_bytes(b"")
    (tmp_path / "Vicente.npy").write_bytes(b"")
    segs = long_turns("Odete", 0, 6) + long_turns("Vicente", 5000, 6)
    m = meeting(segs, labels=[label("Odete", 0.82), label("Vicente", 0.47)])
    plans = plans_by_person(m, tmp_path)
    assert (plans["Odete"].action, plans["Odete"].code) == ("skip", "recognized_well")
    assert (plans["Vicente"].action, plans["Vicente"].target_profile) == (
        "enroll", "Vicente__2026-03-16")


def test_zoom_track_uses_own_file_and_skips_enrolled(tmp_path):
    (tmp_path / "Vicente.npy").write_bytes(b"")
    # Odete's track was named after her phone; she was renamed in review.
    segs = long_turns("Odete", 0, 6, label="Xiaomi") + long_turns("Vicente", 5000, 6, label="Vicente")
    m = meeting(segs, tracks={"Xiaomi": "/z/odete.m4a", "Vicente": "/z/vicente.m4a"})
    plans = plans_by_person(m, tmp_path)
    assert plans["Odete"].action == "enroll"
    assert {c.audio for c in plans["Odete"].clips} == {"/z/odete.m4a"}
    assert plans["Vicente"].code == "already_enrolled"


def test_long_turns_are_cut_into_several_clips(tmp_path):
    # Three 20-second turns: 60 s of clean speech, not 3 x 12 s.
    p = plans_by_person(meeting(long_turns("Odete", 0, 3, each=20.0, gap=40.0)), tmp_path)["Odete"]
    assert (p.action, p.code) == ("enroll", "new_person")
    assert p.clean_seconds == 60.0
    assert all(c.end - c.start <= 12.0 for c in p.clips)
    # Every turn contributes before any turn contributes twice.
    starts = sorted(c.start for c in p.clips)
    assert {0.0, 40.0, 80.0} <= set(starts)
