"""Task 2.10: the posture tier (D1, SPEC.md §5).

Posture asks the weakest question the tool asks: do the legs of a family exist
*anywhere* in the captured stack? No edges, no guard, no trace.

Two things are pinned here, and the second is the one that matters:

1. The REAL captured inventory (Checkpoint D) yields posture findings.
2. `realized ⊆ posture` holds as an executable property over the REAL trace and the
   REAL inventory together — the containment that `DESIGN.md` §3 claims is
   structural. If this ever fails, the tier design is broken, not the report text.

Tier honesty is checked in the OUTPUT, not just the logic (`CLAUDE.md` invariant 3):
a posture finding must never carry realized's evidence or realized's verbs.
"""

from __future__ import annotations

import json
from pathlib import Path

from trifecta_lens.engine import (
    FAMILY_TRIFECTA,
    detect_posture,
    detect_realized,
    satisfied_families,
)
from trifecta_lens.findings import TIER_POSTURE
from trifecta_lens.inventory import load_inventory
from trifecta_lens.labeling import label_events, label_inventory
from trifecta_lens.loader import load_otlp_trace
from trifecta_lens.model import POSTURE_CONTEXT_ID
from trifecta_lens.roles import SENSITIVE_DATA, SINK_EXFIL, UNTRUSTED_SOURCE

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
INVENTORY = FIXTURES / "inventory.json"
OTLP_TRACE = FIXTURES / "demo_mcp_trace.otlp.json"


def _stack():  # type: ignore[no-untyped-def]
    return label_inventory(load_inventory(INVENTORY))


def test_the_real_inventory_yields_a_posture_finding() -> None:
    """2.10's done-when, on the REAL Checkpoint D capture."""
    findings = list(detect_posture(_stack()))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.tier == TIER_POSTURE
    # The union of the captured stack DOES carry all three legs: fetch (source),
    # the filesystem reads (sensitive), and the notify sink. So posture accepts the
    # strongest family — even though no run ever wired them.
    assert finding.family == FAMILY_TRIFECTA
    assert finding.sink_tool == "notify__send"
    assert finding.legs_present == (UNTRUSTED_SOURCE, SENSITIVE_DATA, SINK_EXFIL)
    assert finding.legs_absent == ()


def test_posture_names_every_tool_that_supplies_each_leg() -> None:
    """The user's next move is to look at this list and prune it. So name them all."""
    finding = next(iter(detect_posture(_stack())))
    by_role = {leg.role: leg for leg in finding.legs}

    sensitive_tools = {t.tool for t in by_role[SENSITIVE_DATA].tools}
    assert "filesystem__read_text_file" in sensitive_tools
    assert "filesystem__read_multiple_files" in sensitive_tools

    assert {t.tool for t in by_role[UNTRUSTED_SOURCE].tools} == {"fetch__fetch"}
    assert {t.tool for t in by_role[SINK_EXFIL].tools} == {"notify__send"}

    # Every cited tool carries the catalog's rationale, so the call is correctable.
    assert all(t.note for leg in finding.legs for t in leg.tools)


def test_the_posture_context_announces_that_it_is_not_a_real_context() -> None:
    """Posture's union is synthetic. Presenting it as an agent context would be a lie.

    A reader who mistakes the union for a real context reads posture as reachable —
    i.e. reads the weakest tier as the middle one. The id and the provenance both
    have to prevent that.
    """
    finding = next(iter(detect_posture(_stack())))
    assert finding.context == POSTURE_CONTEXT_ID
    assert "not a real agent context" in finding.context_provenance


# --- Tier honesty, checked in the TEXT (CLAUDE.md invariant 3) ---------------


def test_a_posture_finding_cannot_carry_realized_evidence() -> None:
    """Structural, not editorial: the type has nowhere to put it.

    A capability finding has no `path`, no `path_basis`, no `masked_values` and no
    `legs_observed` — because posture observed nothing. This test pins that the
    serialized line really has no such keys, so a downstream consumer cannot read a
    posture line as if it were a realized one.
    """
    line = json.loads(next(iter(detect_posture(_stack()))).to_json_line())

    for forbidden in ("path", "path_basis", "path_edges", "masked_values",
                      "legs_observed", "legs_not_observed", "detected_under"):
        assert forbidden not in line, (
            f"a posture finding carries {forbidden!r} — that is realized's evidence, "
            "and this tier has none of it."
        )
    assert line["tier"] == TIER_POSTURE
    assert line["legs_present"] and "legs" in line


def test_posture_text_says_capability_not_observation() -> None:
    finding = next(iter(detect_posture(_stack())))
    text = (finding.summary + " " + finding.note + " " + finding.scope).lower()

    assert "no run was observed" in text
    assert "capability, not observation" in text
    # It must never claim the flow happened, nor borrow realized's verb.
    assert "observed reaching" not in text
    # And it must say out loud that it is the weakest tier (SPEC.md §5).
    assert "weakest" in text


# --- The containment property (DESIGN.md §3) --------------------------------


def test_realized_is_contained_in_posture_on_the_real_capture() -> None:
    """`realized ⊆ posture`, executable, over the REAL trace + the REAL inventory.

    Compared at the level of the ACCEPTANCE predicate, not the reported findings.
    A run that accepts the trifecta also accepts two-leg, but is only *reported*
    once (at the strongest family, SPEC.md §5) — so comparing reported families
    would compare two different projections and prove nothing. What must hold is:
    every (family, sink) the trace realized is a (family, sink) the stack's posture
    admits.

    This is the composability join paying out: the same catalog labeled both
    artifacts, so the two tiers really are talking about one system.
    """
    stack = _stack()
    events = label_events(load_otlp_trace(OTLP_TRACE))

    realized = {
        (family.id, finding.sink_tool)
        for finding in detect_realized(events)
        for family in satisfied_families(frozenset(finding.legs_observed))
    }
    posture_context = stack.posture_context()
    posture = {
        (family.id, sink.name)
        for family in satisfied_families(posture_context.roles())
        for sink in posture_context.tools_with(family.sink)
    }

    assert realized, "the real trace realized nothing — the fixture is not exercising"
    assert realized <= posture, (
        f"realized {sorted(realized)} escaped posture {sorted(posture)}. "
        "The tier lattice is broken."
    )


def test_posture_is_deterministic() -> None:
    a = [f.to_json_line() for f in detect_posture(_stack())]
    b = [f.to_json_line() for f in detect_posture(_stack())]
    assert a == b
