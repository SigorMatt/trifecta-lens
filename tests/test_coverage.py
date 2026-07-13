"""Task 3.12: a silent tier is only a result if the catalog recognised the stack.

**The bug this closes.** Handed an inventory of Slack + Postgres + Linear —
`read_channel_history` (untrusted content), `postgres__query` (private data),
`slack__post_to_channel` (an outbound sink), all in one agent context, which is a
textbook lethal trifecta — trifecta-lens printed:

    no findings at this tier: the captured inventory does not carry all the legs
    of any family we detect.

It had matched **none** of the four tools against its catalog, and never said so. A
reader takes that for a clean bill of health. It is not one.

This was a hole in a principle the code already stated. `report.py`: *"A tier that did
not run is not a tier that found nothing."* And `Detected under:` ships on every report,
including the empty ones, because (D4, SPEC.md §6.1) an undisclosed bound makes "no
finding" un-auditable — *the same honesty failure as an overclaim, pointed the other
way*. The catalog is a far larger bound than `min_value_chars`, and it was the one bound
never disclosed.

**And the trap these tests exist to hold the line on.** "Matched no entry" has two
causes and we cannot tell them apart: a tool we have never heard of (`postgres__query`),
and a tool we know and deliberately leave unlabeled (`filesystem__list_directory`
returns *names*, not content — SPEC.md §4 says labeling it "would make every `ls` a
leg"). So the disclosure counts and names; it must never *classify*. Calling an
unmatched tool "uncovered" overclaims a gap; calling it "safe" overclaims a clearance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trifecta_lens.catalog import default_catalog, parse_catalog
from trifecta_lens.coverage import inventory_coverage, trace_coverage
from trifecta_lens.engine import detect_posture, detect_reachable, reachable_collapse
from trifecta_lens.inventory import load_inventory
from trifecta_lens.labeling import label_events, label_inventory
from trifecta_lens.loader import load_otlp_trace
from trifecta_lens.report import TierResults, format_report

ROOT = Path(__file__).resolve().parent.parent
REAL_INVENTORY = ROOT / "fixtures" / "inventory.json"
REAL_TRACE = ROOT / "fixtures" / "demo_mcp_trace.otlp.json"

# The stack that motivated this task: a real lethal trifecta, in servers our catalog has
# never heard of. Slack history is untrusted content, the database holds private data,
# and posting to a channel sends data out of the boundary. We label none of it.
STRANGER_STACK: dict[str, Any] = {
    "contexts": [
        {
            "id": "assistant",
            "provenance": "hand-authored for this test — not a capture.",
            "servers": ["slack", "postgres", "linear"],
            "tools": [
                {"server": "slack", "tool": {"name": "post_to_channel"}},
                {"server": "slack", "tool": {"name": "read_channel_history"}},
                {"server": "postgres", "tool": {"name": "query"}},
                {"server": "linear", "tool": {"name": "get_ticket"}},
            ],
        }
    ]
}


def _stack(tmp_path: Path, doc: dict[str, Any], catalog: Any = None) -> Any:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return label_inventory(load_inventory(path), catalog or default_catalog())


def _report(stack: Any) -> str:
    return format_report(
        results=TierResults(
            reachable=tuple(detect_reachable(stack)),
            posture=tuple(detect_posture(stack)),
            collapse=reachable_collapse(stack),
            coverage=inventory_coverage(stack),
        )
    )


# --- the failing case that motivated the work -------------------------------


def test_a_stack_we_recognise_nothing_of_does_not_read_as_clean(tmp_path: Path) -> None:
    stack = _stack(tmp_path, STRANGER_STACK)
    coverage = inventory_coverage(stack)

    assert coverage.total == 4
    assert coverage.matched == ()
    assert coverage.nothing_matched is True
    assert coverage.unmatched == (
        "linear__get_ticket",
        "postgres__query",
        "slack__post_to_channel",
        "slack__read_channel_history",
    )

    report = _report(stack)
    assert "matched 0 of 4 tools" in report
    # Every unrecognised tool is NAMED. A count alone tells the reader they have a
    # problem; the list tells them which entries to write.
    for tool in coverage.unmatched:
        assert tool in report, f"{tool} is unrecognised and not shown to the reader"

    assert "NOT a clean result" in report
    assert "Treat the tiers as un-run" in report


def test_the_silent_tier_says_it_is_not_a_result(tmp_path: Path) -> None:
    """The exact sentence that used to mislead, and what replaced it."""
    report = _report(_stack(tmp_path, STRANGER_STACK))
    assert "does not carry all the legs of any family we detect" not in report, (
        "the tier still reports a stack we recognised NOTHING of as though its silence "
        "were a fact about the stack"
    )


# --- the real capture: partial coverage, stated calmly ----------------------


def test_the_real_capture_reports_partial_coverage_without_crying_wolf() -> None:
    """Pins "unmatched ≠ unsafe" against a real artifact, not a constructed one.

    On the real Checkpoint D inventory the six unmatched tools are **every one** a
    directory-listing or file-metadata tool — precisely the ones SPEC.md §4 says must
    stay unlabeled, because they return names rather than content and labeling them
    would make every `ls` a leg of an exfil finding.

    So the common case of an unmatched tool is a *correct* silence, and the disclosure
    has to survive that without turning into an alarm. A coverage warning that fires
    like a smoke detector on toast gets taped over, and then it is worth nothing on the
    day it matters.
    """
    stack = label_inventory(load_inventory(REAL_INVENTORY), default_catalog())
    coverage = inventory_coverage(stack)

    assert coverage.matched, "the real capture must match SOMETHING"
    assert coverage.unmatched, "the real capture has deliberately-unlabeled tools"
    assert coverage.nothing_matched is False
    assert coverage.complete is False
    assert all("filesystem__" in t for t in coverage.unmatched), (
        "the real capture's unmatched set changed; this test's premise (they are all "
        f"the correctly-unlabeled listing/metadata tools) no longer holds: "
        f"{coverage.unmatched}"
    )

    report = _report(stack)
    assert "matched 10 of 16 tools" in report
    assert "NOT a clean result" not in report, (
        "partial coverage is NORMAL — a real stack is full of tools that correctly "
        "carry no role. Escalating it to the language reserved for a stack we "
        "recognised nothing of would train the reader to ignore the disclosure."
    )
    assert "Treat the tiers as un-run" not in report


def test_coverage_is_disclosed_even_when_there_are_findings() -> None:
    """`Detected under:` rides on every report; so must this. Same argument (§6.1).

    A finding does not mean the search was complete. An unmatched tool could be the sink
    of a trifecta we never reported — so coverage bounds a report that found something
    exactly as much as one that found nothing.
    """
    stack = label_inventory(load_inventory(REAL_INVENTORY), default_catalog())
    report = _report(stack)
    assert tuple(detect_posture(stack)), "the real inventory yields findings"
    assert "--- COVERAGE" in report
    assert "matched no entry:" in report
    # And the action text must hold in BOTH worlds: an unmatched tool means a leg may be
    # missing, whether or not something was found. An earlier draft said "the silence
    # below is our labeling" — which is simply false on a report that has findings.
    assert "whether or not anything was found" in report


# --- full coverage is the only case where silence is a result ---------------


def test_when_everything_matched_a_silent_tier_is_a_real_result(
    tmp_path: Path,
) -> None:
    """Then, and only then, "we found nothing" is a claim about the stack."""
    overlay = parse_catalog(
        """
