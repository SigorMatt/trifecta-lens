"""Trace-fixture loader: JSONL spans -> Event stream (FIXTURES.md; SPEC.md §7).

Stage 1 front-end (DESIGN.md §5): all parsing mess is confined here. The
attribute lookups are kept in one place (the ``_ATTR_*`` constants) so the
Phase 2+ OTLP adapter is a new front-end, not a rewrite.

Reads local files only — never a network connection (CLAUDE.md invariant 1).
"""

import json
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
            f"span {span_id!r} (line {line_no}) is missing required "
            f"attribute {_ATTR_SPAN_KIND!r} — malformed fixture"
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
    return events
