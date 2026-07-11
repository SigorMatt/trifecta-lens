"""demo/spans.py — OpenInference span recorder (payload-level, flat JSONL).

Emits one span per line using the OpenInference semantic-convention attribute
keys (``openinference.span.kind``, ``tool.name``, ``input.value`` /
``input.mime_type``, ``output.value`` / ``output.mime_type``) in the
*simplified flat* shape defined by FIXTURES.md.

The flat shape is deliberate. The v1 ingester (task 1.3) parses exactly this
shape; the full OTLP nested-attribute exporter output is Phase 2+ (FIXTURES.md).
Recording the flat shape here means the human-captured trace loads through the
core loader unchanged — no adapter, no rewrite. See the plumbing test in
``tests/test_demo_harness.py`` for the round-trip proof.

This module has no network dependency and no model dependency; it is a pure
serializer over values the agent already holds.
"""

from __future__ import annotations

import itertools
import json
from typing import Any, TextIO

_JSON_MIME = "application/json"
_TEXT_MIME = "text/plain"


def _payload(value: Any) -> tuple[str, str]:
    """Serialize a payload to ``(value, mime_type)`` per FIXTURES.md.

    Strings are stored verbatim as ``text/plain``; anything else (tool argument
    dicts) is JSON-encoded as ``application/json`` so the loader parses it back
    into a dict. ``sort_keys`` keeps the emitted line stable for a given input.
    """
    if isinstance(value, str):
        return value, _TEXT_MIME
    return json.dumps(value, sort_keys=True), _JSON_MIME


class SpanRecorder:
    """Writes OpenInference spans to an open text stream, one JSON object/line.

    Span ids are allocated in order (``s0``, ``s1``, …); only equality matters
    (FIXTURES.md). Records are flushed as written, matching the append-stream
    spirit — file order is never relied on for causality, since the loader sorts
    by ``start_time`` and rebuilds ancestry from ``parent_id``.
    """

    def __init__(self, out: TextIO, trace_id: str) -> None:
        self._out = out
        self._trace_id = trace_id
        self._ids = itertools.count()

    def new_span_id(self) -> str:
        return f"s{next(self._ids)}"

    def _write(self, span: dict[str, Any]) -> None:
        self._out.write(json.dumps(span, sort_keys=True))
        self._out.write("\n")
        self._out.flush()

    def agent_span(
        self,
        *,
        span_id: str,
        name: str,
        user_input: str,
        start_time: float,
        end_time: float,
        status: str = "OK",
    ) -> None:
        """Record the root AGENT span that wraps the whole run."""
        attributes: dict[str, Any] = {
            "openinference.span.kind": "AGENT",
            "input.value": user_input,
            "input.mime_type": _TEXT_MIME,
        }
        self._write(
            {
                "trace_id": self._trace_id,
                "span_id": span_id,
                "parent_id": None,
                "name": name,
                "start_time": start_time,
                "end_time": end_time,
                "status": status,
                "attributes": attributes,
            }
        )

    def tool_span(
        self,
        *,
        name: str,
        tool: str,
        inputs: Any,
        outputs: Any | None,
        parent_id: str,
        start_time: float,
        end_time: float,
        status: str = "OK",
    ) -> str:
        """Record one TOOL span and return its allocated span id."""
        span_id = self.new_span_id()
        input_value, input_mime = _payload(inputs)
        attributes: dict[str, Any] = {
            "openinference.span.kind": "TOOL",
            "tool.name": tool,
            "input.value": input_value,
            "input.mime_type": input_mime,
        }
        if outputs is not None:
            output_value, output_mime = _payload(outputs)
            attributes["output.value"] = output_value
            attributes["output.mime_type"] = output_mime
        self._write(
            {
                "trace_id": self._trace_id,
                "span_id": span_id,
                "parent_id": parent_id,
                "name": name,
                "start_time": start_time,
                "end_time": end_time,
                "status": status,
                "attributes": attributes,
            }
        )
        return span_id
