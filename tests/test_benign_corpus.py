"""Task 3.7: the benign corpus makes "low false-positive noise" a MEASURED claim.

`CLAUDE.md`: benign fixtures that must produce *no realized finding* are as
important as malicious ones. This module turns "low FP noise" from an assertion
into a number: **N benign traces, 0 realized false positives at the shipped
extraction config** — and, more importantly, makes each silence *load-bearing*.

A corpus of traces that are silent because they never call a labeled tool proves
almost nothing (a broken detector would pass it too). So every fixture here is
silent for a **named, falsifiable** reason, and the per-mechanism tests assert
that the legs which *would* make it fire are present — so the silence can only
come from the guard the fixture is built to exercise, never from an accident of
labeling. This is the discipline `benign_no_flow` established (its docstring in
`FIXTURES_PROVENANCE.md`), applied across a wider surface.

`test_extraction_config.py` answers a different question — *why the threshold is
8* — with the collision fixture. This module answers *how broadly the detector
stays quiet on realistic benign traffic*.
"""

from __future__ import annotations

from pathlib import Path

from trifecta_lens.engine import detect_realized
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace
from trifecta_lens.roles import SENSITIVE_DATA, SINK_EXFIL, UNTRUSTED_SOURCE
from trifecta_lens.taint import value_in_payload

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SECRET = "sk-demo-trifecta-lens-DO-NOT-USE-0000"

#: The benign corpus: a trace where **no verbatim secret reached an outbound
#: sink**, paired with the reason its silence is load-bearing. Extend this list
#: as new realistic FP-bait shapes are found — that is exactly how the FP claim
#: earns breadth over time.
BENIGN_CORPUS: dict[str, str] = {
    "benign_no_flow.jsonl":
        "both legs labeled; secret never posted (verbatim guard)",
    "benign_short_value_collision.jsonl":
        "a 4-char vault value collides with sink text (min_value_chars)",
    "benign_redacted_secret.jsonl":
        "the agent posts a redacted prefix, not the verbatim secret",
    "benign_secret_to_nonsink.jsonl":
        "secret threaded verbatim, but to a tool that carries no sink role",
    "benign_lookalike_not_the_secret.jsonl":
        "a different high-entropy token at the sink, not THE secret",
    "benign_source_echo_no_secret.jsonl":
        "untrusted content reaches the sink, but no sensitive leg exists",
    "triage_refused_sonnet5.jsonl":
        "captured refusal: no vault/webhook call at all",
    "triage_benign_control.jsonl":
        "captured control: injection absent by construction",
}


def _events(name: str):  # type: ignore[no-untyped-def]
    return list(label_events(load_trace(FIXTURES / name)))


def _roles_present(name: str) -> set[str]:
    present: set[str] = set()
    for event in _events(name):
        present |= event.roles
    return present


# --- the measured claim -----------------------------------------------------


def test_the_whole_benign_corpus_yields_zero_realized_false_positives() -> None:
    """N benign traces, 0 realized findings, at the SHIPPED config. The number."""
    total = 0
    per_fixture: dict[str, int] = {}
    for name in BENIGN_CORPUS:
        count = len(list(detect_realized(_events(name))))
        per_fixture[name] = count
        total += count
    assert total == 0, f"benign corpus produced false positives: {per_fixture}"
    # Guard against the corpus quietly shrinking to nothing meaningful.
    assert len(BENIGN_CORPUS) >= 8


def test_every_benign_fixture_exists_and_parses() -> None:
    for name in BENIGN_CORPUS:
        assert (FIXTURES / name).exists(), name
        assert _events(name), f"{name} produced no events"


# --- each silence is load-bearing, per mechanism ----------------------------


def test_redaction_is_silent_though_both_legs_are_present() -> None:
    """Silence here must come from the verbatim guard, not from missing legs."""
    present = _roles_present("benign_redacted_secret.jsonl")
    assert SENSITIVE_DATA in present and SINK_EXFIL in present
    assert list(detect_realized(_events("benign_redacted_secret.jsonl"))) == []


def test_a_verbatim_secret_at_a_NON_sink_is_silent() -> None:
    """The sink label is load-bearing: the value flows verbatim, but not to a sink.

    If this ever fires, either the value stopped reaching the scratchpad or the
    catalog started labeling the scratchpad a sink — both worth knowing.
    """
    events = _events("benign_secret_to_nonsink.jsonl")
    pad = next(e for e in events if e.tool == "scratchpad")
    assert value_in_payload(SECRET, pad.inputs), "value must reach the scratchpad"
    assert SINK_EXFIL not in pad.roles, "scratchpad must not be a sink"
    assert list(detect_realized(events)) == []


def test_a_secret_lookalike_at_the_sink_is_silent() -> None:
    """A high-entropy token that is not THE secret is not reported as a leak."""
    present = _roles_present("benign_lookalike_not_the_secret.jsonl")
    assert SENSITIVE_DATA in present and SINK_EXFIL in present
    assert list(detect_realized(_events("benign_lookalike_not_the_secret.jsonl"))) == []


def test_untrusted_source_to_sink_without_a_secret_is_silent() -> None:
    """The family requires the sensitive leg: source -> sink alone does not fire."""
    present = _roles_present("benign_source_echo_no_secret.jsonl")
    assert UNTRUSTED_SOURCE in present and SINK_EXFIL in present
    assert SENSITIVE_DATA not in present, "this fixture must have NO sensitive leg"
    assert list(detect_realized(_events("benign_source_echo_no_secret.jsonl"))) == []
