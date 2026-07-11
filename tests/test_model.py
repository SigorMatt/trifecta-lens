"""Task 0.5 done-when: the Event model round-trips a hand-written event."""

import json

from trifecta_lens.model import Event


def _hand_written_event() -> Event:
    return Event(
        id="s2",
        parent_id="s0",
        ts=1001.5,
        actor="vault",
        action="TOOL",
        tool="vault",
        inputs={"path": "secret.txt"},
        outputs={"text": "API_KEY=sk-demo-1234"},
        roles={"sensitive_data"},
        values=["API_KEY=sk-demo-1234"],
    )


def test_event_round_trips_through_json() -> None:
    event = _hand_written_event()
    payload = json.dumps(event.to_dict(), sort_keys=True)
    assert Event.from_dict(json.loads(payload)) == event


def test_event_serialization_is_deterministic() -> None:
    event = _hand_written_event()
    first = json.dumps(event.to_dict(), sort_keys=True)
    second = json.dumps(event.to_dict(), sort_keys=True)
    assert first == second


def test_optional_fields_round_trip_as_none() -> None:
    event = Event(
        id="s0",
        parent_id=None,
        ts=1000.0,
        actor="agent.run",
        action="AGENT",
        tool=None,
        inputs=None,
        outputs=None,
        roles=set(),
        values=[],
    )
    assert Event.from_dict(event.to_dict()) == event
