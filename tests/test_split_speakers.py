"""Splitting WhisperX segments where the speaker changes.

Reproduced on Windows and locally: Whisper made one segment from 1.0 to
29.5 s across a change of speaker at 20 s, and the first 8.9 s of the
second person's turn were credited to the first.
"""

from notarius.transcribe import split_at_speaker_changes


def w(word, start, end, speaker=None):
    d = {"word": word, "start": start, "end": end}
    if speaker:
        d["speaker"] = speaker
    return d


def seg(words, speaker="A"):
    return {"start": words[0]["start"], "end": words[-1]["end"], "speaker": speaker,
            "text": " ".join(x["word"] for x in words), "words": words}


def labels(out):
    return [(s.speaker_label, s.text, s.start, s.end) for s in out]


def test_a_segment_across_a_speaker_change_is_split():
    out = split_at_speaker_changes([seg([
        w("então", 0.0, 0.5, "A"), w("vamos", 0.6, 1.0, "A"), w("começar", 1.1, 1.8, "A"),
        w("eu", 2.4, 2.6, "B"), w("concordo", 2.7, 3.3, "B"), w("plenamente", 3.4, 4.2, "B"),
    ])])
    assert labels(out) == [("A", "então vamos começar", 0.0, 1.8),
                           ("B", "eu concordo plenamente", 2.4, 4.2)]


def test_one_stray_word_does_not_split_a_sentence():
    out = split_at_speaker_changes([seg([
        w("a", 0.0, 0.2, "A"), w("gente", 0.3, 0.6, "A"), w("pode", 0.7, 0.9, "B"),
        w("ir", 1.0, 1.1, "A"), w("conversando", 1.2, 1.9, "A"),
    ])])
    assert labels(out) == [("A", "a gente pode ir conversando", 0.0, 1.9)]


def test_a_stray_first_word_joins_the_next_run():
    out = split_at_speaker_changes([seg([
        w("é", 0.0, 0.2, "B"), w("isso", 0.3, 0.6, "A"), w("mesmo", 0.7, 1.0, "A"),
        w("pessoal", 1.1, 1.6, "A"),
    ])])
    assert labels(out) == [("A", "é isso mesmo pessoal", 0.0, 1.6)]


def test_missing_speakers_and_timestamps_are_inherited():
    words = [w("vinte", 0.0, 0.4, "A"), {"word": "2026"}, w("certo", 0.9, 1.2), w("ok", 1.3, 1.5)]
    out = split_at_speaker_changes([seg(words)])
    assert labels(out) == [("A", "vinte 2026 certo ok", 0.0, 1.5)]


def test_segments_without_words_are_kept_whole():
    out = split_at_speaker_changes([{"start": 5.0, "end": 6.0, "text": " oi ", "speaker": "C"},
                                    {"start": 7.0, "end": 8.0, "text": "  "}])
    assert labels(out) == [("C", "oi", 5.0, 6.0)]
