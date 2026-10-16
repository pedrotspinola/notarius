"""Per-segment decision rule, including the attendee gate.

The gate exists because a single segment can score high for someone who
is not in the meeting at all (a person speaking in an unusual tone scored
5.3 for an absent colleague): with an attendee list, renames may only
target people known to be present.
"""

from notarius.config import Candidate
from notarius.identify import verify_decision

HINT = 2.0
ACCEPT = 3.5


def c(name: str, norm: float) -> Candidate:
    return Candidate(name=name, raw=0.5, norm=norm, excess=norm - ACCEPT)


def decide(assigned, scored, allowed=None):
    scored = sorted(scored, key=lambda x: x.excess, reverse=True)
    return verify_decision(assigned, scored, HINT, allowed)


PRESENT = {"Odete Prado", "Vicente", "Iolanda", "Teodoro"}
ABSENT_CASE = [c("Gervásio", 5.26), c("Odete Prado", 1.65)]


def test_absent_person_renames_without_gate():
    kind, new, *_ = decide("Odete Prado", ABSENT_CASE, None)
    assert (kind, new) == ("reassigned", "Gervásio")


def test_absent_person_is_contained_by_gate():
    kind, new, own, best, best_norm = decide("Odete Prado", ABSENT_CASE, PRESENT)
    assert (kind, new) == ("gated", None)
    assert best == "Gervásio" and abs(best_norm - 5.26) < 1e-9
    assert abs(own - 1.65) < 1e-9


def test_present_target_is_not_blocked():
    kind, new, *_ = decide("Odete Prado", [c("Vicente", 5.42), c("Odete Prado", 0.36)], PRESENT)
    assert (kind, new) == ("reassigned", "Vicente")


def test_rescue_of_unknown_label():
    kind, new, own, *_ = decide(None, [c("Gervásio", 4.0)], PRESENT)
    assert (kind, new, own) == ("gated", None, None)
    kind, new, *_ = decide(None, [c("Teodoro", 6.88)], PRESENT)
    assert (kind, new) == ("reassigned", "Teodoro")


def test_gate_leaves_other_kinds_alone():
    assert decide("Vicente", [c("Vicente", 6.0), c("Teodoro", 1.0)], PRESENT)[0] == "verified"
    assert decide("Odete Prado", [c("Gervásio", 4.5), c("Odete Prado", 3.0)], PRESENT)[0] == "suspect"
    assert decide("Vicente", [c("Vicente", 0.5), c("Teodoro", 1.2)], PRESENT)[0] == "flagged"
    assert decide(None, [c("Gervásio", 2.5)], PRESENT)[0] == "possible"
    assert decide(None, [c("Gervásio", 1.0)], PRESENT)[0] == "kept"


def test_never_renames_below_accept():
    # Owner below hint, best other below accept: flagged, not renamed.
    kind, new, *_ = decide("Vicente", [c("Teodoro", 3.4), c("Vicente", 0.1)])
    assert (kind, new) == ("flagged", None)


def test_gate_is_case_insensitive():
    kind, new, *_ = decide(None, [c("iolanda", 4.0)], {"Iolanda", "Vicente"})
    assert (kind, new) == ("reassigned", "iolanda")
    kind, new, *_ = decide("Vicente", [c("Iolanda", 4.2), c("Vicente", 0.3)], {"iolanda", "Vicente"})
    assert (kind, new) == ("reassigned", "Iolanda")
