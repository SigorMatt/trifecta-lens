"""Task 2.11: the reachable tier, the collapse disclosure, and NON-VACUITY (D1, D7).

Reachable is the tier the tool exists to report: all legs co-exposed to **one**
agent context, so a single run could wire them. It is also the tier most easily
shipped as a lie — a middle tier that is secretly equal to posture satisfies
`realized ⊆ reachable ⊆ posture` *trivially, while carrying no information*
(`DECISIONS.md` F2). That is the tier-honesty failure occurring inside the tier
structure, and D1 binds two things on shipping it:

1. **Prove non-vacuity on a REAL inventory** — there must exist a real captured
   stack where reachable is strictly tighter than posture. TASKS 2.11 makes this a
   🛑 HALT condition: if it fails on the real capture, stop, do not weaken the tier.
   `test_NON_VACUITY_...` below is that check. It reads the real Checkpoint D
   inventory and fails loudly if reachable ever degenerates.

2. **Disclose the collapse case** — on a single-context stack reachable *is*
   necessarily posture, and the tool must say so rather than presenting a tier that
   silently carries nothing.

The single-context stack used for (2) is derived by SLICING the real inventory down
to one of its captured contexts. Nothing here is invented: a projection of a real
capture is still a real capture's data (`AGENT.md`: never fabricate a captured
artifact).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from trifecta_lens.engine import (
    FAMILY_TRIFECTA,
    FAMILY_TWO_LEG,
    detect_posture,
    detect_reachable,
    detect_realized,
    reachable_collapse,
    satisfied_families,
)
from trifecta_lens.findings import TIER_REACHABLE
from trifecta_lens.inventory import load_inventory
from trifecta_lens.labeling import label_events, label_inventory
from trifecta_lens.loader import load_otlp_trace
from trifecta_lens.model import LabeledStack
from trifecta_lens.roles import SINK_EXFIL

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
INVENTORY = FIXTURES / "inventory.json"
OTLP_TRACE = FIXTURES / "demo_mcp_trace.otlp.json"


def _stack() -> LabeledStack:
    """The REAL captured stack (Checkpoint D): two contexts, assistant + triage."""
    return label_inventory(load_inventory(INVENTORY))


def _one_context(context_id: str) -> LabeledStack:
    """The real stack sliced to a single captured context. Not a fabrication."""
    stack = _stack()
    return LabeledStack(
        contexts=tuple(c for c in stack.contexts if c.id == context_id)
    )


# --- 🛑 THE HALT CONDITION ---------------------------------------------------


def test_NON_VACUITY_reachable_is_strictly_tighter_than_posture_on_the_real_stack() -> (
    None
):
    """D1/D7's binding constraint, on the REAL captured inventory.

    If this fails, Track C must HALT (TASKS 2.11): the answer is D7's constructed
    fallback held to a documented in-the-wild topology — NOT weakening the tier
    until it passes.

    The witness: `triage` is a real captured agent context that carries the source
    and sensitive legs but NO outbound sink, so it cannot wire the family that
    posture finds in the stack. Posture is structurally unable to see that
    distinction. That is reachable carrying information.
    """
    stack = _stack()
    collapse = reachable_collapse(stack)

    assert not collapse.collapsed, (
        "reachable COLLAPSED into posture on the real captured inventory. "
        "This is the 🛑 halt condition in TASKS 2.11 — do not weaken the tier to "
        "make it pass."
    )
    assert collapse.narrowed_contexts == ("triage",)

    # And concretely, at the level of what each context can conclude:
    posture_families = satisfied_families(stack.posture_context().roles())
    assistant = satisfied_families(stack.context("assistant").roles())
    triage = satisfied_families(stack.context("triage").roles())

    assert posture_families  # posture finds the family...
    assert assistant == posture_families  # ...the broad context can wire it...
    assert triage == ()  # ...and the restricted one cannot. STRICTLY tighter.


def test_the_narrowed_context_is_missing_exactly_the_sink() -> None:
    """*Why* triage cannot wire it — read off the real artifact, not assumed."""
    stack = _stack()
    triage = next(c for c in stack.contexts if c.id == "triage")
    assistant = next(c for c in stack.contexts if c.id == "assistant")

    assert SINK_EXFIL not in triage.roles()
    assert SINK_EXFIL in assistant.roles()
    assert {t.name for t in assistant.tools} - {t.name for t in triage.tools} == {
        "notify__send"
    }


# --- The tier itself ---------------------------------------------------------


def test_reachable_fires_only_for_the_context_that_can_wire_it() -> None:
    findings = list(detect_reachable(_stack()))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.tier == TIER_REACHABLE
    assert finding.family == FAMILY_TRIFECTA
    assert finding.context == "assistant"
    assert finding.sink_tool == "notify__send"

    # The restricted context produced NOTHING. That silence is the tier working.
    assert "triage" not in {f.context for f in findings}


def test_a_reachable_finding_carries_the_context_provenance() -> None:
    """A capability finding about an unexplained context id is unactionable.

    The human-written capture note (D2) travels with the finding, so a reader knows
    what `assistant` *is* without going back to the inventory file.
    """
    finding = next(iter(detect_reachable(_stack())))
    assert "personal assistant" in finding.context_provenance.lower()


def test_reachable_discloses_that_it_is_doing_work_on_this_stack() -> None:
    finding = next(iter(detect_reachable(_stack())))
    assert "strictly tighter than posture" in finding.disclosure
    assert "triage" in finding.disclosure
    # And it is in the SERIALIZED line, not only in the report: an NDJSON consumer
    # must not have to trust that someone printed the caveat elsewhere.
    assert "strictly tighter" in json.loads(finding.to_json_line())["disclosure"]


# --- The collapse case (D1's other binding constraint) -----------------------


def test_a_single_context_stack_triggers_the_collapse_disclosure() -> None:
    """On one context, reachable IS posture. Say so; do not ship a silent tier."""
    stack = _one_context("assistant")
    collapse = reachable_collapse(stack)

    assert collapse.collapsed
    assert collapse.narrowed_contexts == ()
    assert "reachable adds no information on this stack" in collapse.disclosure
    assert "single agent context" in collapse.disclosure
    assert "treat this finding as posture" in collapse.disclosure

    # The finding itself carries it — the caveat cannot be separated from the claim.
    finding = next(iter(detect_reachable(stack)))
    assert "adds no information" in finding.disclosure


def test_the_collapsed_tier_still_agrees_with_posture() -> None:
    """The collapse claim must be TRUE, not merely printed."""
    stack = _one_context("assistant")
    reachable = {(f.family, f.sink_tool) for f in detect_reachable(stack)}
    posture = {(f.family, f.sink_tool) for f in detect_posture(stack)}
    assert reachable == posture


def test_a_stack_whose_only_context_cannot_wire_it_finds_nothing() -> None:
    """The other single-context case: collapsed, and correctly empty."""
    stack = _one_context("triage")
    assert list(detect_reachable(stack)) == []
    assert list(detect_posture(stack)) == []
    assert reachable_collapse(stack).collapsed


# --- The full chain: realized ⊆ reachable ⊆ posture (DESIGN.md §3) -----------


def _accepted(legs_by_sink: dict[str, frozenset[str]]) -> set[tuple[str, str]]:
    return {
        (family.id, sink)
        for sink, legs in legs_by_sink.items()
        for family in satisfied_families(legs)
    }


def test_realized_subset_reachable_subset_posture_on_the_real_capture() -> None:
    """2.11's done-when: the whole lattice, executable, on real artifacts.

    Compared at the ACCEPTANCE predicate rather than the reported family — a run
    that accepts the trifecta also accepts two-leg but is reported only once, at the
    strongest (SPEC.md §5), so comparing reported families would compare different
    projections and prove nothing.
    """
    stack = _stack()
    events = label_events(load_otlp_trace(OTLP_TRACE))

    realized = {
        (family.id, finding.sink_tool)
        for finding in detect_realized(events)
        for family in satisfied_families(frozenset(finding.legs_observed))
    }
    reachable = _accepted(
        {
            sink.name: context.roles()
            for context in stack.contexts
            for family in satisfied_families(context.roles())
            for sink in context.tools_with(family.sink)
        }
    )
    union = stack.posture_context()
    posture = _accepted(
        {
            sink.name: union.roles()
            for family in satisfied_families(union.roles())
            for sink in union.tools_with(family.sink)
        }
    )

    assert realized, "the real trace realized nothing — the fixture is not exercising"
    assert realized <= reachable <= posture, (
        f"the tier lattice is broken: realized={sorted(realized)} "
        f"reachable={sorted(reachable)} posture={sorted(posture)}"
    )


def test_realized_is_STRICTLY_inside_reachable_and_that_is_the_product() -> None:
    """The gap between the tiers is the whole reason all three exist.

    The captured run realized only the two-leg family: it read the file and posted
    it, with no untrusted source in the path. But the `assistant` context is *also*
    exposed to `fetch__fetch` — so the same context could have wired the full
    trifecta, and no run we captured did.

    "Could, but didn't" is precisely what reachable is for, and it is invisible to
    realized. If this test ever collapses to equality, the tiers have stopped
    earning their keep.
    """
    stack = _stack()
    events = label_events(load_otlp_trace(OTLP_TRACE))

    realized_families = {
        family.id
        for finding in detect_realized(events)
        for family in satisfied_families(frozenset(finding.legs_observed))
    }
    reachable_families = {f.family for f in detect_reachable(stack)}

    assert realized_families == {FAMILY_TWO_LEG}
    assert FAMILY_TRIFECTA not in realized_families  # no source leg was OBSERVED...
    assert FAMILY_TRIFECTA in reachable_families  # ...but one is EXPOSED. Could≠did.


def test_reachable_is_deterministic() -> None:
    a = [f.to_json_line() for f in detect_reachable(_stack())]
    b = [f.to_json_line() for f in detect_reachable(_stack())]
    assert a == b


def test_capability_findings_are_deterministic_ACROSS_PROCESSES() -> None:
    """The in-process check above is not enough, and this is not a hypothetical.

    Leg order was originally read straight off `family.required` — a frozenset. Its
    iteration order depends on string hashing, which Python RANDOMIZES per process.
    The findings were byte-identical within one run and differed between runs: the
    determinism invariant broken in the one way a same-process test can never see.

    So run the pipeline in fresh interpreters with different `PYTHONHASHSEED`s and
    demand identical bytes. Any sorted-by-accident iteration in the capability tiers
    gets caught here.
    """
    script = (
        "from trifecta_lens.engine import detect_posture, detect_reachable;"
        "from trifecta_lens.inventory import load_inventory;"
        "from trifecta_lens.labeling import label_inventory;"
        "s = label_inventory(load_inventory('fixtures/inventory.json'));"
        "print(''.join(f.to_json_line() for f in "
        "list(detect_posture(s)) + list(detect_reachable(s))))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("0", "1", "42", "12345")
    }
    assert len(outputs) == 1, (
        "capability findings differ across processes — something in the tiers "
        "iterates a set. Same inputs must give the same bytes (CLAUDE.md)."
    )