version: 1
entries:
  - id: t.linear.ticket
    match: {tool: "linear__get_ticket"}
    role: untrusted_source
    note: "ticket text, authored by whoever filed it"
  - id: t.slack.history
    match: {tool: "slack__read_channel_history"}
    role: untrusted_source
    note: "channel messages, authored by whoever posted them"
  - id: t.pg.query
    match: {tool: "postgres__query"}
    role: sensitive_data
    note: "returns rows from the application database"
  - id: t.slack.post
    match: {tool: "slack__post_to_channel"}
    role: sink
    subtype: exfil
    note: "posts a message body into a channel"
""",
        source="test overlay",
    )
    stack = _stack(
        tmp_path, STRANGER_STACK, default_catalog().overlaid_with(overlay)
    )
    coverage = inventory_coverage(stack)
    assert coverage.complete is True
    assert coverage.unmatched == ()

    report = _report(stack)
    assert "matched 4 of 4 tools" in report
    assert "a silent tier below is a result about this stack" in report
    # And now the catalog HAS an opinion, the trifecta this stack always carried is
    # reported. That is the flywheel: coverage disclosure -> the user writes an entry ->
    # the unmodified engine finds it.
    reachable = tuple(detect_reachable(stack))
    assert reachable, "with the stack labeled, the trifecta must surface"
    assert {f.sink_tool for f in reachable} == {"slack__post_to_channel"}


# --- trace-side coverage, and the honesty gate ------------------------------


def test_a_span_with_no_tool_is_not_counted_as_an_unrecognised_tool() -> None:
    """An agent span is not a tool we failed to recognise; it names no tool at all.

    Counting it as unmatched would inflate the gap with spans that were never
    candidates, and the disclosure's whole value is that its numbers are trustworthy.
    """
    events = label_events(load_otlp_trace(REAL_TRACE), default_catalog())
    assert any(e.tool is None for e in events), "the real trace has a non-tool span"

    coverage = trace_coverage(events)
    assert coverage.total == len({e.tool for e in events if e.tool is not None})


def test_the_disclosure_never_classifies_an_unmatched_tool(tmp_path: Path) -> None:
    """It may count and name. It may not clear, and it may not condemn.

    We cannot distinguish "never heard of it" from "known, and correctly unlabeled", so
    any word that picks one is an overclaim. This is invariant 4 (flow, not causation)
    pointed at the labeling layer.
    """
    for doc in (STRANGER_STACK, json.loads(REAL_INVENTORY.read_text())):
        report = _report(_stack(tmp_path, doc))
        lowered = report.lower()
        for word in ("safe", "harmless tool", "no risk", "uncovered", "vulnerable"):
            assert word not in lowered, (
                f"the coverage disclosure classifies an unmatched tool as {word!r}. It "
                "cannot know that: a tool we never heard of and a tool we deliberately "
                "leave unlabeled are indistinguishable from here."
            )
        # It must say what it CAN'T know, in the same breath as the list.
        assert "cannot tell you which of these are harmless" in report
