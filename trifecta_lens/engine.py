"""The property automaton, run over the trace event graph (DESIGN.md §§2-3).

Stage 2. The engine sees **labeled events only** — never JSONL, never
OpenInference attribute keys, never a tool name it was taught to care about.
Coverage is changed by relabeling (the catalog), never by editing this file
(CLAUDE.md invariant 2).

Shape: an **incremental fold** (DESIGN.md §6). Events are consumed one at a
time, in order, updating `(legs seen, taint register)` and yielding a finding
the moment one is derivable. There is no backward pass and no requirement that
the trace be complete — batch is simply the same fold over a closed file, and
the lattice's monotonicity means a yielded finding is never retracted.

Acceptance (SPEC.md §3, DESIGN.md §2). On a `sink:exfil` event whose inputs
carry a tainted value verbatim:

  - `exfil_trifecta`          if the `untrusted_source` leg is in the ancestry
  - `sensitive_to_exfil_sink` if it is not

One finding per accepting sink, at the strongest family that accepts. Both
require the sensitive leg: exfil is about sensitive data leaving, so a run with
no sensitive value at the sink is not an exfil finding at any strength.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Final

from trifecta_lens.extraction import EXTRACTION, ExtractionConfig
from trifecta_lens.findings import TIER_REALIZED, Finding, Leg
from trifecta_lens.labeling import note_for_role
from trifecta_lens.model import Event, Value
from trifecta_lens.roles import (
    SENSITIVE_DATA,
    SINK_EXFIL,
    TAINT_BEARING,
    UNTRUSTED_SOURCE,
    Role,
)
from trifecta_lens.taint import extract_values, mask, normalize, value_in_payload

FAMILY_TRIFECTA: Final[str] = "exfil_trifecta"
FAMILY_TWO_LEG: Final[str] = "sensitive_to_exfil_sink"

#: The exfil legs, in the order a finding reports them.
_EXFIL_LEGS: Final[tuple[Role, ...]] = (UNTRUSTED_SOURCE, SENSITIVE_DATA, SINK_EXFIL)

SUMMARY: Final[str] = "tainted data observed reaching {sink}"

SCOPE: Final[str] = (
    "verbatim taint only (SPEC.md §6): a value that was encoded, split, "
    "summarized or paraphrased between source and sink does not match, and so "
    "would not appear here. Absence of a finding is not evidence of absence of "
    "a flow."
)

NOTE_TRIFECTA: Final[str] = (
    "all three legs observed in this trace: untrusted_source, sensitive_data, "
    "and sink:exfil. This states that tainted data was observed reaching the "
    "sink; it does not assert that the untrusted content drove the action."
)

NOTE_TWO_LEG: Final[str] = (
    "the untrusted_source leg was not observed in this trace, so this is not a "
    "trifecta finding: it is the lesser result that sensitive data was observed "
    "reaching an outbound sink. It does not claim untrusted content was present."
)


@dataclass(frozen=True)
class _Tainted:
    """One value in the register, and where it entered the run."""

    value: Value
    origin: str
    origin_ts: float
    roles: frozenset[Role]


def _summary_for(event: Event) -> str:
    return SUMMARY.format(sink=event.tool or event.actor)


def _leg(role: Role, event: Event) -> Leg:
    return Leg(role=role, event=event.id, tool=event.tool, note=note_for_role(role))


def _accept(
    sink: Event,
    register: dict[str, _Tainted],
    legs_seen: dict[Role, Event],
    seen: dict[str, Event],
    config: ExtractionConfig,
) -> Finding | None:
    """The guarded accepting transition. ``None`` when the machine does not accept.

    ``register``, ``legs_seen`` and ``seen`` reflect strictly-earlier events —
    that is the path's ancestry. Symbols advance the state; **data admits
    acceptance** (DESIGN.md §2).
    """
    # The guard: some tainted value occurs verbatim in this sink's inputs.
    matched = [
        t for t in register.values()
        if value_in_payload(t.value, sink.inputs, config)
    ]

    # Exfil is about SENSITIVE data leaving. A value that reached the sink but
    # originated only at an untrusted source is not an exfil finding at any
    # strength (it is the action-hijack family's territory — SPEC.md §3).
    sensitive = [t for t in matched if SENSITIVE_DATA in t.roles]
    if not sensitive:
        return None

    # The sensitive leg is the event that produced the matched value. When a
    # value was re-read (the anchor reads the vault twice), the most recent read
    # is the one on the path to this sink; ties break on id, so it is stable.
    origin = max(sensitive, key=lambda t: (t.origin_ts, t.origin))
    sensitive_event = seen[origin.origin]

    source_event = legs_seen.get(UNTRUSTED_SOURCE)
    family = FAMILY_TRIFECTA if source_event is not None else FAMILY_TWO_LEG

    path_events = [sensitive_event, sink]
    if source_event is not None:
        path_events.insert(0, source_event)
    path_events.sort(key=lambda e: (e.ts, e.id))

    legs = tuple(
        _leg(role, event)
        for role, event in (
            (UNTRUSTED_SOURCE, source_event),
            (SENSITIVE_DATA, sensitive_event),
            (SINK_EXFIL, sink),
        )
        if event is not None
    )
    observed = {leg.role for leg in legs}

    return Finding(
        family=family,
        tier=TIER_REALIZED,
        summary=_summary_for(sink),
        sink_event=sink.id,
        sink_tool=sink.tool,
        path=tuple(e.id for e in path_events),
        legs=legs,
        legs_observed=tuple(r for r in _EXFIL_LEGS if r in observed),
        legs_not_observed=tuple(r for r in _EXFIL_LEGS if r not in observed),
        masked_values=tuple(sorted({mask(t.value) for t in sensitive})),
        note=NOTE_TRIFECTA if family == FAMILY_TRIFECTA else NOTE_TWO_LEG,
        scope=SCOPE,
        detected_under=config.to_dict(),
    )


def detect_realized(
    events: Iterable[Event], config: ExtractionConfig = EXTRACTION
) -> Iterator[Finding]:
    """Fold the labeled event stream, yielding realized findings as they are found.

    Events must arrive in the loader's deterministic order (sorted by
    ``(ts, id)``); the fold treats everything already consumed as the current
    event's ancestry.
    """
    register: dict[str, _Tainted] = {}
    legs_seen: dict[Role, Event] = {}
    seen: dict[str, Event] = {}

    for event in events:
        # 1. Accept first: the ancestry is everything strictly before this event,
        #    so a sink can never be tainted by its own payload.
        if SINK_EXFIL in event.roles:
            finding = _accept(event, register, legs_seen, seen, config)
            if finding is not None:
                yield finding

        # 2. Extend the register with values this event contributes.
        taint_roles = event.roles & TAINT_BEARING
        if taint_roles:
            for value in extract_values(event, config):
                register[normalize(value)] = _Tainted(
                    value=value,
                    origin=event.id,
                    origin_ts=event.ts,
                    roles=frozenset(taint_roles),
                )

        # 3. Advance the leg lattice. Monotone: legs only accumulate.
        for role in event.roles:
            legs_seen[role] = event
        seen[event.id] = event
