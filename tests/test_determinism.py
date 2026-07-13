"""Task 1.9: benign fixtures + determinism.

Determinism is a correctness requirement, not a nicety (CLAUDE.md): same inputs
-> same findings, byte-for-byte. It is what makes findings diffable in CI and
makes a claim auditable by re-running it. Asserted at two levels: the in-process
fold, and the actual CLI writing actual files.

The benign matrix is as important as the positive. A detector that fires on
everything is not a detector, so each benign fixture is silent for a DIFFERENT
reason, and the reasons are named here.
"""

import io
import subprocess
import sys
from pathlib import Path

from trifecta_lens.engine import detect_realized
from trifecta_lens.findings import write_ndjson
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace
from trifecta_lens.svg import render_svg

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "fixtures"
ANCHOR = FIXTURES / "demo_realized.jsonl"

SECRET = "sk-demo-trifecta-lens-DO-NOT-USE-0000"


def _ndjson(path: Path) -> str:
    out = io.StringIO()
    write_ndjson(detect_realized(label_events(load_trace(path))), out)
    return out.getvalue()


# --- the benign matrix: silent, each for a different reason -------------------


def test_benign_no_flow_is_silent_because_the_guard_failed() -> None:
    """The load-bearing benign case.

    Both legs are present AND labeled — vault (sensitive_data) and webhook
    (sink:exfil) are both called. So silence here cannot be an artifact of the
    labeling; it can only be the verbatim guard failing, because the secret was
    never posted. This is the low-false-positive claim, made falsifiable.
    """
    events = label_events(load_trace(FIXTURES / "benign_no_flow.jsonl"))

    roles = {r for e in events for r in e.roles}
    assert roles == {"sensitive_data", "sink:exfil"}  # the legs really are there

    assert list(detect_realized(events)) == []


def test_triage_fixtures_are_silent_because_the_SENSITIVE_LEG_is_absent() -> None:
    """The two captured triage runs never call the vault, so nothing is tainted.

    triage_refused: the model was given a poisoned issue and declined the
    injected vault/POST step. triage_benign_control: no injection at all.

    Task 2.13 STRENGTHENED this case. Under the Phase-1 table these fixtures called
    no labeled tool at all, so their silence proved little — an unlabeled stack is
    silent about everything. The default catalog now covers what they really do:
    they read ISSUE TEXT (an untrusted_source — third parties write it) and they
    POST A COMMENT (a sink:exfil — a public issue thread is a shared location).

    So they now carry two of the three legs, and they are *still* silent. That
    silence is now load-bearing: it can only come from the machine requiring a
    SENSITIVE leg before it will call anything exfil (SPEC.md §3). A source reaching
    a sink with nothing sensitive in the path is not an exfil finding at any
    strength — it is the action-hijack family's territory, and v1 does not ship it.
    """
    for name in ("triage_refused_sonnet5.jsonl", "triage_benign_control.jsonl"):
        events = label_events(load_trace(FIXTURES / name))

        roles = {r for e in events for r in e.roles}
        assert roles == {"untrusted_source", "sink:exfil"}, name
        assert "sensitive_data" not in roles, name

        assert list(detect_realized(events)) == [], name


def test_the_fixture_corpus_census_is_pinned() -> None:
    counts = {
        path.name: len(list(detect_realized(label_events(load_trace(path)))))
        for path in sorted(FIXTURES.glob("*.jsonl"))
    }
    assert counts == {
        "benign_no_flow.jsonl": 0,
        # the task 3.7 benign corpus: each silent for a distinct, load-bearing
        # reason (tests/test_benign_corpus.py names them). All 0.
        "benign_lookalike_not_the_secret.jsonl": 0,
        "benign_redacted_secret.jsonl": 0,
        "benign_secret_to_nonsink.jsonl": 0,
        # silent because the 4-char value is below min_value_chars: a short
        # string colliding with payload text is noise, not a flow (SPEC.md §6.1)
        "benign_short_value_collision.jsonl": 0,
        "benign_source_echo_no_secret.jsonl": 0,
        # hand-authored: real parent_id ancestry through the tools, so its
        # finding reads path_basis=causal rather than temporal (SPEC.md §5)
        "causal_chain.jsonl": 1,
        # hand-authored (D15): a secret read by one sub-agent and emailed out by
        # ANOTHER, in one trace. It fires — and always has, because the engine folds
        # one taint set with no notion of an agent. The finding now names the agents
        # it crossed; before D15 it printed as though one agent did both, while
        # SPEC.md §8 denied the capability outright.
        "cross_agent_handoff.jsonl": 1,
        "demo_realized.jsonl": 1,
        "triage_benign_control.jsonl": 0,
        "triage_refused_sonnet5.jsonl": 0,
        "worked_example.jsonl": 1,  # hand-authored: the trifecta's accepting path
    }


# --- determinism --------------------------------------------------------------


def test_findings_are_byte_identical_across_runs() -> None:
    first = _ndjson(ANCHOR)
    assert first == _ndjson(ANCHOR) == _ndjson(ANCHOR)
    assert first.count("\n") == 1


def test_svg_is_byte_identical_across_runs() -> None:
    def svg() -> str:
        (finding,) = detect_realized(label_events(load_trace(ANCHOR)))
        return render_svg(finding)

    assert svg() == svg()


def test_cli_writes_byte_identical_files_across_runs(tmp_path: Path) -> None:
    """End-to-end: the real console script, writing real files, twice."""

    def run(tag: str) -> tuple[bytes, bytes, str]:
        findings = tmp_path / f"{tag}.ndjson"
        svg = tmp_path / f"{tag}.svg"
        result = subprocess.run(
            [
                str(Path(sys.executable).parent / "trifecta-lens"),
                "--trace",
                str(ANCHOR),
                "--findings",
                str(findings),
                "--svg",
                str(svg),
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        )
        return findings.read_bytes(), svg.read_bytes(), result.stdout

    first_findings, first_svg, first_report = run("a")
    second_findings, second_svg, second_report = run("b")

    assert first_findings == second_findings
    assert first_svg == second_svg
    assert first_report == second_report

    # And the raw secret never reaches any output surface.
    assert SECRET.encode() not in first_findings
    assert SECRET.encode() not in first_svg
    assert SECRET not in first_report
