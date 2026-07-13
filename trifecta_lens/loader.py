"""Trace loaders: spans -> Event stream (FIXTURES.md; SPEC.md §7).

Stage 1 front-end (DESIGN.md §5): all parsing mess is confined here. The
attribute lookups are kept in one place (the ``_ATTR_*`` constants) so a second
front-end is a *new function*, not a rewrite. There are two:

* :func:`load_trace` — the Phase 1 **flat** JSONL shape (one hand-authorable span
  per line, attributes already flat).
* :func:`load_otlp_trace` — the **real OTLP/JSON** shape a real exporter emits
  (nested ``resourceSpans[].scopeSpans[].spans[]``; each attribute is
  ``{key, value:{stringValue}}``). This is task 2.7, built against the real
  Checkpoint D capture (``DECISIONS.md`` D9). It decodes the OTLP envelope into
  the same intermediate span shape :func:`load_trace` uses and shares the one
  attribute->Event mapping — the engine never learns there were two formats.

Reads local files only — never a network connection (CLAUDE.md invariant 1).
"""

import base64
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

from trifecta_lens.model import Event

# OpenInference attribute keys we key on (FIXTURES.md). Everything else is
# ignored, not an error.
_ATTR_SPAN_KIND = "openinference.span.kind"
_ATTR_TOOL_NAME = "tool.name"
_ATTR_INPUT_VALUE = "input.value"
_ATTR_INPUT_MIME = "input.mime_type"
_ATTR_OUTPUT_VALUE = "output.value"
_ATTR_OUTPUT_MIME = "output.mime_type"

_MIME_JSON = "application/json"


class MalformedSpanError(ValueError):
    """A span that violates the fixture contract — fail loudly, don't guess."""


def _parse_payload(
    attributes: dict[str, Any], value_key: str, mime_key: str, span_id: str
) -> dict[str, Any] | None:
    """Parse one payload attribute pair.

    Returns None when the payload attribute is absent — distinct from an
    empty payload, which parses to a present-but-empty value (SPEC.md §7
    degradation: absent payload means realized is UNAVAILABLE, not empty).
    """
    if value_key not in attributes:
        return None
    raw = attributes[value_key]
    if attributes.get(mime_key) == _MIME_JSON:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise MalformedSpanError(
                f"span {span_id!r}: {value_key} declared {_MIME_JSON} "
                f"but does not parse as JSON: {exc}"
            ) from exc
        if isinstance(parsed, dict):
            return parsed
        # JSON that is not an object still needs a stable home in the dict.
        return {"value": parsed}
    return {"text": raw}


def _event_from_span(span: dict[str, Any], line_no: int) -> Event:
    try:
        span_id = span["span_id"]
        parent_id = span.get("parent_id")
        name = span["name"]
        start_time = span["start_time"]
        attributes = span.get("attributes", {})
    except (KeyError, TypeError) as exc:
        raise MalformedSpanError(f"line {line_no}: span missing {exc}") from exc

    kind = attributes.get(_ATTR_SPAN_KIND)
    if not kind:
        raise MalformedSpanError(
            f"span {span_id!r} (line {line_no}) has no {_ATTR_SPAN_KIND!r} attribute.\n"
            "v1 reads ONE semantic convention: OpenInference (SPEC.md §7.3). Two "
            "envelopes carry it — flat JSONL and OTLP/JSON — and both must name the "
            "span kind.\n"
            "If your spans carry 'gen_ai.*' keys, this is an OTel GenAI trace: a "
            "different convention, and NOT supported. Your trace is not malformed; we "
            "do not speak it. A second convention lands only when a real captured "
            "trace of it is in hand (DECISIONS.md D9/D12) — we will not guess at a "
            "format we have never seen."
        )

    tool = attributes.get(_ATTR_TOOL_NAME)
    return Event(
        id=span_id,
        parent_id=parent_id,
        ts=float(start_time),
        # The fixture does not carry an explicit actor; the tool acted when
        # one is named, otherwise the span's own name identifies the actor.
        actor=tool if tool is not None else name,
        action=kind,
        tool=tool,
        inputs=_parse_payload(attributes, _ATTR_INPUT_VALUE, _ATTR_INPUT_MIME, span_id),
        outputs=_parse_payload(
            attributes, _ATTR_OUTPUT_VALUE, _ATTR_OUTPUT_MIME, span_id
        ),
        roles=set(),
        values=[],
    )


#: The OpenInference span kind that marks an agent. A tool span's nearest ancestor of
#: this kind is the agent that ran it (D15).
_KIND_AGENT = "AGENT"


def resolve_agents(events: list[Event]) -> list[Event]:
    """Attach each event's agent: its nearest ancestor span of kind ``AGENT`` (D15).

    **No new format, no new attribute, no new convention.** The information was already
    in every trace we load — ``parent_id`` and ``openinference.span.kind`` are both in
    the six keys we read (``SPEC.md`` §7.3). Nothing had ever looked at them together.

    That omission was not cosmetic. The engine folds a trace carrying **one** taint set
    and no notion of an agent, so a secret read by agent A and emitted by agent B has
    **always** fired — while ``SPEC.md`` §8 listed cross-agent multi-hop as out of
    scope, and the finding printed as though one agent did both. We shipped the
    capability, denied it, and reported it wrong.

    The agent's identity is the AGENT span's **id** — opaque, and deliberately *not* an
    inventory context id. The trace and the inventory name agents in different
    vocabularies; guessing a mapping between them would invent an identity neither
    artifact carries, which is exactly the mistake D14 was.
    """
    by_id = {event.id: event for event in events}

    def agent_of(event: Event) -> str | None:
        current = event.parent_id
        seen: set[str] = set()  # a malformed trace may cycle; refuse to hang on it
        while current is not None and current not in seen:
            seen.add(current)
            parent = by_id.get(current)
            if parent is None:
                return None
            if parent.action == _KIND_AGENT:
                return parent.id
            current = parent.parent_id
        return None

    return [replace(event, agent=agent_of(event)) for event in events]


