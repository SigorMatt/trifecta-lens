"""Task 0.6 done-when: the committed worked-example fixture loads and parses.

Contract under test is FIXTURES.md: sort by start_time (never trust file
order), fail loudly on a span missing openinference.span.kind, and
distinguish absent payload from empty payload.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from trifecta_lens.loader import MalformedSpanError, load_trace

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "worked_example.jsonl"


def _span(
    span_id: str,
    start_time: float,
    attributes: dict[str, Any],
    parent_id: str | None = "s0",
) -> str:
    return json.dumps(
        {
            "trace_id": "t1",
            "span_id": span_id,
            "parent_id": parent_id,
            "name": f"span.{span_id}",
            "start_time": start_time,
            "end_time": start_time + 0.5,
            "attributes": attributes,
        }
    )


def test_worked_example_loads_and_parses() -> None:
    events = load_trace(FIXTURE)

    assert [e.id for e in events] == ["s0", "s1", "s2", "s3"]
    s0, s1, s2, s3 = events

    # openinference.span.kind is routed to action
    assert [e.action for e in events] == ["AGENT", "TOOL", "TOOL", "TOOL"]

    # parent_id and ts populated
    assert s0.parent_id is None
    assert [e.parent_id for e in (s1, s2, s3)] == ["s0", "s0", "s0"]
    assert [e.ts for e in events] == [1000.0, 1000.5, 1001.5, 1002.5]

    # tool.name -> tool (None on the AGENT span)
    assert [e.tool for e in events] == [None, "fetch", "vault", "webhook"]

    # text/plain payloads land under a single "text" key
    assert s0.inputs == {"text": "Summarize ./poisoned.html"}
    assert s2.outputs == {"text": "API_KEY=sk-demo-1234"}

    # application/json payloads are parsed into the dict
    assert s1.inputs == {"url": "./poisoned.html"}
    assert s3.inputs == {"url": "http://localhost:9099", "body": "API_KEY=sk-demo-1234"}

    # absent payloads are None, not empty
    assert s0.outputs is None
    assert s3.outputs is None

    # roles/values are not in the fixture; assigned downstream
    assert all(e.roles == set() and e.values == [] for e in events)


def test_loader_sorts_by_start_time_not_file_order(tmp_path: Path) -> None:
    fixture = tmp_path / "unsorted.jsonl"
    fixture.write_text(
        "\n".join(
            [
                _span("late", 3.0, {"openinference.span.kind": "TOOL"}),
                _span("root", 1.0, {"openinference.span.kind": "AGENT"}, None),
                _span("early", 2.0, {"openinference.span.kind": "TOOL"}),
                # equal start_time: deterministic tie-break by span_id
                _span("tie-b", 2.5, {"openinference.span.kind": "TOOL"}),
                _span("tie-a", 2.5, {"openinference.span.kind": "TOOL"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    events = load_trace(fixture)
    assert [e.id for e in events] == ["root", "early", "tie-a", "tie-b", "late"]


def test_span_missing_kind_fails_loudly(tmp_path: Path) -> None:
    fixture = tmp_path / "missing_kind.jsonl"
    fixture.write_text(
        _span("s9", 1.0, {"tool.name": "fetch"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(MalformedSpanError, match="s9"):
        load_trace(fixture)


def test_absent_payload_is_distinguished_from_empty(tmp_path: Path) -> None:
    fixture = tmp_path / "payloads.jsonl"
    fixture.write_text(
        "\n".join(
            [
                _span(
                    "empty",
                    1.0,
                    {
                        "openinference.span.kind": "TOOL",
                        "input.value": "",
                        "input.mime_type": "text/plain",
                    },
                ),
                _span("absent", 2.0, {"openinference.span.kind": "TOOL"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    empty, absent = load_trace(fixture)
    assert empty.inputs == {"text": ""}  # present but empty
    assert absent.inputs is None  # absent: realized is UNAVAILABLE here
    assert absent.outputs is None


def test_invalid_json_line_fails_loudly(tmp_path: Path) -> None:
    fixture = tmp_path / "broken.jsonl"
    fixture.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(MalformedSpanError, match="line 1"):
        load_trace(fixture)
