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
from itertools import pairwise
from typing import Final

from trifecta_lens.extraction import EXTRACTION, ExtractionConfig
from trifecta_lens.findings import (
    BASIS_CAUSAL,
    BASIS_MIXED,
    BASIS_TEMPORAL,
    TIER_POSTURE,
    TIER_REACHABLE,
    TIER_REALIZED,
    CapabilityFinding,
    CapabilityLeg,
    Finding,
    Leg,
    PathEdge,
    ToolCitation,
)
from trifecta_lens.model import Event, LabeledContext, LabeledStack, Value
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


@dataclass(frozen=True)
class Family:
    """One acceptance predicate of the fixed automaton (SPEC.md §3, DESIGN.md §2)."""

    id: str
    #: The legs that must all be present for this family to accept.
    required: frozenset[Role]
    #: The sink role that terminates its path.
    sink: Role


#: **The acceptance predicate of the machine, and the whole of it.** Ordered
#: STRONGEST FIRST — that ordering is what "report at the strongest family that
#: accepts" means, and it is why a two-leg finding can never be dressed up as a
#: trifecta.
#:
#: The two families are not two machines. Two-leg is the trifecta's predicate with
#: one conjunct dropped (`SPEC.md` §3.1): same states, same lattice, same guard.
#: Because `{SRC,SEN,SINK} ⊃ {SEN,SINK}`, every trifecta-accepting run also
#: satisfies two-leg — so the families form a lattice too, and `trifecta ⊆ two-leg`
#: holds at every tier (`DESIGN.md` §3).
#:
#: The action-hijack family (`sink:impact`) is deliberately ABSENT: it is
#: fast-follow (SPEC.md §3, ROADMAP Phase 4). The catalog already labels impact
#: sinks; no v1 family accepts on them. Adding the family later is adding a row
#: here — the states and the guard do not move.
FAMILIES: Final[tuple[Family, ...]] = (
    Family(
        id=FAMILY_TRIFECTA,
        required=frozenset({UNTRUSTED_SOURCE, SENSITIVE_DATA, SINK_EXFIL}),
        sink=SINK_EXFIL,
    ),
    Family(
        id=FAMILY_TWO_LEG,
        required=frozenset({SENSITIVE_DATA, SINK_EXFIL}),
        sink=SINK_EXFIL,
    ),
)


def satisfied_families(legs: frozenset[Role]) -> tuple[Family, ...]:
    """Every family whose legs are all present in ``legs``, strongest first.

    This one function is the automaton's acceptance condition, and **all three
    tiers call it** — realized over a trace path's ancestry, reachable over one
    context's exposed roles, posture over the union. That is what makes
    ``realized ⊆ reachable ⊆ posture`` structural (`DESIGN.md` §3): the tiers differ
    only in the leg set they hand this function, and each tier's leg set is a
    superset of the tighter tier's. Nothing about containment rests on the report
    text agreeing with itself.

    Reporting takes the **first** (strongest); the full tuple is what the
    containment property is checked against, since a run that accepts the trifecta
    also accepts two-leg but is only *reported* once (SPEC.md §5).
    """
    return tuple(family for family in FAMILIES if family.required <= legs)

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


def _is_ancestor(ancestor: Event, descendant: Event, seen: dict[str, Event]) -> bool:
    """Whether the trace's own parent_id chain links ``ancestor`` to ``descendant``.

    This is the ONLY thing that earns the word "causal" — and it is a claim about
    the instrumentation's ancestry, not about intent (CLAUDE.md invariant 4).
    """
    current = descendant.parent_id
    while current is not None:
        if current == ancestor.id:
            return True
        parent = seen.get(current)
        if parent is None:
            return False
        current = parent.parent_id
    return False


def _path_edges(
    path_events: list[Event], seen: dict[str, Event]
) -> tuple[tuple[PathEdge, ...], str]:
    """Build the path's edges with their bases, and the aggregate basis.

    An edge is CAUSAL when real ancestry links its two spans, TEMPORAL when only
    ordering does. Most real traces hang every tool span off the agent root, so
    temporal is the common — and honest — answer.
    """
    edges = tuple(
        PathEdge(
            source=source.id,
            target=target.id,
            basis=(
                BASIS_CAUSAL
                if _is_ancestor(source, target, seen)
                else BASIS_TEMPORAL
            ),
        )
        for source, target in pairwise(path_events)
    )
    bases = {edge.basis for edge in edges}
    if bases == {BASIS_CAUSAL}:
        aggregate = BASIS_CAUSAL
    elif bases == {BASIS_TEMPORAL}:
        aggregate = BASIS_TEMPORAL
    else:
        aggregate = BASIS_MIXED
    return edges, aggregate


