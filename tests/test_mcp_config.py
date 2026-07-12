"""Unit tests for the real-MCP demo topology (tasks 2.4/2.5).

These test the *pure* configuration and namespacing logic — the part that must
be correct for the inventory and the trace to describe one system — without
launching a server, a model, or needing the ``demo`` extra. The live capture
itself is exercised at Checkpoint D, not here.

Importing the demo capture modules is itself part of the contract: they must
import with only the ``dev`` extra present (heavy SDKs imported lazily), exactly
as ``demo.providers`` does. If any of these imports pulls in ``mcp`` or
OpenTelemetry at module load, this test file fails to import under CI.
"""

from __future__ import annotations

import pytest

from demo import (  # noqa: F401  (import-time contract: must not need the extra)
    capture_inventory,
    mcp_client,
    mcp_config,
    otel_export,
    run_mcp,
    sink_server,
)


def test_qualify_roundtrips() -> None:
    q = mcp_config.qualify("filesystem", "read_text_file")
    assert q == "filesystem__read_text_file"
    assert mcp_config.split_qualified(q) == ("filesystem", "read_text_file")


def test_split_preserves_tool_underscores() -> None:
    # The tool name's own underscores must survive; only the first separator
    # splits (server ids are separator-free by construction).
    server, tool = mcp_config.split_qualified("filesystem__read_multiple_files")
    assert (server, tool) == ("filesystem", "read_multiple_files")


def test_qualify_rejects_separator_in_server_id() -> None:
    with pytest.raises(mcp_config.MCPConfigError):
        mcp_config.qualify("a__b", "tool")


def test_split_rejects_unqualified_name() -> None:
    with pytest.raises(mcp_config.MCPConfigError):
        mcp_config.split_qualified("fetch")  # no separator


def test_every_server_id_is_separator_free() -> None:
    # The unambiguous-split guarantee depends on this holding for the real ids.
    for server_id in mcp_config.SERVERS:
        assert mcp_config.NAMESPACE_SEP not in server_id


def test_contexts_are_asymmetric_for_non_vacuity() -> None:
    # reachable can only be a STRICT subset of posture if some context lacks a
    # leg the union has. The triage context must lack the sink server.
    assistant = set(mcp_config.CONTEXTS["assistant"])
    triage = set(mcp_config.CONTEXTS["triage"])
    assert "notify" in assistant  # the sink
    assert "notify" not in triage
    assert triage < assistant  # strict subset


def test_trace_context_has_the_sink() -> None:
    # A realized flow can only be captured from a context that owns an outbound
    # leg, so the trace context must include the sink server.
    assert "notify" in mcp_config.CONTEXTS[mcp_config.TRACE_CONTEXT]


def test_server_ids_for_validates() -> None:
    assert mcp_config.server_ids_for("assistant") == ["fetch", "filesystem", "notify"]
    with pytest.raises(mcp_config.MCPConfigError):
        mcp_config.server_ids_for("nope")


def test_every_context_server_is_defined() -> None:
    for servers in mcp_config.CONTEXTS.values():
        for server_id in servers:
            assert server_id in mcp_config.SERVERS


def test_sink_records_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    # The inert sink returns a status and performs no delivery. With no outbox
    # env set it only counts bytes; the important observation lives in the span.
    monkeypatch.delenv(sink_server.OUTBOX_ENV, raising=False)
    status = sink_server._record("status://register", "sk-demo-0000")
    assert "recorded" in status
    assert "not delivered" in status


def test_every_context_has_a_provenance_note() -> None:
    # D2 requires a human-written provenance note per context; the capture note
    # must carry both the context's intent and the capture method (no model).
    for context_id in mcp_config.CONTEXTS:
        note = capture_inventory._capture_note(context_id)
        assert context_id in capture_inventory.CONTEXT_INTENT
        assert capture_inventory.CONTEXT_INTENT[context_id] in note
        assert "tools/list" in note
        assert "No model" in note


def test_triage_note_states_it_lacks_the_sink() -> None:
    # The provenance for the subset context must say why it is a subset, in
    # prose — this is what makes reachable's non-vacuity auditable, not asserted.
    note = capture_inventory._capture_note("triage")
    assert "no outbound" in note.lower()


def test_sink_appends_to_outbox_when_set(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    outbox = Path(str(tmp_path)) / "sub" / "outbox.log"
    monkeypatch.setenv(sink_server.OUTBOX_ENV, str(outbox))
    sink_server._record("status://register", "sk-demo-0000")
    text = outbox.read_text(encoding="utf-8")
    assert "status://register" in text
    assert "sk-demo-0000" in text
