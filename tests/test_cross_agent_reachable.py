"""Task 3.14b / D15 part 2: reachable across a DECLARED delegation chain.

D15 part 1 closed the honesty hole — a cross-agent flow is detected, and the finding
now says reachable cannot corroborate it. This closes it from the capability side.

**Why reachable could not already do this.** Its edge relation is co-exposure *within
one context*. In a cross-agent flow no single context holds every leg — that is what
makes it cross-agent — so reachable is *structurally* unable to see one. It goes silent
exactly where the danger is, and silence reads as safety.

**Why this is a separate tier, not a flavour of reachable.** It is a **weaker** claim.
It rests on an assumption the *operator supplied* — that these agents can pass data
between them — which no captured artifact corroborates and no trace was consulted to
check. A tier that borrows a stronger tier's name borrows its credibility (`CLAUDE.md`
invariant 3), so this one gets its own name, its own summary and its own note, and it
says what it assumed.

**And there is no new machinery.** A delegation chain is a synthetic ``LabeledContext``,
exactly as posture's union is (``model.delegation_context``), so ``detect_capability``
runs unchanged. Three bags of tools, one automaton — which is what keeps
``reachable ⊆ reachable-across-a-chain ⊆ posture`` structural rather than asserted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trifecta_lens.catalog import default_catalog
from trifecta_lens.engine import (
    detect_posture,
    detect_reachable,
    detect_reachable_cross_agent,
)
from trifecta_lens.findings import TIER_REACHABLE, TIER_REACHABLE_CROSS
from trifecta_lens.inventory import InvalidInventoryError, load_inventory
from trifecta_lens.labeling import label_inventory

ROOT = Path(__file__).resolve().parent.parent
DELEGATING = ROOT / "fixtures" / "usage" / "delegating_inventory.json"

#: The same two agents, with the handoff NOT declared. Everything else identical.
UNDECLARED: dict[str, Any] = {
    "contexts": [
        {"id": "reader", "provenance": "probe",
         "tools": [{"tool": {"name": "fetch"}}, {"tool": {"name": "read_secret"}}]},
        {"id": "sender", "provenance": "probe",
         "tools": [{"tool": {"name": "send_email"}}]},
    ]
}


def _stack(tmp_path: Path, doc: dict[str, Any]) -> Any:
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return label_inventory(load_inventory(path), default_catalog())


# --- the tier sees what reachable structurally cannot -----------------------


def test_a_declared_chain_pools_legs_no_single_agent_holds() -> None:
    stack = label_inventory(load_inventory(DELEGATING), default_catalog())

    assert not tuple(detect_reachable(stack)), (
        "neither agent holds all three legs — if reachable fires, the premise is gone"
    )

    (finding,) = tuple(detect_reachable_cross_agent(stack))
    assert finding.tier == TIER_REACHABLE_CROSS
    assert finding.family == "exfil_trifecta"
    assert finding.context == "reader -> sender"
    assert finding.sink_tool == "send_email"


def test_it_never_borrows_reachables_language() -> None:
    """Invariant 3, at the tier boundary. This is the WEAKER claim and must read as one.

    The temptation is to call it "reachable" — it is, after all, about reachability.
    But reachable's claim is corroborated by the inventory alone, and this one is not:
    it rests on a declaration only the operator can make. Blurring them lets the weaker
    finding ride on the stronger one's evidence, which is the exact failure invariant 3
    exists to stop.
    """
    stack = label_inventory(load_inventory(DELEGATING), default_catalog())
    (finding,) = tuple(detect_reachable_cross_agent(stack))

    assert finding.tier != TIER_REACHABLE
    # It states the assumption it rests on, and whose it is.
    assert "assumption YOU supplied" in finding.note
    assert "nothing in the captured inventory corroborates" in finding.note
    assert "If the declared handoff is wrong, this finding is wrong" in finding.note
    # And it refuses the stronger tier's headline outright.
    assert "not the lethal-trifecta condition proper" in finding.note
    assert "reachable did not accept here" in finding.note
    # It observed nothing, and never implies it did.
    assert "observed" not in finding.summary


def test_without_a_declaration_the_tier_does_not_run(tmp_path: Path) -> None:
    """We will not INFER a handoff. An inventory says what an agent can reach, never
    who it talks to — inventing the edge would manufacture the finding.
    """
    stack = _stack(tmp_path, UNDECLARED)
    assert stack.delegation_chains() == ()
    assert not tuple(detect_reachable_cross_agent(stack))
    # And posture still sees the legs, so the stack is not "clean" — just unjoined.
    assert tuple(detect_posture(stack))


# --- it reports only what reachable could NOT -------------------------------


def test_it_does_not_double_count_what_a_single_agent_already_wires(
    tmp_path: Path,
) -> None:
    """If one agent in the chain already holds every leg, that IS reachable.

    Reporting it again under a weaker tier would double-count one exposure — and worse,
    would let the weaker claim appear to be corroborated by the stronger one's finding.
    """
    doc = json.loads(json.dumps(UNDECLARED))
    doc["contexts"][0]["delegates_to"] = ["sender"]
    # The reader can now send mail itself — so it wires the whole thing alone.
    doc["contexts"][0]["tools"].append({"tool": {"name": "send_email"}})
    stack = _stack(tmp_path, doc)

    reachable = tuple(detect_reachable(stack))
    assert {f.context for f in reachable} == {"reader"}, "reader wires it alone now"
    assert not tuple(detect_reachable_cross_agent(stack)), (
        "the chain re-reported an exposure a single agent already accounts for"
    )


def test_containment_holds_across_the_new_tier() -> None:
    """reachable ⊆ reachable-across-a-chain ⊆ posture — structural, not asserted.

    Each tier hands the same automaton a WIDER bag of tools: one context, then the
    contexts a declared handoff joins, then every context. A wider bag cannot accept
    fewer families.
    """
    stack = label_inventory(load_inventory(DELEGATING), default_catalog())
    chain = stack.delegation_chains()[0]

    single = frozenset().union(*(stack.context(c).roles() for c in chain))
    pooled = stack.delegation_context(chain).roles()
    everything = stack.posture_context().roles()

    for context_id in chain:
        assert stack.context(context_id).roles() <= pooled
    assert pooled <= everything
    assert single == pooled  # the chain here IS every context, so they coincide


# --- the declaration is validated, not trusted blindly ----------------------


def test_a_handoff_to_a_context_that_does_not_exist_fails(tmp_path: Path) -> None:
    """A dangling edge would silently SHRINK the chain and under-report. Fail."""
    doc = json.loads(json.dumps(UNDECLARED))
    doc["contexts"][0]["delegates_to"] = ["snder"]  # typo
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(InvalidInventoryError, match="unknown context"):
        load_inventory(path)


def test_no_doc_still_claims_there_are_three_tiers() -> None:
    """The count drifted the moment a tier was added, and nothing caught it.

    `SPEC.md` §1 said "three tiers"; `CLAUDE.md` invariant 3 said "the three tiers have
    fixed definitions"; the posture disclosure the tool PRINTS said "the weakest of the
    three tiers". A doc that miscounts the thing it specifies is not a rounding error —
    invariant 3 IS the tier structure, and it was describing a structure that no longer
    existed.

    So the count is now derived, not retyped, and the docs may not contradict it.
    """
    from trifecta_lens.findings import TIERS

    assert len(TIERS) == 4, "a tier moved; every doc below must move with it"

    # The docs that SPECIFY the tier structure, and the core modules that describe it
    # in prose a reader will trust. (ROADMAP/TASKS/DECISIONS are historical records and
    # are correctly frozen at what was true when written.)
    docs = ("SPEC.md", "CLAUDE.md", "README.md", "USAGE.md")
    targets = [ROOT / name for name in docs]
    targets += sorted((ROOT / "trifecta_lens").glob("*.py"))

    for path in targets:
        text = path.read_text(encoding="utf-8").lower()
        for stale in ("three tiers", "three-tier framing"):
            assert stale not in text, (
                f"{path.name} still says {stale!r}, but there are {len(TIERS)} tiers. "
                "The docs and the core prose specify the tier structure; one that "
                "miscounts it is describing a machine we do not ship."
            )


def test_posture_and_the_chain_tier_do_not_both_claim_to_be_the_weakest() -> None:
    """"Weaker" has TWO axes, and conflating them was a real slip in this very work.

    Posture is the **loosest** — it pins down least, and overlaps ordinary static
    scanners. `reachable_cross_agent` is the **least corroborated** — it rests on a
    declaration nothing verifies. Those are different failings. Calling both "the
    weakest" tells the reader one of them is something it is not, and quietly invites
    the chain tier to inherit posture's (milder) reputation, or vice versa.
    """
    from trifecta_lens.engine import DISCLOSURE_POSTURE, NOTE_REACHABLE_CROSS

    assert "LOOSEST" in DISCLOSURE_POSTURE
    assert "LEAST CORROBORATED" in NOTE_REACHABLE_CROSS
    # Neither may claim the other's failing as its own.
    assert "least corroborated" not in DISCLOSURE_POSTURE.lower()
    assert "loosest" in NOTE_REACHABLE_CROSS.lower(), (
        "the chain tier must name posture as the loosest, so a reader cannot mistake "
        "'least corroborated' for 'least specific'"
    )


def test_chains_are_transitive_and_deterministic(tmp_path: Path) -> None:
    """a -> b -> c pools all three: data that can walk the chain can walk all of it."""
    doc: dict[str, Any] = {
        "contexts": [
            {"id": "a", "provenance": "p", "delegates_to": ["b"],
             "tools": [{"tool": {"name": "fetch"}}]},
            {"id": "b", "provenance": "p", "delegates_to": ["c"],
             "tools": [{"tool": {"name": "read_secret"}}]},
            {"id": "c", "provenance": "p",
             "tools": [{"tool": {"name": "send_email"}}]},
        ]
    }
    stack = _stack(tmp_path, doc)
    chains = stack.delegation_chains()
    assert ("a", "b", "c") in chains
    assert chains == stack.delegation_chains()  # deterministic

    findings = tuple(detect_reachable_cross_agent(stack))
    assert any(f.context == "a -> b -> c" for f in findings)