def _leg(role: Role, event: Event) -> Leg:
    # The note is read by ROLE, never by tool: the catalog (Stage 1) already
    # attached its rationale to the event, so the engine cites the entry without
    # ever learning what a "vault" is (DESIGN.md §5).
    return Leg(
        role=role, event=event.id, tool=event.tool, note=event.role_notes.get(role, "")
    )


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

    # The acceptance predicate — the SAME one the capability tiers run. The legs
    # on this path are the sensitive origin, the sink we are standing on, and the
    # untrusted source if the ancestry carried one. Report the strongest family
    # that accepts; there is always at least one, since `sensitive` is non-empty
    # and this event is a sink.
    legs_present = frozenset(
        {SENSITIVE_DATA, SINK_EXFIL}
        | ({UNTRUSTED_SOURCE} if source_event is not None else set())
    )
    accepted = satisfied_families(legs_present)
    if not accepted:
        return None
    family = accepted[0].id

    path_events = [sensitive_event, sink]
    if source_event is not None:
        path_events.insert(0, source_event)
    path_events.sort(key=lambda e: (e.ts, e.id))

    # The sink is not yet in ``seen`` (it is the event being processed), but the
    # ancestry walk needs it to resolve the chain above it.
    ancestry = {**seen, sink.id: sink}
    edges, basis = _path_edges(path_events, ancestry)

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
        path_edges=edges,
        path_basis=basis,
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


# --- The capability tiers (tasks 2.10, 2.11) ---------------------------------
#
# Same machine, weaker input (DESIGN.md §3). Realized runs the automaton over the
# trace event graph with the taint guard ON. Drop the guard and run it over one
# agent context's exposed roles -> REACHABLE. Drop the contexts too and run it over
# the union of the whole stack -> POSTURE.
#
# Both are literally `satisfied_families(...)` again, over a leg set that comes
# from the inventory instead of from a path's ancestry. That is what makes
# `realized ⊆ reachable ⊆ posture` structural: each tier's leg set is a superset of
# the tighter tier's, so an accepting family at a tighter tier accepts at a looser
# one by construction. Nothing here re-derives the acceptance condition.

CAPABILITY_SCOPE: Final[str] = (
    "This tier reads the captured tool inventory ONLY. It never opened a payload "
    "and consulted no trace, so it cannot say whether any value moved. A finding "
    "here is a statement about what the stack CAN do, not about what it did."
)

NOTE_POSTURE: Final[str] = (
    "posture states capability, not observation: these roles exist somewhere in "
    "the captured stack. No run was observed doing this. Posture does NOT claim "
    "any single agent context can reach all of these tools — that is the reachable "
    "tier's question, and it is the tighter one. This tier overlaps ordinary "
    "static scanners and is the weakest of the three."
)

NOTE_REACHABLE: Final[str] = (
    "reachable states capability, not observation: every leg is exposed to this "
    "one agent context, so a single run could wire them together. No run was "
    "observed doing so. This is the lethal-trifecta condition as a topology — it "
    "is not evidence that any data moved."
)

SUMMARY_POSTURE: Final[str] = (
    "all legs of {family} are present in the captured stack; {sink} could receive "
    "them"
)
SUMMARY_REACHABLE: Final[str] = (
    "all legs of {family} are exposed to agent context {context!r}; a single run "
    "could wire them to {sink}"
)

_TIER_TEXT: Final[dict[str, tuple[str, str]]] = {
    TIER_POSTURE: (SUMMARY_POSTURE, NOTE_POSTURE),
    TIER_REACHABLE: (SUMMARY_REACHABLE, NOTE_REACHABLE),
}

DISCLOSURE_POSTURE: Final[str] = (
    "posture is the weakest of the three tiers and overlaps what ordinary static "
    "scanners already report. Do not read it as a path: it says the parts are in "
    "the building, not that one agent can reach them all."
)

#: The collapse case (DECISIONS.md D1). On a stack where every agent context can
#: already wire everything posture found, reachable is *necessarily* equal to
#: posture and carries no information. That is a real property of some stacks — and
#: a tier that quietly says nothing while looking like it says something is exactly
#: the tier-honesty failure the invariant exists to prevent. So we detect it and
#: say it, in the finding itself.
DISCLOSURE_COLLAPSED_SINGLE: Final[str] = (
    "reachable adds no information on this stack: it has a single agent context, "
    "so every leg posture found is co-exposed to it by definition. Here reachable "
    "and posture are the same tier — treat this finding as posture."
)
DISCLOSURE_COLLAPSED_ALL: Final[str] = (
    "reachable adds no information on this stack: every agent context exposes all "
    "the legs posture found, so no context is more restricted than the stack as a "
    "whole. Here reachable and posture coincide — treat this finding as posture."
)
DISCLOSURE_TIGHTER: Final[str] = (
    "reachable is strictly tighter than posture on this stack: {narrowed} of "
    "{total} agent contexts cannot wire this family ({names}). Posture cannot see "
    "that distinction — it only asks whether the legs exist somewhere."
)


@dataclass(frozen=True)
class ReachableCollapse:
    """Whether reachable degenerates into posture on this stack (D1)."""

    collapsed: bool
    disclosure: str
    #: The contexts that CANNOT wire what posture found — the evidence that this
    #: tier is doing work. Empty exactly when ``collapsed``.
    narrowed_contexts: tuple[str, ...]


