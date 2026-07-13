"""Inventory loader + the composability join (task 2.6, D2/D8).

Loads the REAL captured inventory (Checkpoint D) and asserts the properties the
posture/reachable tiers will rest on, plus the join that makes "the three tiers
describe one system" checkable: the real captured trace's tool names are a subset
of the inventory's tool names.

The core OTLP front-end is task 2.7, so here the trace's tool names are read from
the OTLP artifact directly — the assertion is at the artifact level, which is
exactly where the composability guarantee has to hold.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trifecta_lens.inventory import (
    InvalidInventoryError,
    ToolRef,
    load_inventory,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
INVENTORY = FIXTURES / "inventory.json"
TRACE = FIXTURES / "demo_mcp_trace.otlp.json"


def _trace_tool_names(otlp_path: Path) -> set[str]:
    """Extract the ``tool.name`` of every span in an OTLP/JSON document.

    A minimal reader — the core OTLP loader is task 2.7; this proves the join at
    the artifact level without depending on it.
    """
    doc = json.loads(otlp_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for resource_spans in doc.get("resourceSpans", []):
        for scope_spans in resource_spans.get("scopeSpans", []):
            for span in scope_spans.get("spans", []):
                for attr in span.get("attributes", []):
                    if attr["key"] == "tool.name":
                        names.add(attr["value"]["stringValue"])
    return names


def test_real_inventory_loads_two_contexts() -> None:
    inv = load_inventory(INVENTORY)
    ids = [c.id for c in inv.contexts]
    assert ids == ["assistant", "triage"]


def test_qualified_names_are_server_scoped() -> None:
    inv = load_inventory(INVENTORY)
    assistant = inv.context("assistant")
    assert "filesystem__read_text_file" in assistant.qualified_names()
    assert "notify__send" in assistant.qualified_names()


def test_reachable_is_a_strict_subset_of_posture_on_the_real_inventory() -> None:
    # The non-vacuity property (D1/D7), read straight off the captured artifact:
    # triage's tool set is a STRICT subset of the posture union, and the tool it
    # lacks is exactly the outbound sink.
    inv = load_inventory(INVENTORY)
    posture = inv.posture_tools()
    triage = inv.context("triage").qualified_names()
    assistant = inv.context("assistant").qualified_names()

    assert triage < posture  # strict subset -> reachable ⊊ posture
    assert "notify__send" in posture
    assert "notify__send" in assistant
    assert "notify__send" not in triage
    # The ONLY difference is the sink leg.
    assert assistant - triage == {"notify__send"}


def test_composability_join_trace_names_subset_of_inventory() -> None:
    # The Checkpoint D acceptance (D8): every tool the real trace names exists in
    # the inventory. Same <server>__<tool> scheme on both sides -> the two
    # artifacts describe ONE system.
    inv = load_inventory(INVENTORY)
    trace_names = _trace_tool_names(TRACE)
    assert trace_names  # the trace really did call tools
    assert trace_names <= inv.posture_tools(), (
        f"trace tool names {sorted(trace_names)} are not all in the inventory "
        f"{sorted(inv.posture_tools())}"
    )
    # And concretely, the two legs the trace walked:
    assert "filesystem__read_text_file" in trace_names
    assert "notify__send" in trace_names


def test_toolref_qualified() -> None:
    assert ToolRef(name="read_text_file", server="filesystem").qualified == (
        "filesystem__read_text_file"
    )


def test_a_tool_with_no_server_is_identified_by_its_bare_name() -> None:
    """`server` is OPTIONAL, and that is what makes a non-MCP agent work (D14).

    Qualification exists for exactly one reason: under MCP two servers may each expose a
    `read`. An agent whose tools are ordinary local functions (LangChain, a hand-rolled
    loop) has NO servers and a flat name space — and its trace emits `send_email`, not
    `local__send_email`.

    Forcing a fake server on such a stack invents an identity its trace does not carry,
    which breaks the composability join BY CONSTRUCTION. That is not hypothetical: it
    produced a REALIZED trifecta alongside a REACHABLE two-leg in one report — realized
    ⊄ reachable, the containment guarantee violated in the one place this project calls
    it structural.
    """
    assert ToolRef(name="send_email").qualified == "send_email"
    assert ToolRef(name="send_email", server=None).qualified == "send_email"


def test_provenance_is_carried_through() -> None:
    inv = load_inventory(INVENTORY)
    triage = inv.context("triage")
    assert "no outbound" in triage.provenance.lower()


def test_malformed_inventory_fails_loudly(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"

    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(InvalidInventoryError):
        load_inventory(bad)

    bad.write_text('{"contexts": "nope"}', encoding="utf-8")
    with pytest.raises(InvalidInventoryError):
        load_inventory(bad)

    bad.write_text(
        json.dumps({"contexts": [{"id": "c", "tools": [{"server": "s"}]}]}),
        encoding="utf-8",
    )
    with pytest.raises(InvalidInventoryError):  # tool entry missing the 'tool' object
        load_inventory(bad)

    # An EMPTY server is malformed — but an ABSENT one is the non-MCP case and is legal
    # (D14). The two must not be conflated: one is a broken file, the other is a whole
    # class of agent.
    bad.write_text(
        json.dumps({"contexts": [{"id": "c", "tools": [
            {"server": "", "tool": {"name": "t"}}
        ]}]}),
        encoding="utf-8",
    )
    with pytest.raises(InvalidInventoryError):
        load_inventory(bad)


def test_an_inventory_with_no_servers_at_all_loads(tmp_path: Path) -> None:
    """The non-MCP shape: no `server` anywhere, identities are bare names (D14)."""
    path = tmp_path / "flat.json"
    path.write_text(
        json.dumps({"contexts": [{"id": "researcher", "tools": [
            {"tool": {"name": "crm_lookup"}},
            {"tool": {"name": "send_email"}},
        ]}]}),
        encoding="utf-8",
    )
    inventory = load_inventory(path)
    assert inventory.posture_tools() == {"crm_lookup", "send_email"}


def test_posture_is_deterministic() -> None:
    # Same file -> identical posture set, twice (determinism invariant).
    assert load_inventory(INVENTORY).posture_tools() == (
        load_inventory(INVENTORY).posture_tools()
    )
