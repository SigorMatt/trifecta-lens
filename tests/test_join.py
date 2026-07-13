"""Task 3.13: `realized ⊆ reachable ⊆ posture` only holds if the artifacts agree (D14).

**The bug.** ``DESIGN.md`` §3 says containment is *"a structural property of the
machine, not editorial discipline in report text."* It is — **for two artifacts that
share a tool name space.** Nothing checked that. The tiers never meet: realized labels
the events of the trace, the capability tiers label the tools of the inventory, and each
is *individually* correct on its own input.

So a non-MCP agent — trace emitting bare ``fetch``, hand-written inventory emitting
qualified ``local__fetch`` — got this, in one report, with no complaint:

    [REALIZED]   exfil_trifecta            (all three legs)
    [REACHABLE]  sensitive_to_exfil_sink   (two-leg — NOT the trifecta)

A realized trifecta that the reachable tier says **cannot be wired**. Containment
violated, silently, in the one place this project calls it structural.

``DECISIONS.md`` D8 already called the join *"a fixture assertion — an executable
test, not a hope"*, and ``tests/test_inventory.py`` pins it — **for our own artifacts**.
Nothing pinned it for the user's. A guarantee that holds only for inputs we happened to
author is not a guarantee; it is a coincidence.

Two things fix it, and this file holds both:

1. **The identity model was wrong for non-MCP stacks.** ``server`` is now optional, so
   a flat agent's tool is identified by its bare name — the name its trace carries.
   Forcing ``local__`` on it *invented* an identity, and the join could never hold.
2. **The join is computed at runtime and disclosed when it fails.** We disclose; we do
   not repair. Guessing that ``fetch`` and ``local__fetch`` are the same tool would put
   a tool in a finding that no artifact named.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trifecta_lens.catalog import default_catalog
from trifecta_lens.coverage import inventory_coverage
from trifecta_lens.engine import (
    detect_posture,
    detect_reachable,
    detect_realized,
    reachable_collapse,
)
from trifecta_lens.inventory import load_inventory
from trifecta_lens.join import composability_join
from trifecta_lens.labeling import label_events, label_inventory
from trifecta_lens.loader import load_otlp_trace, load_trace
from trifecta_lens.report import TierResults, format_report

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
REAL_TRACE = FIXTURES / "demo_mcp_trace.otlp.json"
REAL_INVENTORY = FIXTURES / "inventory.json"
NONMCP_TRACE = FIXTURES / "usage" / "nonmcp_trace.jsonl"
NONMCP_INVENTORY = FIXTURES / "usage" / "nonmcp_inventory.json"


def _run(trace: Path, inventory: Path, catalog: Any = None) -> tuple[Any, str]:
    active = catalog or default_catalog()
    loader = load_otlp_trace if trace.suffix == ".json" else load_trace
    events = tuple(label_events(loader(trace), active))
    stack = label_inventory(load_inventory(inventory), active)
    join = composability_join(events, stack)
    report = format_report(
        results=TierResults(
            events=events,
            realized=tuple(detect_realized(events)),
            reachable=tuple(detect_reachable(stack)),
            posture=tuple(detect_posture(stack)),
            collapse=reachable_collapse(stack),
            coverage=inventory_coverage(stack),
            join=join,
        )
    )
    return join, report


# --- the join holds on the artifacts that share a name space ----------------


def test_the_real_capture_joins_and_says_nothing_about_it() -> None:
    """A holding join needs no words. Silence here is the correct output."""
    join, report = _run(REAL_TRACE, REAL_INVENTORY)
    assert join.holds
    assert not join.unlisted
    assert "JOIN" not in report, (
        "the report cries mismatch on two artifacts that agree — an alarm that fires "
        "when nothing is wrong is worse than no alarm"
    )


def test_a_flat_non_mcp_stack_joins(tmp_path: Path) -> None:
    """The whole point of making `server` optional (D14): bare names, and they MEET."""
    join, report = _run(NONMCP_TRACE, NONMCP_INVENTORY)
    assert join.holds, (
        f"the non-MCP trace calls {join.called} and its inventory exposes "
        f"{join.exposed} — these must be the same identities or no tier is comparable"
    )
    assert "JOIN" not in report


# --- the regression: a mismatch must never pass silently --------------------


def _qualified_copy(tmp_path: Path) -> Path:
    """The BROKEN inventory: the same stack, but with a fake server bolted on.

    This is exactly what a non-MCP user was forced to write before `server` became
    optional, because the loader demanded one. It is the shape that produced the bug.
    """
    doc = json.loads(NONMCP_INVENTORY.read_text(encoding="utf-8"))
    for context in doc["contexts"]:
        for entry in context["tools"]:
            entry["server"] = "local"
    path = tmp_path / "qualified.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_a_namespace_mismatch_is_caught_and_named(tmp_path: Path) -> None:
    """The exact input that emitted a realized trifecta over a reachable two-leg."""
    join, report = _run(NONMCP_TRACE, _qualified_copy(tmp_path))

    assert not join.holds
    assert join.disjoint, "bare vs qualified names share nothing — that is the signal"
    assert set(join.unlisted) == {"fetch", "crm_lookup", "send_email"}

    assert "JOIN" in report
    assert "SHARE NO TOOL NAMES" in report
    # The tiers are still computed — we do not suppress them, we say they are not
    # comparable. Suppressing would hide evidence the user asked us to look at.
    assert "REALIZED" in report and "REACHABLE" in report
    # And every unjoinable name is shown, on both sides, so the user can SEE the
    # mismatch rather than take our word for it.
    for name in ("fetch", "crm_lookup", "send_email"):
        assert name in report
    for name in ("local__fetch", "local__crm_lookup", "local__send_email"):
        assert name in report


def test_a_partial_mismatch_is_caught_too(tmp_path: Path) -> None:
    """The subtler case: the inventory is merely INCOMPLETE (D8's subset condition).

    A run can only call a tool its agent is exposed to, so a trace naming a tool the
    inventory lacks means the inventory is not the whole story — and reachable is then
    computed over a stack smaller than the one that actually ran. Containment is not
    guaranteed, and quietly reporting anyway would be asserting a comparison we cannot
    make.
    """
    doc = json.loads(NONMCP_INVENTORY.read_text(encoding="utf-8"))
    doc["contexts"][0]["tools"] = [
        t for t in doc["contexts"][0]["tools"] if t["tool"]["name"] != "send_email"
    ]
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    join, report = _run(NONMCP_TRACE, path)
    assert not join.holds
    assert not join.disjoint, "they still share names — this is the partial case"
    assert join.unlisted == ("send_email",)
    assert "JOIN" in report
    assert "SHARE NO TOOL NAMES" not in report, (
        "the partial case borrowed the disjoint case's alarm; they are different "
        "problems and the reader needs to know which one they have"
    )
    assert "does not list" in report


def test_the_join_disclosure_does_not_guess_which_side_is_wrong(tmp_path: Path) -> None:
    """We cannot know whether the inventory is incomplete or the names disagree.

    Both produce the same evidence. Renaming the user's tools to force a match would put
    a tool in a finding that no artifact named — the same line D2 draws about topology,
    and invariant 4 draws about causation. So the report offers both readings and picks
    neither.
    """
    _, report = _run(NONMCP_TRACE, _qualified_copy(tmp_path))
    lowered = report.lower()
    assert (
        "we cannot tell which" in lowered
        or "usually a name-space mismatch" in lowered
    )
    for word in ("renamed", "corrected", "assuming", "we matched"):
        assert word not in lowered, (
            f"the join disclosure claims to have resolved the mismatch ({word!r}). It "
            "must disclose, never repair."
        )
