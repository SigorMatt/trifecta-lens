"""The tiered human report (SPEC.md §5, §7). Pure: values in, a string out.

All three tiers, each with its own badge, its own verb, and its own weight. The
report's whole job is to keep them apart (`CLAUDE.md` invariant 3), so three rules
are structural here rather than editorial:

* **A tier that did not run is not a tier that found nothing.** No inventory means
  posture and reachable are UNAVAILABLE — not silent, not clean. Same for realized
  without a trace, and for a trace with no payloads.
* **Strongest tier first, and posture is never the headline.** Posture overlaps what
  ordinary static scanners already do; leading with it would sell the weakest claim
  as the result.
* **Every tier states what it did NOT do.** Realized says no-finding is not
  no-flow. The capability tiers say, in their own words, that they observed nothing
  at all — they read an inventory, not a payload.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from trifecta_lens.coverage import Coverage
from trifecta_lens.engine import FAMILY_TRIFECTA, ReachableCollapse
from trifecta_lens.extraction import EXTRACTION, ExtractionConfig
from trifecta_lens.findings import (
    BASIS_CAUSAL,
    BASIS_TEMPORAL,
    CapabilityFinding,
    Finding,
)
from trifecta_lens.join import Join
from trifecta_lens.model import Event

_HEADER: Final[str] = "trifecta-lens"

#: What each tier MEANS, printed every run. A badge the reader has to already
#: understand is not a disclosure.
_LEGEND: Final[tuple[str, ...]] = (
    "REALIZED   a run DID wire it: a tainted value was observed reaching a sink, "
    "verbatim.",
    "REACHABLE  one agent context COULD wire it. No run was observed doing so.",
    "POSTURE    the legs exist somewhere in the stack. Weakest tier — it overlaps "
    "ordinary static scanners.",
)

_VERBATIM_SCOPE: Final[str] = (
    "Scope: realized covers VERBATIM taint only (SPEC.md §6). A value that was "
    "encoded, split, summarized or paraphrased between source and sink does not "
    "match. No finding is not evidence of no flow."
)
_REALIZED_UNAVAILABLE_PAYLOAD: Final[str] = (
    "realized: UNAVAILABLE — this trace carries no payload-level span content, so "
    "there is nothing to match values against. This is not a clean result: the "
    "realized tier could not run. Re-capture with payload-level instrumentation "
    "(FIXTURES.md), or rely on posture/reachable."
)
_REALIZED_NOT_RUN: Final[str] = (
    "realized: NOT RUN — no trace was given (--trace). This tier says nothing about "
    "this stack, and its silence here is not a clean result."
)
_CAPABILITY_NOT_RUN: Final[str] = (
    "posture and reachable: NOT RUN — no tool inventory was given (--inventory). "
    "These tiers say nothing about this stack. A captured inventory is how the tool "
    "learns what the agent COULD do (SPEC.md §7, DECISIONS.md D2)."
)
_NO_REALIZED_FINDINGS: Final[str] = "no realized findings on this trace."
_NO_CAPABILITY_FINDINGS: Final[str] = (
    "no findings at this tier: the captured inventory does not carry all the legs "
    "of any family we detect."
)

# --- Coverage: the largest bound on what we can find, and the last one disclosed ---
#
# `Detected under:` has always ridden on every report because an undisclosed bound makes
# "no finding" un-auditable (D4, SPEC.md §6.1). That was written about min_value_chars.
# It applies with far more force to the CATALOG: pointed at a stack it had no entries
# for, this tool used to print "no findings at this tier" and let a reader take it for a
# clean bill of health.
#
# What it may NOT do is classify. "Matched no entry" has two causes — a tool we have
# never heard of, and a tool we know and deliberately leave unlabeled (a directory
# listing returns names, not content; SPEC.md §4) — and they are indistinguishable from
# here. So these strings count, name, and hand the reader the list. They never say
# "uncovered" (overclaims a gap) and never say "safe" (overclaims a clearance).

_COVERAGE_MEANING: Final[str] = (
    "A tool that matches no catalog entry carries no role, and a tool with no role is "
    "invisible to EVERY tier below. We cannot tell you which of these are harmless: a "
    "tool we have never heard of, and a tool we know and deliberately leave unlabeled "
    "(a directory listing returns names, not content, and carries no role by design — "
    "SPEC.md §4), look identical from here."
)
_COVERAGE_ACTION: Final[str] = (
    "Read the list. If any of those tools reads private data, ingests untrusted "
    "content, or sends data out of your boundary, we did not see it — so a leg may be "
    "MISSING from everything below, whether or not anything was found. Teach it:\n"
    "  trifecta-lens --catalog my-stack.yaml ...    (CONTRIBUTING.md)"
)
_COVERAGE_NONE: Final[str] = (
    "The catalog matched NOTHING in this stack. Every tier below is silent because we "
    "recognised none of these tools — not because the stack is clean. Treat the tiers "
    "as un-run."
)
_COVERAGE_COMPLETE: Final[str] = (
    "Every tool matched a catalog entry, so a silent tier below is a result about this "
    "stack rather than a limit of our labeling."
)

# --- The join: do the two artifacts describe ONE system? --------------------------
#
# realized ⊆ reachable ⊆ posture holds BY CONSTRUCTION — but only for a trace and an
# inventory that share a tool name space. Nothing checked that at runtime, and a non-MCP
# user whose trace says `fetch` while their inventory says `local__fetch` got a REALIZED
# trifecta and a REACHABLE two-leg in the same report: containment violated, silently,
# in the one place this project calls it structural (DESIGN.md §3, D14).
#
# We disclose; we do not repair. Guessing that `fetch` and `local__fetch` are the same
# tool would put a tool in a finding that no artifact named.

_JOIN_DISJOINT: Final[str] = (
    "THE TRACE AND THE INVENTORY SHARE NO TOOL NAMES AT ALL. Every tier below is "
    "computed, but they are NOT describing one system, and realized ⊆ reachable does "
    "NOT hold between them — compare them at your own risk. This is usually a "
    "name-space mismatch rather than two unrelated systems: a bare 'fetch' in the "
    "trace against a qualified 'local__fetch' in the inventory. Make the two agree "
    "(USAGE.md), then re-run."
)
_JOIN_UNLISTED: Final[str] = (
    "The trace called tool(s) the inventory does not list. A run can only call a tool "
    "its agent is exposed to, so one of two things is true and we cannot tell which: "
    "the inventory is incomplete, or the two artifacts use different names for the "
    "same tools. Until they agree, realized ⊆ reachable is not guaranteed."
)


def _join_section(join: Join | None) -> list[str]:
    """Printed only when the join FAILS. A holding join needs no words."""
    if join is None or not join.applicable or join.holds:
        return []

    lines = _rule("JOIN — READ THIS FIRST")
    lines.append(_JOIN_DISJOINT if join.disjoint else _JOIN_UNLISTED)
    lines += ["", "  called by the trace, absent from the inventory:"]
    lines += [f"    {name}" for name in join.unlisted]
    lines += ["", "  the inventory exposes:"]
    lines += [f"    {name}" for name in join.exposed]
    lines.append("")
    return lines


#: What each basis MEANS, spelled out. Printing the bare word "temporal" would be
#: a label, not a disclosure (DECISIONS.md D5).
_BASIS_MEANING: Final[dict[str, str]] = {
    BASIS_TEMPORAL: (
        "temporal — the steps were observed in this ORDERING; the trace carries "
        "no parent-child link between them, so this does not establish that one "
        "fed the other"
    ),
    BASIS_CAUSAL: (
        "causal — the trace's own ancestry links these spans. This describes the "
        "instrumentation's parent chain, not intent"
    ),
    "mixed": (
        "mixed — some steps are linked by the trace's ancestry, others only by "
        "the ordering in which they were observed"
    ),
}

_FAMILY_BADGE: Final[dict[str, str]] = {
    FAMILY_TRIFECTA: "all three legs",
    # The two-leg family must always announce what it is NOT.
    "sensitive_to_exfil_sink": "two-leg — NOT the trifecta",
}


@dataclass(frozen=True)
class TierResults:
    """What each tier produced — or ``None`` if it never ran.

    ``None`` and ``()`` are different answers and the report must never conflate
    them: an empty tuple is "this tier ran and found nothing", ``None`` is "this
    tier was given no input". Collapsing the two is how a tool ends up implying a
    clean bill of health it never checked for.
    """

    events: tuple[Event, ...] = ()
    realized: tuple[Finding, ...] | None = None
    reachable: tuple[CapabilityFinding, ...] | None = None
    posture: tuple[CapabilityFinding, ...] | None = None
    collapse: ReachableCollapse | None = None
    #: Whether the trace and the inventory describe ONE system (D8/D14). ``None`` when
    #: only one of them was given — there is nothing to join.
    join: Join | None = None
    #: How much of the inventory the catalog had an opinion about. ``None`` when no
    #: inventory was given (there is nothing to have covered). A silent capability
    #: tier is only a *result* if this says the catalog recognised the stack.
    coverage: Coverage | None = None


def realized_is_available(events: Sequence[Event]) -> bool:
    """Whether the trace has the payload-level content realized needs.

    Absent payloads mean realized is UNAVAILABLE, not empty (SPEC.md §7).
    """
    return any(e.inputs is not None or e.outputs is not None for e in events)


def _rule(label: str) -> list[str]:
    return ["", f"--- {label} " + "-" * max(0, 66 - len(label)), ""]


#: A cross-agent flow is a BIGGER claim than a single-agent one, and it is the case
#: the reachable tier is structurally unable to corroborate: reachable asks whether ONE
#: agent context holds every leg, and in a cross-agent flow, by definition, none does.
#: So reachable goes silent exactly when this fires — and a reader comparing the two
#: tiers would read that silence as a contradiction, or worse, as reassurance.
#:
#: It is not a contradiction. It is the two tiers answering different questions, and the
#: report has to say so where the reader meets it (D15).
_CROSSES_AGENTS: Final[str] = (
    "This flow CROSSED AN AGENT BOUNDARY: one agent read the value, another sent it. "
    "REACHABLE cannot corroborate this, and its silence is not a contradiction — it "
    "asks whether a SINGLE agent context holds every leg, and here, by definition, "
    "none does. Do not read that silence as reassurance. (Declaring the handoffs "
    "between your agents is what lets reachable model this — USAGE.md.)"
)


def _format_realized(finding: Finding) -> list[str]:
    badge = _FAMILY_BADGE.get(finding.family, "")
    lines = [
        f"[{finding.tier.upper()}]  {finding.family}  ({badge})",
        f"  {finding.summary}",
        "",
        "  path   "
        + " -> ".join(f"{leg.event} ({leg.tool}, {leg.role})" for leg in finding.legs),
        "  basis  " + _BASIS_MEANING.get(finding.path_basis, finding.path_basis),
        "  value  " + ", ".join(finding.masked_values),
    ]
    if finding.crosses_agents:
        lines += [
            "  agents " + " -> ".join(finding.agents),
            "",
            f"  {_CROSSES_AGENTS}",
        ]
    lines += [
        "",
        "  legs observed:",
    ]
    for leg in finding.legs:
        tool = leg.tool or "-"
        lines.append(f"    {leg.role:<17} {leg.event:<4} {tool:<10} {leg.note}")
        # Name the entry that made the call. Disagreeing with a label is expected;
        # the user should not have to read our source to act on it (SPEC.md §4).
        lines.append(f"    {'':<17} {'':<4} {'':<10} [catalog: {leg.catalog_entry}]")
    if finding.legs_not_observed:
        lines.append("  legs NOT observed:")
        lines += [
            f"    {role:<17} not seen anywhere in this trace"
            for role in finding.legs_not_observed
        ]
    lines += ["", f"  {finding.note}", ""]
    return lines


def leg_lines(finding: CapabilityFinding) -> list[str]:
    """The exposed-leg block: which tools supply each leg, and which entry said so."""
    lines: list[str] = []
    for leg in finding.legs:
        lines.append(f"    {leg.role:<17} {', '.join(t.tool for t in leg.tools)}")
        for citation in leg.tools:
            lines.append(
                f"    {'':<17} {citation.tool}: {citation.note} "
                f"[catalog: {citation.catalog_entry}]"
            )
    return lines


def _format_capability(finding: CapabilityFinding) -> list[str]:
    badge = _FAMILY_BADGE.get(finding.family, "")
    lines = [
        f"[{finding.tier.upper()}]  {finding.family}  ({badge})",
        f"  {finding.summary}",
        "",
        f"  context  {finding.context}",
        f"           {finding.context_provenance}",
        "",
        # NOT "legs observed" — this tier observed nothing. The word is the tier's
        # honesty, and realized owns it (CLAUDE.md invariant 3).
        "  legs exposed:",
    ]
    for leg in leg_lines(finding):
        lines.append(leg)
    if finding.legs_absent:
        lines.append("  legs NOT exposed:")
        lines += [
            f"    {role:<17} absent from this context"
            for role in finding.legs_absent
        ]
    lines += ["", f"  {finding.note}", ""]
    return lines


def _realized_section(results: TierResults) -> list[str]:
    lines = _rule("REALIZED")
    if results.realized is None:
        return [*lines, _REALIZED_NOT_RUN, ""]
    if not realized_is_available(results.events):
        return [*lines, _REALIZED_UNAVAILABLE_PAYLOAD, ""]
    if not results.realized:
        return [*lines, _NO_REALIZED_FINDINGS, "", _VERBATIM_SCOPE, ""]
    for finding in results.realized:
        lines += _format_realized(finding)
    count = len(results.realized)
    plural = "" if count == 1 else "s"
    lines += [f"{count} realized finding{plural}.", "", _VERBATIM_SCOPE, ""]
    return lines


def _coverage_note(coverage: Coverage) -> str:
    """What a silent capability tier is worth, given how much the catalog recognised."""
    if coverage.nothing_matched:
        return (
            "no findings at this tier — and this is NOT a clean result. The catalog "
            "matched none of this stack's tools, so there was nothing here for the "
            "detector to see. See COVERAGE."
        )
    if not coverage.complete:
        return (
            f"no findings at this tier among the {len(coverage.matched)} tool(s) the "
            f"catalog matched. {len(coverage.unmatched)} tool(s) matched no entry and "
            "are invisible to every tier — see COVERAGE."
        )
    return _NO_CAPABILITY_FINDINGS


def _coverage_section(coverage: Coverage | None) -> list[str]:
    """Printed in EVERY report that had an inventory — including the silent ones."""
    if coverage is None or coverage.total == 0:
        return []

    lines = _rule("COVERAGE")
    lines.append(
        f"The catalog matched {len(coverage.matched)} of {coverage.total} tools in "
        "this inventory."
    )
    if coverage.nothing_matched:
        lines += ["", _COVERAGE_NONE]
    if coverage.complete:
        lines += ["", _COVERAGE_COMPLETE, ""]
        return lines

    # The distinct tools, once. Which context exposes an unmatched tool is not
    # load-bearing — we have no opinion about it *anywhere* — and repeating the same
    # list per context (real stacks share servers) buries the names in duplication.
    lines += ["", "  matched no entry:"]
    lines += [f"    {name}" for name in coverage.unmatched]
    lines += ["", _COVERAGE_MEANING, "", _COVERAGE_ACTION, ""]
    return lines


def _capability_section(
    label: str,
    findings: tuple[CapabilityFinding, ...] | None,
    coverage: Coverage | None = None,
    disclosure: str = "",
) -> list[str]:
    lines = _rule(label)
    if findings is None:
        return [*lines, _CAPABILITY_NOT_RUN, ""]
    if disclosure:
        lines += [disclosure, ""]
    if not findings:
        # A silent tier means different things depending on how much of the stack the
        # catalog recognised. One sentence cannot honestly serve all three cases.
        note = _NO_CAPABILITY_FINDINGS if coverage is None else _coverage_note(coverage)
        return [*lines, note, ""]
    for finding in findings:
        lines += _format_capability(finding)
    return lines


def format_report(
    findings: Sequence[Finding] | None = None,
    events: Sequence[Event] = (),
    config: ExtractionConfig = EXTRACTION,
    results: TierResults | None = None,
) -> str:
    """Render the tiered human report. Deterministic: same inputs, same text.

    Accepts either a full :class:`TierResults` (the three-tier path) or the legacy
    realized-only pair, so a trace-only run still reads exactly as it did.
    """
    if results is None:
        results = TierResults(
            events=tuple(events),
            realized=None if findings is None else tuple(findings),
        )

    lines = [_HEADER, "=" * len(_HEADER), "", *_LEGEND]

    # The join comes first, because a failed join means the tiers below cannot be
    # COMPARED to each other at all — a stronger and more urgent caveat than coverage,
    # which only bounds what each tier could see.
    lines += _join_section(results.join)

    # Coverage next, because it bounds everything below it. A reader who meets the tiers
    # before learning we recognised none of their tools has already drawn the wrong
    # conclusion by the time the caveat arrives.
    lines += _coverage_section(results.coverage)

    lines += _realized_section(results)
    lines += _capability_section(
        "REACHABLE",
        results.reachable,
        results.coverage,
        results.collapse.disclosure if results.collapse else "",
    )
    lines += _capability_section("POSTURE", results.posture, results.coverage)

    # The disclosure goes in EVERY report, including a silent one: "no finding" is
    # only auditable if the reader knows what the search was bounded by (SPEC §6.1).
    lines += ["", f"Detected under: {config.describe()}.", ""]
    return "\n".join(lines)
