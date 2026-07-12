"""Task 1.7 done-when: the human report prints the masked verdict for the anchor.

Realized only for the slice (posture/reachable are Phase 2), so the report must
say so rather than implying the other two tiers ran and found nothing.

The things this test guards are honesty properties of the TEXT, not the logic
(CLAUDE.md: invariants 3-5 must hold in the output text):
  - the tier badge is present and says REALIZED
  - the two-leg family is visibly NOT the trifecta
  - the secret is masked, never printed
  - the verbatim-only scope is stated
"""

from pathlib import Path

from trifecta_lens.engine import detect_realized
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace
from trifecta_lens.report import format_report

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
ANCHOR = FIXTURES / "demo_realized.jsonl"
TRIAGE_REFUSED = FIXTURES / "triage_refused_sonnet5.jsonl"

SECRET = "sk-demo-trifecta-lens-DO-NOT-USE-0000"


def _report(path: Path) -> str:
    events = label_events(load_trace(path))
    return format_report(list(detect_realized(events)), events)


def test_report_prints_the_masked_verdict_for_the_anchor() -> None:
    text = _report(ANCHOR)

    assert "[REALIZED]" in text
    assert "sensitive_to_exfil_sink" in text
    assert "tainted data observed reaching webhook" in text
    assert "s3" in text and "s4" in text
    assert "sk-demo-...MASKED" in text
    assert "1 realized finding" in text


def test_report_never_prints_the_secret() -> None:
    assert SECRET not in _report(ANCHOR)


def test_report_shows_the_two_leg_family_as_not_the_trifecta() -> None:
    text = _report(ANCHOR)
    assert "not the trifecta" in text.lower()
    assert "untrusted_source" in text
    assert "not observed" in text


def test_report_states_that_only_the_realized_tier_ran() -> None:
    """Tier honesty: silence from a tier we did not run is not a clean bill."""
    text = _report(ANCHOR)
    assert "realized" in text.lower()
    assert "posture" in text.lower() and "reachable" in text.lower()


def test_report_states_the_verbatim_only_scope() -> None:
    assert "verbatim" in _report(ANCHOR).lower()


def test_report_on_a_silent_trace_says_no_finding_without_claiming_safety() -> None:
    text = _report(TRIAGE_REFUSED)
    assert "no realized findings" in text.lower()
    # Absence of a finding is not evidence of absence of a flow — say so.
    assert "verbatim" in text.lower()
    assert "[REALIZED]" not in text


def test_report_degrades_honestly_without_payloads() -> None:
    """CLAUDE.md: no payload-level content -> realized is UNAVAILABLE, not empty."""
    from dataclasses import replace

    events = label_events(load_trace(ANCHOR))
    stripped = [replace(e, inputs=None, outputs=None) for e in events]

    text = format_report(list(detect_realized(stripped)), stripped)
    assert "UNAVAILABLE" in text
    assert "no realized findings" not in text.lower()
