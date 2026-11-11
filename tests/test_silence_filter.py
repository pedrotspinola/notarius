"""Zoom one-track-per-person: lines Whisper invents over silence are dropped.

Synthetic tracks; the levels follow real meetings: real speech peaks at
-2..-9 dB, the invented lines ("E aí", "Obrigado.", "Tchau.") sit on silence
at -40..-75 dB.
"""

import numpy as np

from notarius.config import IdentifiedSegment, PipelineConfig
from notarius.transcribe import filter_silent_segments

SR = 16000
CFG = PipelineConfig()
DROP, QUIET = CFG.silent_segment_peak_db, CFG.quiet_segment_peak_db


def track(seconds, bursts, seed=0):
    """Noise floor at -75 dB plus tone bursts ``(start, end, peak dB)``."""
    rng = np.random.default_rng(seed)
    a = rng.normal(0, 10 ** (-75 / 20) / 3, int(seconds * SR)).astype(np.float32)
    for s, e, db in bursts:
        n = int((e - s) * SR)
        a[int(s * SR):int(s * SR) + n] = (
            10 ** (db / 20) * np.sin(np.arange(n) * 2 * np.pi * 220 / SR)
        ).astype(np.float32)
    return a


def seg(start, end, text, who="Odete Prado"):
    return IdentifiedSegment(start, end, text, who, 1.0, label=who, origin="track")


def texts(segs):
    return [s.text for s in segs]


def test_defaults():
    assert CFG.drop_silent_segments
    assert (DROP, QUIET, CFG.quiet_track_min_segments) == (-35.0, -20.0, 3)


def test_invented_lines_on_silence_are_dropped_real_ones_kept():
    audio = track(60, [(10, 12, -6), (30, 31, -5), (40, 40.4, -28)])
    segs = [
        seg(10.2, 11.8, "Queria sugerir um encaminhamento."),
        seg(20.0, 21.0, "E aí"),                    # silence
        seg(30.5, 30.5, "É."),                       # zero-length aligned span
        seg(40.0, 40.4, "Tchau."),                   # quiet but audible
        seg(50.0, 55.0, "Obrigado por assistir!"),  # silence
    ]
    kept, events = filter_silent_segments(segs, audio, DROP, QUIET)
    assert texts(kept) == ["Queria sugerir um encaminhamento.", "É.", "Tchau."]
    dropped = [e for e in events if e["action"] == "dropped"]
    assert [e["text"] for e in dropped] == ["E aí", "Obrigado por assistir!"]
    assert all(e["peak_db"] < DROP for e in dropped)
    quiet = [e for e in events if e["action"] == "quiet"]
    assert [e["text"] for e in quiet] == ["Tchau."]
    assert -30 < quiet[0]["peak_db"] < -26


def test_silent_attendee_track_of_only_invented_lines_is_emptied():
    junk = [seg(5, 6, "Tchau.", "Vicente"), seg(20, 21, "E aí", "Vicente"),
            seg(40, 41, "Obrigado.", "Vicente")]
    kept, events = filter_silent_segments(junk, track(60, []), DROP, QUIET)
    assert kept == []
    assert [e["action"] for e in events] == ["dropped"] * 3


def test_one_audible_noise_does_not_shield_the_invented_lines():
    # One line says nothing about the microphone: the invented lines still go.
    lines = [seg(5.0, 5.5, "Tchau.", "Vicente"), seg(20, 21, "E aí", "Vicente"),
             seg(40, 41, "Obrigado.", "Vicente")]
    kept, events = filter_silent_segments(lines, track(60, [(5, 5.5, -27)]), DROP, QUIET)
    assert texts(kept) == ["Tchau."]
    assert [e["action"] for e in events] == ["quiet", "dropped", "dropped"]


def test_weak_microphone_track_is_left_alone():
    weak = track(60, [(10, 12, -28), (20, 22, -29), (30, 32, -27), (45, 46, -38)])
    lines = [seg(10.1, 11.9, "fala real", "Iolanda"), seg(20.1, 21.9, "mais uma", "Iolanda"),
             seg(30.1, 31.9, "outra fala", "Iolanda"),
             seg(45.1, 45.9, "fala bem baixa", "Iolanda"), seg(52, 53, "E aí", "Iolanda")]
    kept, events = filter_silent_segments(lines, weak, DROP, QUIET)
    assert kept == lines
    assert len(events) == 1 and events[0]["action"] == "track_too_quiet"
    assert -30 < events[0]["median_peak_db"] < -25


def test_edges_of_the_track():
    audio = track(10, [(0.0, 0.5, -6)])
    kept, events = filter_silent_segments(
        [seg(0.0, 0.3, "Oi."), seg(9.8, 12.0, "E aí")], audio, DROP, QUIET)
    assert texts(kept) == ["Oi."]
    assert [e["text"] for e in events if e["action"] == "dropped"] == ["E aí"]
