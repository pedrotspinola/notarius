"""The meeting record: attendance, rendering, JSON round trip."""

from notarius.config import IdentifiedSegment
from notarius.meeting import ChatMessage, Meeting, build_attendees, merge_consecutive


def seg(start, end, name, text="x", label="SPEAKER_00", origin="label"):
    return IdentifiedSegment(start, end, text, name, 4.0, label=label, origin=origin)


SEGMENTS = [
    seg(0, 2, "Odete Prado", "Bom dia."),
    seg(2.5, 4, "Odete Prado", "Vamos começar."),
    seg(5, 8, "Desconhecido 1", "Oi.", label="SPEAKER_01"),
    seg(9, 12, "Vicente", "Tudo bem?", label="SPEAKER_02"),
]


def test_attendance_lists_speakers_then_silent_and_skips_unknowns():
    attendees = build_attendees(SEGMENTS, ["vicente", "Iolanda"])
    assert [(a.name, a.spoke, a.segments) for a in attendees] == [
        ("Iolanda", False, 0),
        ("Odete Prado", True, 2),
        ("Vicente", True, 1),
    ]


def test_merge_joins_close_segments_of_same_speaker():
    merged = merge_consecutive(SEGMENTS)
    assert [m.speaker_name for m in merged] == ["Odete Prado", "Desconhecido 1", "Vicente"]
    assert merged[0].text == "Bom dia. Vamos começar."
    assert (merged[0].start, merged[0].end) == (0, 4)


def test_render_text():
    m = Meeting("Reunião", "file", "/x.mkv", SEGMENTS, listed_attendees=["Iolanda"],
                chat=[ChatMessage("00:00:10", "Vicente", "link\naqui")])
    text = m.render_text()
    assert text.splitlines()[:2] == ["Presentes: Odete Prado, Vicente, Iolanda*", "(* não falou)"]
    assert "Odete Prado [00:00:00]: Bom dia. Vamos começar." in text
    assert "Desconhecido 1 [00:00:05]: Oi." in text
    assert text.rstrip().endswith("Vicente [00:00:10]: link\n    aqui")


def test_json_round_trip(tmp_path):
    m = Meeting("Reunião", "zoom", "/pasta", SEGMENTS, date="2026-03-16_11-00-31",
                tracks={"Vicente": "/pasta/v.m4a"}, events=[{"index": 2, "kind": "possible"}])
    txt = m.save(tmp_path / "r.json")
    assert txt.read_text(encoding="utf-8") == m.render_text()
    loaded = Meeting.load(tmp_path / "r.json")
    assert loaded.segments == m.segments
    assert loaded.tracks == m.tracks and loaded.events == m.events
    assert loaded.date == m.date and loaded.render_text() == m.render_text()