def reachable_collapse(stack: LabeledStack) -> ReachableCollapse:
    """Detect (and word) the collapse case, so the tool can disclose it.

    Reachable has collapsed when **every** context accepts exactly what the union
    accepts — then knowing a family is reachable tells you nothing you did not
    already know from posture.

    The negation is what makes reachable worth shipping: at least one real agent
    context is narrower than the stack, so reachable can say "this one cannot do it"
    where posture must stay silent. That is *non-vacuity*, and it is a property of
    the captured stack, not of our code — which is why it is computed here and
    proven on a real inventory (D7), never asserted.
    """
    posture_families = satisfied_families(stack.posture_context().roles())
    narrowed = tuple(
        context.id
        for context in stack.contexts
        if satisfied_families(context.roles()) != posture_families
    )

    if not narrowed:
        return ReachableCollapse(
            collapsed=True,
            disclosure=(
                DISCLOSURE_COLLAPSED_SINGLE
                if len(stack.contexts) <= 1
                else DISCLOSURE_COLLAPSED_ALL
            ),
            narrowed_contexts=(),
        )
    return ReachableCollapse(
        collapsed=False,
        disclosure=DISCLOSURE_TIGHTER.format(
            narrowed=len(narrowed),
            total=len(stack.contexts),
            names=", ".join(narrowed),
        ),
        narrowed_contexts=narrowed,
    )


def _capability_legs(context: LabeledContext, roles: Iterable[Role]) -> tuple[
    CapabilityLeg, ...
]:
    """Every tool in this context supplying each required leg, in capture order."""
    return tuple(
        CapabilityLeg(
            role=role,
            tools=tuple(
                ToolCitation(tool=tool.name, note=tool.role_notes.get(role, ""))
                for tool in context.tools_with(role)
            ),
        )
        for role in roles
    )


def detect_capability(
    context: LabeledContext, tier: str, disclosure: str
) -> Iterator[CapabilityFinding]:
    """Run the automaton over one context's exposed roles, with the guard OFF.

    Posture passes the stack's union context; reachable passes each real context.
    They are the same call because they are the same question asked of a wider and
    a narrower bag of tools (SPEC.md §5).

    One finding per (family, sink tool), at the strongest family that accepts —
    exactly realized's reporting rule, so a flow is never double-counted at any
    tier.
    """
    summary_template, note = _TIER_TEXT[tier]
    exposed = context.roles()
    accepted = satisfied_families(exposed)
    if not accepted:
        return
    family = accepted[0]

    # Iterate the legs in the fixed reporting order, NOT in `family.required`'s
    # order: that is a frozenset, and frozenset iteration order depends on string
    # hashing, which is randomized per process. Reading it directly would make the
    # findings differ run-to-run — silently, and only across processes, which is the
    # worst way for a determinism invariant to break (DESIGN.md §8).
    legs = _capability_legs(context, (r for r in _EXFIL_LEGS if r in family.required))
    for sink in context.tools_with(family.sink):
        yield CapabilityFinding(
            family=family.id,
            tier=tier,
            summary=summary_template.format(
                family=family.id, context=context.id, sink=sink.name
            ),
            context=context.id,
            context_provenance=context.provenance,
            sink_tool=sink.name,
            legs=legs,
            legs_present=tuple(r for r in _EXFIL_LEGS if r in exposed),
            legs_absent=tuple(r for r in _EXFIL_LEGS if r not in exposed),
            note=note,
            scope=CAPABILITY_SCOPE,
            disclosure=disclosure,
        )


def detect_posture(stack: LabeledStack) -> Iterator[CapabilityFinding]:
    """Posture: do the legs exist ANYWHERE in the captured stack? (SPEC.md §5)

    The union of every context, with no edges and no guard — the weakest tier.
    **Never headline it**: it overlaps what ordinary static scanners already do,
    and it says nothing about whether one agent could actually reach them all.
    """
    yield from detect_capability(
        stack.posture_context(), TIER_POSTURE, DISCLOSURE_POSTURE
    )


def detect_reachable(stack: LabeledStack) -> Iterator[CapabilityFinding]:
    """Reachable: are all legs co-exposed to ONE agent context? (D1, SPEC.md §5)

    The lethal-trifecta condition proper, and the tier the tool exists to report.
    Strictly tighter than posture whenever some context is narrower than the stack:
    a context with no outbound sink yields nothing here, while the stack as a whole
    still trips posture.

    **Co-exposure is the edge relation** — not tool-I/O type compatibility, which
    would be near-vacuous (`DECISIONS.md` F2). Two tools are connected when one agent
    context can invoke both, because the model between them is a universal connector
    that will move any value anywhere. So "all legs in one context" *is* the graph
    question, and it needs no adjacency structure to answer.

    Every finding carries :func:`reachable_collapse`'s verdict, so a stack on which
    this tier is degenerate says so **in the finding**, not just in the report.
    """
    collapse = reachable_collapse(stack)
    for context in stack.contexts:
        yield from detect_capability(context, TIER_REACHABLE, collapse.disclosure)
