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

from trifecta_lens.engine import FAMILY_TRIFECTA, ReachableCollapse
from trifecta_lens.extraction import EXTRACTION, ExtractionConfig
from trifecta_lens.findings import (
    BASIS_CAUSAL,
    BASIS_TEMPORAL,
    CapabilityFinding,
    Finding,
)
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


def realized_is_available(events: Sequence[Event]) -> bool:
    """Whether the trace has the payload-level content realized needs.

    Absent payloads mean realized is UNAVAILABLE, not empty (SPEC.md §7).
    """
    return any(e.inputs is not None or e.outputs is not None for e in events)


def _rule(label: str) -> list[str]:
    return ["", f"--- {label} " + "-" * max(0, 66 - len(label)), ""]


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
        "",
        "  legs observed:",
    ]
    lines += [
        f"    {leg.role:<17} {leg.event:<4} {leg.tool or '-':<10} {leg.note}"
        for leg in finding.legs
    ]
    if finding.legs_not_observed:
        lines.append("  legs NOT observed:")
        lines += [
            f"    {role:<17} not seen anywhere in this trace"
            for role in finding.legs_not_observed
        ]
    lines += ["", f"  {finding.note}", ""]
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
    for leg in finding.legs:
        tools = ", ".join(t.tool for t in leg.tools)
        note = leg.tools[0].note if leg.tools else ""
        lines.append(f"    {leg.role:<17} {tools}")
        if note:
            lines.append(f"    {'':<17} ({note})")
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


def _capability_section(
    label: str,
    findings: tuple[CapabilityFinding, ...] | None,
    disclosure: str = "",
) -> list[str]:
    lines = _rule(label)
    if findings is None:
        return [*lines, _CAPABILITY_NOT_RUN, ""]
    if disclosure:
        lines += [disclosure, ""]
    if not findings:
        return [*lines, _NO_CAPABILITY_FINDINGS, ""]
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

    lines += _realized_section(results)
    lines += _capability_section(
        "REACHABLE",
        results.reachable,
        results.collapse.disclosure if results.collapse else "",
    )
    lines += _capability_section("POSTURE", results.posture)

    # The disclosure goes in EVERY report, including a silent one: "no finding" is
    # only auditable if the reader knows what the search was bounded by (SPEC §6.1).
    lines += ["", f"Detected under: {config.describe()}.", ""]
    return "\n".join(lines)