def load_trace(path: str | Path) -> list[Event]:
    """Load one JSONL trace fixture into a deterministically ordered Event list.

    Events are sorted by (start_time, span_id) — file order is never trusted
    for causality, and the tie-break rule is a determinism invariant
    (DESIGN.md §8).
    """
    events: list[Event] = []
    text = Path(path).read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            span = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MalformedSpanError(f"line {line_no}: invalid JSON: {exc}") from exc
        if not isinstance(span, dict):
            raise MalformedSpanError(f"line {line_no}: span is not a JSON object")
        events.append(_event_from_span(span, line_no))
    events.sort(key=lambda e: (e.ts, e.id))
    return resolve_agents(events)


# --- OTLP/JSON front-end (task 2.7) -----------------------------------------
#
# Real OpenTelemetry exporters emit OTLP, whose JSON form nests spans under
# resource/scope and encodes every attribute as ``{key, value:{<type>Value}}``.
# We decode that envelope into the SAME intermediate span dict the flat loader
# consumes, then hand each to ``_event_from_span`` — so the attribute->Event
# mapping, the payload-vs-absent distinction, and the span-kind requirement are
# defined once, not twice (FIXTURES.md: a new front-end, not a rewrite).

# OTLP status codes (opentelemetry.proto.trace.v1). Only ERROR is not "OK".
_OTLP_STATUS_ERROR = "STATUS_CODE_ERROR"

# OTLP AnyValue scalar variants we read (camelCase, as MessageToDict emits).
# v1 keys only on string attributes; the numeric/bool variants are decoded for
# completeness so an unexpected type does not silently vanish.
_ANYVALUE_SCALARS = ("stringValue", "intValue", "boolValue", "doubleValue")


def _hex_id(raw: str | None) -> str | None:
    """Decode an OTLP/JSON base64 span/trace id to hex; empty/absent -> None.

    Only equality matters for ids (FIXTURES.md); hex is the conventional,
    readable form, and ``spanId``/``parentSpanId`` decode consistently so the
    parent chain still links.
    """
    if not raw:
        return None
    try:
        return base64.b64decode(raw).hex()
    except (ValueError, TypeError) as exc:
        raise MalformedSpanError(f"span id {raw!r} is not valid base64: {exc}") from exc


def _anyvalue(value: Any) -> Any:
    """Extract the scalar from an OTLP ``AnyValue`` object."""
    if not isinstance(value, dict):
        return None
    for variant in _ANYVALUE_SCALARS:
        if variant in value:
            return value[variant]
    return None


def _flatten_attributes(raw_attributes: Any, span_id: str) -> dict[str, Any]:
    """Turn an OTLP ``attributes`` array into the flat ``{key: scalar}`` dict."""
    if raw_attributes is None:
        return {}
    if not isinstance(raw_attributes, list):
        raise MalformedSpanError(
            f"span {span_id!r}: OTLP 'attributes' is not an array"
        )
    flat: dict[str, Any] = {}
    for attr in raw_attributes:
        if not isinstance(attr, dict) or "key" not in attr:
            raise MalformedSpanError(
                f"span {span_id!r}: malformed OTLP attribute {attr!r}"
            )
        flat[attr["key"]] = _anyvalue(attr.get("value"))
    return flat


def _otlp_span_to_intermediate(span: dict[str, Any]) -> dict[str, Any]:
    """Decode one OTLP span into the flat shape ``_event_from_span`` reads."""
    span_id = _hex_id(span.get("spanId"))
    if span_id is None:
        raise MalformedSpanError("OTLP span missing 'spanId'")
    try:
        start_nanos = int(span["startTimeUnixNano"])
    except (KeyError, ValueError, TypeError) as exc:
        raise MalformedSpanError(
            f"span {span_id!r}: missing/invalid 'startTimeUnixNano'"
        ) from exc
    status = span.get("status") or {}
    return {
        "span_id": span_id,
        "parent_id": _hex_id(span.get("parentSpanId")),
        "name": span.get("name", span_id),
        "start_time": start_nanos / 1e9,
        "status": "ERROR" if status.get("code") == _OTLP_STATUS_ERROR else "OK",
        "attributes": _flatten_attributes(span.get("attributes"), span_id),
    }


def _iter_otlp_spans(document: Any) -> Iterator[dict[str, Any]]:
    """Walk resourceSpans[].scopeSpans[].spans[] of an OTLP/JSON document."""
    if not isinstance(document, dict):
        raise MalformedSpanError("OTLP document is not a JSON object")
    for resource_spans in document.get("resourceSpans", []):
        for scope_spans in resource_spans.get("scopeSpans", []):
            yield from scope_spans.get("spans", [])


def load_otlp_trace(path: str | Path) -> list[Event]:
    """Load a real OTLP/JSON trace document into a deterministic Event list.

    Same output contract as :func:`load_trace` (Events sorted by ``(ts, id)``),
    so the labeling, taint and engine stages run on it unchanged: only the
    front-end differs (FIXTURES.md). MCP tool names arrive **server-qualified**
    (``<server>__<tool>``) in ``tool.name`` and are carried through as
    ``Event.tool`` verbatim (SPEC.md §2).
    """
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    events = [
        _event_from_span(_otlp_span_to_intermediate(span), line_no=i)
        for i, span in enumerate(_iter_otlp_spans(document), start=1)
    ]
    events.sort(key=lambda e: (e.ts, e.id))
    return resolve_agents(events)
