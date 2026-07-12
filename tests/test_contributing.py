"""Task 3.5: CONTRIBUTING.md's contribution path is EXECUTED, not just described.

The pitch of this project to a contributor is a strong claim — *cover your own
stack by editing a data file, not our code* — and 2.13 proved the claim holds
(``test_A_STRANGERS_SERVER_IS_COVERED_BY_EDITING_DATA_NOT_CODE``). But a
contributor never runs our test suite before deciding whether to bother; they
copy the YAML out of ``CONTRIBUTING.md``. So the doc is the interface, and a doc
that drifts from the parser is worse than no doc: it makes the one advertised
path fail on first contact, for the one person who was willing to walk it.

Hence: every YAML example in ``CONTRIBUTING.md`` is parsed by the REAL catalog
parser, the overlay it shows is run through the REAL labeling function, and the
finding-citation format it prints is compared against what the REAL report emits.
The doc cannot rot without this file going red.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.test_gates import banned_tokens_in
from trifecta_lens.catalog import Catalog, default_catalog, parse_catalog
from trifecta_lens.engine import detect_realized
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_otlp_trace
from trifecta_lens.report import TierResults, format_report
from trifecta_lens.roles import SENSITIVE_DATA, SINK_EXFIL

REPO = Path(__file__).resolve().parent.parent
CONTRIBUTING = REPO / "CONTRIBUTING.md"


def _text() -> str:
    return CONTRIBUTING.read_text(encoding="utf-8")


def _yaml_blocks() -> list[str]:
    blocks = re.findall(r"^```yaml\n(.*?)^```", _text(), flags=re.M | re.S)
    assert blocks, "CONTRIBUTING.md advertises the catalog path but shows no YAML"
    return blocks


def test_every_yaml_example_in_contributing_parses_with_the_real_parser() -> None:
    """Copy-paste must work. The examples go through ``parse_catalog``, not a mock.

    ``parse_catalog`` is strict on purpose (a malformed entry is an error, never a
    silently-skipped line), which is exactly why a stale example in the doc would
    hand a first-time contributor a hard failure instead of a finding.
    """
    for i, block in enumerate(_yaml_blocks()):
        catalog = parse_catalog(block, source=f"CONTRIBUTING.md: yaml block {i}")
        assert catalog.entries, f"yaml block {i} declares no entries"


def _documented_overlay() -> Catalog:
    """The overlay example the doc tells a stranger to copy."""
    for block in _yaml_blocks():
        catalog = parse_catalog(block, source="CONTRIBUTING.md")
        if any(e.id.startswith("acme.") for e in catalog.entries):
            return catalog
    pytest.fail("CONTRIBUTING.md no longer shows the worked overlay example")


def test_the_documented_overlay_labels_the_stack_the_doc_says_it_does() -> None:
    """The doc's worked example, run: unknown stack -> silent; + overlay -> labeled.

    This is 2.13's architectural claim reduced to the two lines a reader will
    actually copy. If someone changes the catalog schema, the roles, or the
    server-qualified naming rule, this fails here — in the doc — rather than in a
    stranger's terminal.
    """
    shipped = default_catalog()
    # A stack this repo has never heard of is invisible under the defaults...
    assert shipped.label("crm__read_customer_rows") == {}
    assert shipped.label("wiki__publish_page") == {}

    # ...and the entire contribution that fixes that is the data in the doc.
    extended = shipped.overlaid_with(_documented_overlay())
    assert SENSITIVE_DATA in extended.label("crm__read_customer_rows")
    assert SINK_EXFIL in extended.label("wiki__publish_page")

    # The overlay is consulted FIRST, so the contributor's note is the one cited —
    # which is what makes "your entries win" in the doc a true statement.
    label = extended.label("crm__read_customer_rows")[SENSITIVE_DATA]
    assert label.entry == "acme.crm.rows"


def test_the_citation_format_in_the_doc_is_the_one_the_report_prints() -> None:
    """The doc promises every finding names the entry to edit. Check the string.

    "Disagreeing with a label" is the flywheel's return path: it only works if the
    id shown in the doc is (a) a real id in the shipped catalog and (b) rendered in
    the shape the doc shows. Both, against the real captured stack.
    """
    doc = _text()
    cited = set(re.findall(r"\[catalog: ([\w.]+)\]", doc))
    assert cited, "the doc no longer shows a finding citing its catalog entry"

    shipped_ids = {e.id for e in default_catalog().entries}
    assert cited <= shipped_ids, (
        f"CONTRIBUTING.md cites unknown entries: {cited - shipped_ids}"
    )

    trace = REPO / "fixtures" / "demo_mcp_trace.otlp.json"
    events = tuple(label_events(load_otlp_trace(trace)))
    report = format_report(
        results=TierResults(events=events, realized=tuple(detect_realized(events)))
    )
    for entry_id in cited:
        assert f"[catalog: {entry_id}]" in report, (
            f"the doc shows `[catalog: {entry_id}]` but no report prints it that way"
        )


def test_every_repo_path_the_doc_points_at_exists() -> None:
    """A contribution guide's links are its load-bearing part."""
    links = re.findall(r"\]\((?!https?://)([^)#]+)", _text())
    assert links, "CONTRIBUTING.md links to nothing in the repo"
    missing = [link for link in links if not (REPO / link).exists()]
    assert not missing, f"CONTRIBUTING.md points at paths that do not exist: {missing}"


def test_contributing_carries_no_causal_or_attack_language() -> None:
    """The 0.8 honesty gate, applied to the doc that recruits people to the project.

    Invariant 4 is not only a property of the report text. A contribution guide that
    describes findings as evidence of an att*ck teaches every future entry's `note`
    — which IS report text — to do the same.
    """
    assert not banned_tokens_in(_text())
