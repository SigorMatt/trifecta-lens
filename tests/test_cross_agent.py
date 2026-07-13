"""Task 3.14 / D15: the cross-agent flow we have always detected and always denied.

`SPEC.md` §8 listed cross-agent multi-hop as an explicit non-goal — *"must never appear
in output, docs or --help as current capability."* Asked why, I ran one instead of
reading the doc. **It fires.**

The engine folds a trace in time order carrying **one global taint set** and no notion
of an agent at all (`engine.py`). So a secret read by agent A and emailed out by agent
B, in one trace, has always produced a realized finding. We shipped the capability and
denied it.

Two things followed from that, and the first is why this is a bug and not a happy
accident:

1. **Containment breaks.** Reachable asks whether **one** agent context holds every leg.
   In a genuine cross-agent flow, by definition, **none does** — so reachable a genuine
   cross-agent flow, by definition, **none does** — so reachable goes silent exactly
   when realized fires. `realized ⊄ reachable`: the guarantee `DESIGN.md` §3 calls *"a
   structural property of the machine"*, violated. This is the **second** instance of
   the D14 class, and unlike D14 it is not a naming accident — it falls straight out of
   the tier definitions.
2. **The finding hid the hop.** The path printed as `r_read -> s_send`, as though one
   agent did both. A flow that changes hands is a materially bigger claim.

The identity was already in the trace: a tool span's nearest ancestor of kind `AGENT` is
the agent that ran it, and `parent_id` and the span kind are both among the six
attributes we already read. Nothing had ever looked at them together.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trifecta_lens.catalog import default_catalog
from trifecta_lens.coverage import inventory_coverage
from trifecta_lens.engine import detect_posture, detect_reachable, detect_realized
from trifecta_lens.inventory import load_inventory
from trifecta_lens.labeling import label_events, label_inventory
from trifecta_lens.loader import load_otlp_trace, load_trace
from trifecta_lens.report import TierResults, format_report

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
CROSS_AGENT = FIXTURES / "cross_agent_handoff.jsonl"

# : The stack the handoff runs on: a `reader` agent that can read secrets, a `sender`
# agent : that can send mail. **Neither holds both legs** — that is what makes it cross-
# agent, and : it is exactly why the reachable tier cannot corroborate the flow.
SPLIT_STACK: dict[str, Any] = {
    "contexts": [
        {
            "id": "reader",
            "provenance": "hand-authored for the D15 cross-agent case — not a capture.",
            "tools": [{"tool": {"name": "read_secret"}}],
        },
        {
            "id": "sender",
            "provenance": "hand-authored for the D15 cross-agent case — not a capture.",
            "tools": [{"tool": {"name": "send_email"}}],
        },
    ]
}


def _events() -> tuple[Any, ...]:
    return tuple(label_events(load_trace(CROSS_AGENT), default_catalog()))


def _report(tmp_path: Path) -> str:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(SPLIT_STACK), encoding="utf-8")
    stack = label_inventory(load_inventory(path), default_catalog())
    events = _events()
    return format_report(
        results=TierResults(
            events=events,
            realized=tuple(detect_realized(events)),
            reachable=tuple(detect_reachable(stack)),
            posture=tuple(detect_posture(stack)),
            coverage=inventory_coverage(stack),
        )
    )


# --- the agent identity was in the trace all along --------------------------


def test_a_tool_span_knows_which_agent_ran_it() -> None:
    """Nearest ancestor of kind AGENT. No new format, no new attribute (D15)."""
    by_id = {event.id: event for event in _events()}
    assert by_id["r_read"].agent == "reader"
    assert by_id["s_send"].agent == "sender"
    # The sub-agent spans themselves sit under the orchestrator.
    assert by_id["reader"].agent == "orch"
    assert by_id["orch"].agent is None, "the root agent has no agent above it"


def test_every_committed_fixture_is_still_single_agent() -> None:
    """No regression: the disclosure must fire ONLY on a genuine crossing.

    A false "this crossed agents" would be a bigger overclaim than the silence it
    replaces, so the fixtures that are single-agent must stay that way.
    """
    for path, loader in (
        (FIXTURES / "demo_mcp_trace.otlp.json", load_otlp_trace),
        (FIXTURES / "worked_example.jsonl", load_trace),
        (FIXTURES / "usage" / "nonmcp_trace.jsonl", load_trace),
    ):
        events = label_events(loader(path), default_catalog())
        agents = {e.agent for e in events if e.tool is not None}
        assert len(agents) == 1, f"{path.name} is no longer single-agent: {agents}"

    for finding in detect_realized(
        tuple(label_events(load_otlp_trace(FIXTURES / "demo_mcp_trace.otlp.json")))
    ):
        assert finding.crosses_agents is False


# --- the flow is detected, and now it SAYS it crossed -----------------------


def test_the_cross_agent_flow_is_detected_and_names_both_agents() -> None:
    """One agent read the secret; another sent it. The engine never cared."""
    findings = tuple(detect_realized(_events()))
    assert len(findings) == 1
    finding = findings[0]

    assert finding.crosses_agents is True
    assert finding.agents == ("reader", "sender")
    assert [leg.agent for leg in finding.legs] == ["reader", "sender"]

    # And the language does not escalate just because it crossed. It is still flow, not
    # causation: we observed a value reach a sink, not one agent "handing" it to
    # another.
    assert "observed reaching" in finding.summary
    assert "attack" not in finding.summary.lower()


def test_the_report_explains_why_reachable_is_silent(tmp_path: Path) -> None:
    """The containment fix, and the whole point of D15.

    Reachable finds NOTHING here — correctly, because no single context holds both legs.
    Left unexplained, a reader compares a REALIZED finding against a silent REACHABLE
    tier and concludes either that the tool contradicts itself, or (far worse) that the
    silence is reassuring. It is neither: the two tiers are answering different
    questions, and only one of them can see a flow that changes hands.
    """
    report = _report(tmp_path)

    assert "[REALIZED]" in report
    assert "CROSSED AN AGENT BOUNDARY" in report
    assert "reader -> sender" in report

    # Reachable is genuinely silent on this stack...
    path = tmp_path / "inventory.json"
    stack = label_inventory(load_inventory(path), default_catalog())
    assert not tuple(detect_reachable(stack)), (
        "if reachable fires here the test's premise is gone — neither context holds "
        "both legs, which is what MAKES this cross-agent"
    )
    # ...and the report says why, where the reader meets it, rather than leaving them to
    # infer a contradiction.
    assert "silence is not a contradiction" in report
    assert "Do not read that silence as reassurance" in report


def test_the_disclosure_does_not_claim_one_agent_handed_it_to_another(
    tmp_path: Path,
) -> None:
    """Invariant 4, at the agent boundary — the tempting overclaim lives here.

    We observed a value in agent A's span and the same value, verbatim, in agent B's
    sink. We did **not** observe a handoff: no span says "A passed this to B", and the
    value could have reached B by any route. Saying "one agent handed the secret to
    another" would be exactly the causal claim `CLAUDE.md` invariant 4 forbids — dressed
    up as an architectural insight.
    """
    report = _report(tmp_path).lower()
    for claim in ("handed", "passed it", "delegated the secret", "leaked to"):
        assert claim not in report, (
            f"the cross-agent disclosure asserts a handoff ({claim!r}). We observed a "
            "value reaching a sink in another agent's span. We saw no handoff."
        )
