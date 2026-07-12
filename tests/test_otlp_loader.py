"""Real OTLP/OpenInference front-end (task 2.7, D9).

Built and tested against the REAL Checkpoint D capture
(``fixtures/demo_mcp_trace.otlp.json``), not an imagined OTLP shape. Asserts the
two done-when clauses: the real captured trace loads to the expected Event
stream, and the existing realized detector runs on it **unchanged**.

The detector keys on ROLES, which the catalog assigns (task 2.8). The catalog for
server-qualified MCP names is Track C, so here roles are assigned test-locally —
that is deliberately NOT shipped in core. The point of this test is the *ingest
fidelity*: once labeled, the loaded Event stream drives the unmodified engine to
fire on the real flow.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from trifecta_lens.engine import FAMILY_TWO_LEG, detect_realized
from trifecta_lens.findings import BASIS_TEMPORAL, TIER_REALIZED
from trifecta_lens.loader import MalformedSpanError, load_otlp_trace
from trifecta_lens.model import Event
from trifecta_lens.roles import SENSITIVE_DATA, SINK_EXFIL

TRACE = Path(__file__).resolve().parent.parent / "fixtures" / "demo_mcp_trace.otlp.json"

_SECRET = "sk-demo-trifecta-lens-mcp-DO-NOT-USE-0000"


def _label(events: list[Event]) -> list[Event]:
    """Assign roles test-locally (the qualified-name catalog is Track C, 2.8)."""
    roles = {
        "filesystem__read_text_file": {SENSITIVE_DATA},
        "notify__send": {SINK_EXFIL},
    }
    return [replace(e, roles=set(roles.get(e.tool or "", set()))) for e in events]


def test_real_otlp_loads_expected_event_stream() -> None:
    events = load_otlp_trace(TRACE)
    # AGENT root + two TOOL children, in start-time order.
    assert [e.action for e in events] == ["AGENT", "TOOL", "TOOL"]
    tools = [e.tool for e in events]
    assert tools == [None, "filesystem__read_text_file", "notify__send"]

    root, read, send = events
    # Ancestry survives OTLP decode: both tool spans parent to the agent root.
    assert root.parent_id is None
    assert read.parent_id == root.id
    assert send.parent_id == root.id
    # Sorted by (ts, id): the agent root started first.
    assert root.ts <= read.ts <= send.ts


def test_nested_otlp_attributes_decode_to_payloads() -> None:
    _, read, send = load_otlp_trace(TRACE)
    # output.value / input.value survive the nested {key, value:{stringValue}}
    # decode and the mime-typed payload parse.
    assert read.outputs is not None and _SECRET in read.outputs["text"]
    assert send.inputs is not None and send.inputs["body"] == _SECRET


def test_existing_detector_runs_unchanged_and_fires_on_the_real_flow() -> None:
    events = _label(load_otlp_trace(TRACE))
    findings = list(detect_realized(events))  # the engine, unmodified

    assert len(findings) == 1
    finding = findings[0]
    assert finding.tier == TIER_REALIZED
    # No untrusted_source span in this trace -> the honest lesser family.
    assert finding.family == FAMILY_TWO_LEG
    assert finding.sink_tool == "notify__send"
    # Siblings under the agent root -> the path rests on ordering, and says so.
    assert finding.path_basis == BASIS_TEMPORAL
    # The value is masked; the raw secret never appears in the finding.
    line = finding.to_json_line()
    assert _SECRET not in line
    assert any("MASKED" in m for m in finding.masked_values)


def test_otlp_load_is_deterministic() -> None:
    a = [e.to_dict() for e in load_otlp_trace(TRACE)]
    b = [e.to_dict() for e in load_otlp_trace(TRACE)]
    assert a == b


def test_malformed_otlp_fails_loudly(tmp_path: Path) -> None:
    bad = tmp_path / "bad.otlp.json"

    # A span missing its start time is malformed, not silently dropped.
    bad.write_text(
        json.dumps(
            {
                "resourceSpans": [
                    {
                        "scopeSpans": [
                            {"spans": [{"spanId": "AAAA", "name": "x"}]}
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(MalformedSpanError):
        load_otlp_trace(bad)

    # A span with no span.kind attribute is a malformed fixture (FIXTURES.md).
    bad.write_text(
        json.dumps(
            {
                "resourceSpans": [
                    {
                        "scopeSpans": [
                            {
                                "spans": [
                                    {
                                        "spanId": "AAAA",
                                        "name": "x",
                                        "startTimeUnixNano": "1",
                                        "attributes": [],
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(MalformedSpanError):
        load_otlp_trace(bad)
