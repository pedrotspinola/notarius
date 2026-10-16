"""Review items for a new user (no voices enrolled yet)."""

from notarius.config import IdentifiedSegment, TranscriptionSegment
from notarius.meeting import Meeting
from notarius.review import apply_answers, build_review


def seg(start, end, name, label, text="fala"):
    return IdentifiedSegment(start, end, text, name, -1.0, label=label)


def test_unknown_voices_are_asked_even_without_label_diagnostics(tmp_path):
    m = Meeting("Reunião", "file", "/r.mkv", [
        seg(0, 8, "Desconhecido 1", "SPEAKER_00", "Bom dia, meu nome é Odete."),
        seg(9, 15, "Desconhecido 2", "SPEAKER_01", "Pode falar, Vicente."),
        seg(16, 30, "Desconhecido 1", "SPEAKER_00"),
    ])
    items = build_review(m, tmp_path)
    assert [(i.kind, i.current) for i in items] == [
        ("unknown", "Desconhecido 1"), ("unknown", "Desconhecido 2")]
    assert items[0].suggestions[0].name == "Odete"  # self-introduction
    apply_answers(m, {items[0].id: "Odete"})
    assert [s.speaker_name for s in m.segments] == ["Odete", "Desconhecido 2", "Odete"]
    assert [i.current for i in build_review(m, tmp_path)] == ["Desconhecido 2"]


def test_identify_reports_labels_when_nobody_is_enrolled(tmp_path):
    from notarius.config import PipelineConfig
    from notarius.identify import identify_speakers

    segments = [TranscriptionSegment(0, 5, "a", "SPEAKER_00"),
                TranscriptionSegment(5, 7, "b", "SPEAKER_01"),
                TranscriptionSegment(7, 9, "c", "SPEAKER_00")]
    identified, matches = identify_speakers(
        segments, "unused.wav", PipelineConfig(profiles_dir=tmp_path))
    assert [s.speaker_name for s in identified] == ["Desconhecido 1", "Desconhecido 2", "Desconhecido 1"]
    assert [(m.label, m.assigned, m.n_segments, m.display) for m in matches] == [
        ("SPEAKER_00", None, 2, "Desconhecido 1"), ("SPEAKER_01", None, 1, "Desconhecido 2")]
