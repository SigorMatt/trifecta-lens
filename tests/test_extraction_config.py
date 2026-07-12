"""Task 2.1: containment (D3) + disclosed extraction parameters (D4).

SPEC.md §6/§6.1. Two things are under test, and they are deliberately in ONE
module because they set the false-positive rate *together*:

1. **Containment** — a value matches when it OCCURS in a sink payload string,
   untransformed. "Verbatim" constrains transformation of the *value*, not the
   surrounding body. Whole-field equality is the strictly weaker special case.

2. **Disclosure** — the parameters that bound what realized can see
   (`min_value_chars`, `match`, `normalization`) are carried in every finding's
   `detected_under` and stated in the report. An undisclosed threshold makes
   "no finding" un-auditable, which is the same honesty failure as an overclaim,
   pointed the other way.

The `min_value_chars = 8` constant is justified by a MEASURED false-positive
rate over the benign corpus (see the last test) — a number, not an assertion.
"""

import json
from itertools import pairwise
from pathlib import Path

from trifecta_lens.engine import detect_realized
from trifecta_lens.extraction import EXTRACTION, ExtractionConfig
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace
from trifecta_lens.report import format_report
from trifecta_lens.taint import value_in_payload

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
ANCHOR = FIXTURES / "demo_realized.jsonl"
SECRET = "sk-demo-trifecta-lens-DO-NOT-USE-0000"

BENIGN = (
    "benign_no_flow.jsonl",
    "benign_short_value_collision.jsonl",
    "triage_refused_sonnet5.jsonl",
    "triage_benign_control.jsonl",
)
POSITIVE = ("demo_realized.jsonl", "worked_example.jsonl")


# --- containment (D3) ---------------------------------------------------------


def test_value_matches_when_embedded_in_a_larger_body() -> None:
    """The common real case: a secret pasted into a bigger payload."""
    assert value_in_payload(SECRET, {"body": f"key={SECRET}"}) is True
    assert value_in_payload(SECRET, {"body": f"Authorization: Bearer {SECRET}"}) is True
    assert value_in_payload(SECRET, {"body": json.dumps({"k": SECRET})}) is True


def test_whole_field_equality_still_matches() -> None:
    """Equality is the weaker special case of containment, not a rival rule."""
    assert value_in_payload(SECRET, {"body": SECRET}) is True


def test_transformed_values_still_do_not_match() -> None:
    """Containment widens the payload, NOT the value. v1 stays verbatim-only."""
    import base64

    encoded = base64.b64encode(SECRET.encode()).decode()
    assert value_in_payload(SECRET, {"body": encoded}) is False
    assert value_in_payload(SECRET, {"body": SECRET[:18] + " " + SECRET[18:]}) is False
    assert value_in_payload(SECRET, {"body": "the key from the vault"}) is False


# --- disclosure (D4) ----------------------------------------------------------


def test_extraction_config_declares_the_v1_parameters() -> None:
    assert EXTRACTION.min_value_chars == 8
    assert EXTRACTION.match == "containment"
    assert EXTRACTION.normalization == ("trim", "casefold", "collapse-whitespace")


def test_every_finding_discloses_what_bounded_the_search() -> None:
    (finding,) = detect_realized(label_events(load_trace(ANCHOR)))
    disclosed = finding.to_dict()["detected_under"]

    assert disclosed == {
        "match": "containment",
        "min_value_chars": 8,
        "normalization": ["trim", "casefold", "collapse-whitespace"],
    }


def test_report_states_the_parameters() -> None:
    events = label_events(load_trace(ANCHOR))
    text = format_report(list(detect_realized(events)), events)
    assert "min_value_chars=8" in text
    assert "containment" in text


def test_a_silent_report_also_states_them() -> None:
    """Most important case: 'no finding' is only auditable if you know the bounds."""
    events = label_events(load_trace(FIXTURES / "benign_no_flow.jsonl"))
    text = format_report(list(detect_realized(events)), events)
    assert "no realized findings" in text.lower()
    assert "min_value_chars=8" in text


def test_below_threshold_values_are_not_tracked() -> None:
    assert value_in_payload("abc", {"body": "abc"}) is False  # 3 chars: under 8
    assert value_in_payload("abcdefgh", {"body": "xx abcdefgh xx"}) is True  # 8: at


# --- the measured justification for min_value_chars = 8 -----------------------


def _sweep(names: tuple[str, ...]) -> dict[int, int]:
    """Findings emitted over ``names`` at each candidate threshold."""
    out: dict[int, int] = {}
    for threshold in (1, 2, 3, 4, 5, 6, 8, 12, 16, 24, 40):
        config = ExtractionConfig(min_value_chars=threshold)
        total = 0
        for name in names:
            events = label_events(load_trace(FIXTURES / name))
            total += len(list(detect_realized(events, config=config)))
        out[threshold] = total
    return out


def test_min_value_chars_is_justified_by_a_measured_false_positive_rate() -> None:
    """The constant is MEASURED, not asserted (SPEC.md §6.1).

    Sweeping the threshold over the corpus produces this curve:

        min_value_chars | benign FPs | true positives
        ----------------+------------+---------------
                     <=4|          1 |             2     <- collision admitted
                    5-16|          0 |             2     <- SAFE WINDOW
                      24|          0 |             1     <- true positive dying
                      40|          0 |             0

    The shipped value 8 sits in the middle of the safe window: clear of the
    collision floor (>=5) with margin, and far below where real findings start
    disappearing (24). A future change to the constant has to confront this
    curve rather than re-litigate a vibe.
    """
    false_positives = _sweep(BENIGN)
    true_positives = _sweep(POSITIVE)

    # The threshold EARNS its place: without it, the short-value collision in
    # benign_short_value_collision.jsonl is reported as a flow.
    assert false_positives[4] > 0, "the threshold must actually be doing work"

    # The shipped value: silent on the benign corpus, and it costs no real finding.
    assert false_positives[8] == 0, false_positives
    assert true_positives[8] == len(POSITIVE), true_positives

    # The safe window is real, and 8 is inside it -- not perched on its edge.
    safe = [
        t
        for t in false_positives
        if false_positives[t] == 0 and true_positives[t] == len(POSITIVE)
    ]
    assert 8 in safe
    assert min(safe) < 8 < max(safe), f"8 should have margin on both sides: {safe}"

    # Monotone in both directions: raising the threshold can only ever admit
    # fewer values, so it can only ever lose findings, never gain them.
    thresholds = sorted(false_positives)
    for lower, higher in pairwise(thresholds):
        assert false_positives[lower] >= false_positives[higher], false_positives
        assert true_positives[lower] >= true_positives[higher], true_positives


def test_the_collision_fixture_is_reported_at_a_naive_threshold() -> None:
    """Names precisely what the threshold protects against.

    benign_short_value_collision: a vault read returns "4242" (a retention
    window), and the webhook body happens to contain "4242" (a record count).
    The value did NOT flow to the sink -- a 4-character string simply collides
    with ordinary payload text. That is noise, not evidence, and it is exactly
    what a naive threshold would report as a leak.
    """
    events = label_events(load_trace(FIXTURES / "benign_short_value_collision.jsonl"))

    naive = list(detect_realized(events, config=ExtractionConfig(min_value_chars=1)))
    assert len(naive) == 1  # the collision, misreported as a flow

    shipped = list(detect_realized(events, config=EXTRACTION))
    assert shipped == []  # correctly silent
