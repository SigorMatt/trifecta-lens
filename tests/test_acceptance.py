"""Task 0.7: the phase done-whens as runnable checks, not prose.

Phase 0:
- ``trifecta-lens --version`` exits 0.
- The worked fixture loads to the expected Event count.

Phase 1 (task 1.9), as promised in 0.7:
- The positive fixture yields exactly one realized finding, with the path.
- The benign fixtures yield none.
- A re-run is byte-identical.

This module is the gate: if it is green, the phase's claims are true. Keep it
readable as a spec — someone should be able to read it and know what we assert.
"""

import io
import subprocess
import sys
from pathlib import Path

from trifecta_lens.engine import FAMILY_TWO_LEG, detect_realized
from trifecta_lens.findings import write_ndjson
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "fixtures"
WORKED_EXAMPLE = FIXTURES / "worked_example.jsonl"
WORKED_EXAMPLE_EVENT_COUNT = 4

ANCHOR = FIXTURES / "demo_realized.jsonl"
BENIGN = (
    FIXTURES / "benign_no_flow.jsonl",
    FIXTURES / "triage_refused_sonnet5.jsonl",
    FIXTURES / "triage_benign_control.jsonl",
)


def _findings_ndjson(path: Path) -> str:
    out = io.StringIO()
    write_ndjson(detect_realized(label_events(load_trace(path))), out)
    return out.getvalue()


# --- Phase 0 ------------------------------------------------------------------


def test_version_exits_zero() -> None:
    console_script = Path(sys.executable).parent / "trifecta-lens"
    result = subprocess.run(
        [str(console_script), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_worked_fixture_loads_to_expected_event_count() -> None:
    events = load_trace(WORKED_EXAMPLE)
    assert len(events) == WORKED_EXAMPLE_EVENT_COUNT


# --- Phase 1 exit -------------------------------------------------------------


def test_positive_fixture_yields_exactly_one_realized_finding_with_the_path() -> None:
    findings = list(detect_realized(label_events(load_trace(ANCHOR))))

    assert len(findings) == 1
    (finding,) = findings
    assert finding.tier == "realized"
    assert finding.family == FAMILY_TWO_LEG
    assert finding.sink_event == "s4"
    assert finding.path == ("s3", "s4")
    assert finding.masked_values == ("sk-demo-...MASKED",)
    assert finding.legs_not_observed == ("untrusted_source",)


def test_benign_fixtures_yield_no_realized_finding() -> None:
    for path in BENIGN:
        assert _findings_ndjson(path) == "", path.name


def test_rerun_is_byte_identical() -> None:
    assert _findings_ndjson(ANCHOR) == _findings_ndjson(ANCHOR)
