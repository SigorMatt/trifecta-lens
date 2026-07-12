"""The tiered human report (SPEC.md §7).

Realized only for this slice. The report says that out loud: a tier that did not
run is not a tier that found nothing, and silence from the realized tier is not
a clean bill of health (v1 sees verbatim taint only). Every finding carries its
tier badge and its family, and the two-leg family is always visibly the lesser
result — it must never read like the trifecta (CLAUDE.md invariant 3).

Pure: events and findings in, a string out. Nothing here writes or sends.
"""

from collections.abc import Sequence
from typing import Final

from trifecta_lens.engine import FAMILY_TRIFECTA
from trifecta_lens.extraction import EXTRACTION, ExtractionConfig
from trifecta_lens.findings import BASIS_CAUSAL, BASIS_TEMPORAL, Finding
from trifecta_lens.model import Event

_HEADER: Final[str] = "trifecta-lens — realized tier"
_TIERS_NOT_RUN: Final[str] = (
    "This slice runs the realized tier only. The posture and reachable tiers are "
    "not implemented yet (Phase 2) — they did not run, and their silence here "
    "means nothing."
)
_VERBATIM_SCOPE: Final[str] = (
    "Scope: realized covers VERBATIM taint only (SPEC.md §6). A value that was "
    "encoded, split, summarized or paraphrased between source and sink does not "
    "match. No finding is not evidence of no flow."
)
_UNAVAILABLE: Final[str] = (
    "realized: UNAVAILABLE — this trace carries no payload-level span content, "
    "so there is nothing to match values against. This is not a clean result: "
    "the realized tier could not run. Re-capture with payload-level "
    "instrumentation (FIXTURES.md), or rely on posture/reachable."
)
_NO_FINDINGS: Final[str] = "no realized findings on this trace."

#: What each basis MEANS, spelled out. Printing the bare word "temporal" would
#: be a label, not a disclosure (DECISIONS.md D5).
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
    FAMILY_TRIFECTA: "all three legs observed",
    # The two-leg family must always announce what it is NOT.
    "sensitive_to_exfil_sink": "two-leg — NOT the trifecta",
}


def realized_is_available(events: Sequence[Event]) -> bool:
    """Whether the trace has the payload-level content realized needs.

    Absent payloads mean realized is UNAVAILABLE, not empty (SPEC.md §7).
    """
    return any(e.inputs is not None or e.outputs is not None for e in events)


def _format_finding(finding: Finding) -> list[str]:
    badge = _FAMILY_BADGE.get(finding.family, "")
    lines = [
        f"[{finding.tier.upper()}]  {finding.family}  ({badge})",
        f"  {finding.summary}",
        "",
        "  path   " + " -> ".join(
            f"{leg.event} ({leg.tool}, {leg.role})" for leg in finding.legs
        ),
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


def format_report(
    findings: Sequence[Finding],
    events: Sequence[Event],
    config: ExtractionConfig = EXTRACTION,
) -> str:
    """Render the tiered human report. Deterministic: same inputs, same text."""
    # The disclosure goes in EVERY report, including a silent one: "no finding"
    # is only auditable if the reader knows what the search was bounded by
    # (SPEC.md §6.1).
    disclosure = f"Detected under: {config.describe()}."

    lines = [_HEADER, "=" * len(_HEADER), "", _TIERS_NOT_RUN, ""]

    if not realized_is_available(events):
        lines += [_UNAVAILABLE, "", disclosure, ""]
        return "\n".join(lines)

    if not findings:
        lines += [_NO_FINDINGS, "", _VERBATIM_SCOPE, disclosure, ""]
        return "\n".join(lines)

    for finding in findings:
        lines += _format_finding(finding)

    count = len(findings)
    plural = "" if count == 1 else "s"
    lines += [
        f"{count} realized finding{plural}.",
        "",
        _VERBATIM_SCOPE,
        disclosure,
        "",
    ]
    return "\n".join(lines)
