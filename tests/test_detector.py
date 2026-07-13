"""Task 1.6 — the realized detector, and the acceptance gate for the whole slice.

On fixtures/demo_realized.jsonl the detector must emit:

  - EXACTLY ONE realized finding, family `sensitive_to_exfil_sink`, on sink s4,
    path ending s3 -> s4, secret masked, legs_observed
    = [sensitive_data, sink:exfil], legs_not_observed = [untrusted_source],
    and a note saying this is NOT a trifecta finding.
  - ZERO findings on s2 (the placeholder body — the guard must fail there).
  - ZERO trifecta-family findings anywhere on this anchor.

On BOTH triage fixtures it must emit ZERO realized findings.

Findings serialize as NDJSON: one object per line, sort_keys=True, emitted as
found (DESIGN.md §6) — never a monolithic end-of-run document.
"""

import io
import json
from pathlib import Path

from trifecta_lens.engine import FAMILY_TRIFECTA, FAMILY_TWO_LEG, detect_realized
from trifecta_lens.findings import write_ndjson
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace
from trifecta_lens.roles import SENSITIVE_DATA, SINK_EXFIL, UNTRUSTED_SOURCE

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
ANCHOR = FIXTURES / "demo_realized.jsonl"
TRIAGE_REFUSED = FIXTURES / "triage_refused_sonnet5.jsonl"
TRIAGE_BENIGN = FIXTURES / "triage_benign_control.jsonl"

SECRET = "sk-demo-trifecta-lens-DO-NOT-USE-0000"


def _findings(path: Path) -> list[dict[str, object]]:
    events = label_events(load_trace(path))
    return [f.to_dict() for f in detect_realized(events)]


# --- the acceptance gate -----------------------------------------------------


def test_anchor_emits_exactly_one_realized_finding_on_s4() -> None:
    findings = _findings(ANCHOR)

    assert len(findings) == 1
    (finding,) = findings

    assert finding["tier"] == "realized"
    assert finding["family"] == FAMILY_TWO_LEG
    assert finding["sink"] == {"event": "s4", "tool": "webhook"}
    assert finding["path"] == ["s3", "s4"]


def test_anchor_finding_names_the_missing_source_leg() -> None:
    (finding,) = _findings(ANCHOR)

    assert finding["legs_observed"] == [SENSITIVE_DATA, SINK_EXFIL]
    assert finding["legs_not_observed"] == [UNTRUSTED_SOURCE]

    note = str(finding["note"])
    assert UNTRUSTED_SOURCE in note
    assert "not observed" in note
    assert "not a trifecta finding" in note


def test_anchor_emits_no_trifecta_finding() -> None:
    assert all(f["family"] != FAMILY_TRIFECTA for f in _findings(ANCHOR))


def test_anchor_emits_nothing_on_the_placeholder_sink_s2() -> None:
    """s2 posted "<vault_output>", not the secret: the verbatim guard must fail."""
    s2_sink = {"event": "s2", "tool": "webhook"}
    assert all(f["sink"] != s2_sink for f in _findings(ANCHOR))


def test_realized_stays_silent_on_both_triage_fixtures() -> None:
    assert _findings(TRIAGE_REFUSED) == []
    assert _findings(TRIAGE_BENIGN) == []


# --- the trifecta family is live, not dead code ------------------------------


def test_trifecta_fires_when_the_source_leg_is_genuinely_present() -> None:
    """The two families are separated by the DATA, not by a hardcoded choice.

    worked_example.jsonl is the hand-authored FORMAT fixture (FIXTURES.md), not a
    captured run — it must never be presented as evidence of a real flow. Its job
    here is to prove the trifecta's accepting path is exercised: it has a real
    untrusted-source leg (a URL fetch returning a poisoned page), so the SAME
    machine that reports two-leg on the anchor reports the trifecta here.
    """
    (finding,) = _findings(FIXTURES / "worked_example.jsonl")

    assert finding["family"] == FAMILY_TRIFECTA
    assert finding["path"] == ["s1", "s2", "s3"]  # fetch -> vault -> webhook
    assert finding["legs_observed"] == [UNTRUSTED_SOURCE, SENSITIVE_DATA, SINK_EXFIL]
    assert finding["legs_not_observed"] == []
    assert finding["summary"] == "tainted data observed reaching webhook"


# --- honesty of the emitted text ---------------------------------------------


def test_summary_is_the_fixed_flow_not_causation_line() -> None:
    (finding,) = _findings(ANCHOR)
    assert finding["summary"] == "tainted data observed reaching webhook"


def test_finding_masks_the_secret_and_never_carries_it() -> None:
    (finding,) = _findings(ANCHOR)
    assert finding["masked_values"] == ["sk-demo-...MASKED"]
    assert SECRET not in json.dumps(finding)


def test_finding_states_the_verbatim_only_scope() -> None:
    (finding,) = _findings(ANCHOR)
    assert "verbatim" in str(finding["scope"]).lower()


def test_finding_cites_why_each_role_was_assigned() -> None:
    """SPEC.md §4: every finding cites what assigned each role — the rationale AND
    the catalog entry id, so a user can both judge the call and go change it."""
    (finding,) = _findings(ANCHOR)
    legs = finding["legs"]
    # `agent` is the AGENT span each leg ran under (D15). Both legs here ran under the
    # SAME agent — this anchor is a single-agent run — so the finding does not claim a
    # crossing. That is checked explicitly below, because a false "crosses agents" would
    # be a bigger overclaim than the one it fixes.
    assert legs == [
        {
            "agent": "s0",
            "catalog_entry": "vault.secret",
            "event": "s3",
            "note": "reads a credential from the secret store",
            "role": SENSITIVE_DATA,
            "tool": "vault",
        },
        {
            "agent": "s0",
            "catalog_entry": "webhook.post",
            "event": "s4",
            "note": "sends a payload to an outbound HTTP endpoint",
            "role": SINK_EXFIL,
            "tool": "webhook",
        },
    ]
    assert finding["agents"] == ["s0"]
    assert finding["crosses_agents"] is False


# --- NDJSON append-stream (DESIGN.md §6) -------------------------------------


def test_findings_serialize_as_ndjson_one_object_per_line_sorted_keys() -> None:
    events = label_events(load_trace(ANCHOR))
    out = io.StringIO()
    count = write_ndjson(detect_realized(events), out)

    lines = out.getvalue().splitlines()
    assert count == len(lines) == 1
    for line in lines:
        parsed = json.loads(line)
        # keys sorted: re-serializing with sort_keys must reproduce the line
        assert json.dumps(parsed, sort_keys=True) == line


def test_engine_is_an_incremental_fold_not_a_backward_pass() -> None:
    """DESIGN.md §6: the engine consumes events one at a time and never requires
    the complete trace as a precondition. Feeding it a prefix must yield the
    findings derivable from that prefix — no retraction, no lookahead."""
    events = label_events(load_trace(ANCHOR))

    # Prefix ending BEFORE the tainted sink: nothing is derivable yet.
    assert list(detect_realized(events[:4])) == []

    # The same fold over the full trace emits the finding when it reaches s4,
    # and the prefix's (empty) result is a prefix of the full result.
    assert len(list(detect_realized(events))) == 1
