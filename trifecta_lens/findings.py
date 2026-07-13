"""The findings output contract (SPEC.md §7, DESIGN.md §6).

Findings are an **append-stream**: NDJSON, one finding object per line, keys
sorted, written the moment each one is found — never a monolithic end-of-run
document. That is what keeps a future streaming front-end additive rather than a
redesign, and it is why :func:`write_ndjson` takes an *iterator* and flushes per
line instead of taking a list.

Emission goes to a text stream — stdout or a file. Core never delivers a finding
over the network (`DESIGN.md` §7): that is permanently out, not merely parked.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Final, Protocol, TextIO

from trifecta_lens.roles import Role

#: The findings NDJSON schema version (SPEC.md §7.1). This is a **public
#: contract**: it rides in-band on every finding line because the append-stream
#: has no header, so a consumer parsing one line must be able to tell which
#: schema it is reading. Adding an optional field is a minor bump and consumers
#: must ignore unknown fields; removing/renaming/retyping is a major bump. The
#: frozen key sets are enforced by `tests/test_findings_schema.py` against
#: `schema/findings.schema.json`, so a field cannot move without this moving too.
SCHEMA_VERSION: Final[str] = "1.1"

#: The three tiers (SPEC.md §5). Kept explicit so a lower tier can never silently
#: inherit realized's language or weight (CLAUDE.md invariant 3).
TIER_REALIZED: Final[str] = "realized"
TIER_REACHABLE: Final[str] = "reachable"
TIER_POSTURE: Final[str] = "posture"

#: Weakest first. A tier's *strength* is fixed here and nowhere else.
TIERS: Final[tuple[str, ...]] = (TIER_POSTURE, TIER_REACHABLE, TIER_REALIZED)

#: How an edge in the reported path is justified (SPEC.md §5, DECISIONS.md D5).
#: CAUSAL: the trace's own parent_id chain links the two spans.
#: TEMPORAL: only ordering links them -- one was observed before the other. We
#: did NOT observe that the first fed the second, and must not draw an arrow
#: that implies we did.
BASIS_CAUSAL: Final[str] = "causal"
BASIS_TEMPORAL: Final[str] = "temporal"
BASIS_MIXED: Final[str] = "mixed"


@dataclass(frozen=True)
class PathEdge:
    """One step of the reported path, and what justifies it."""

    source: str
    target: str
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {"basis": self.basis, "from": self.source, "to": self.target}


@dataclass(frozen=True)
class Leg:
    """One observed leg of a path, citing what assigned the role (SPEC.md §4).

    ``catalog_entry`` is the id of the entry that made the call — the thing the user
    edits (or overrides in a `--catalog` overlay) if we got it wrong. A finding that
    justifies itself but does not say where to fix it sends the user into the source.
    """

    role: Role
    event: str
    tool: str | None
    note: str
    catalog_entry: str = ""
    #: The AGENT span this leg ran under (``loader.resolve_agents``). ``None`` when the
    #: trace names no agent above it. Two legs with different agents mean the flow
    #: CROSSED an agent boundary — a materially different claim, and one this finding
    #: used to hide (D15).
    agent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "catalog_entry": self.catalog_entry,
            "event": self.event,
            "note": self.note,
            "role": self.role,
            "tool": self.tool,
        }


@dataclass(frozen=True)
class Finding:
    """One finding. Serializes to exactly one NDJSON line."""

    family: str
    tier: str
    summary: str
    sink_event: str
    sink_tool: str | None
    path: tuple[str, ...]
    #: The path's edges, each carrying its own basis, and the aggregate basis.
    #: Required, never optional: an unlabelled arrow is read as causation
    #: (DECISIONS.md D5).
    path_edges: tuple[PathEdge, ...]
    path_basis: str
    legs: tuple[Leg, ...]
    legs_observed: tuple[Role, ...]
    legs_not_observed: tuple[Role, ...]
    masked_values: tuple[str, ...]
    note: str
    scope: str
    #: The declared extraction parameters that bounded this search (SPEC.md
    #: §6.1). Present on every finding so "what could this even have seen?" is
    #: answerable from the finding alone.
    detected_under: dict[str, Any]
    #: The distinct AGENT spans this path ran across, in path order (D15). More than
    #: one means the flow crossed an agent boundary — one agent read the value, another
    #: sent it. The engine has always detected these (it folds one trace with one taint
    #: set and no notion of an agent) and the finding never said so.
    #:
    #: It matters twice over. It is a bigger claim — and it is the case the REACHABLE
    #: tier is structurally unable to corroborate, because reachable asks whether ONE
    #: context holds every leg, and here by definition none does.
    agents: tuple[str, ...] = ()

    @property
    def crosses_agents(self) -> bool:
        """Whether this flow moved between agents (D15)."""
        return len(self.agents) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "agents": list(self.agents),
            "crosses_agents": self.crosses_agents,
            "detected_under": dict(self.detected_under),
            "family": self.family,
            "legs": [leg.to_dict() for leg in self.legs],
            "legs_not_observed": list(self.legs_not_observed),
            "legs_observed": list(self.legs_observed),
            "masked_values": list(self.masked_values),
            "note": self.note,
            "path": list(self.path),
            "path_basis": self.path_basis,
            "path_edges": [edge.to_dict() for edge in self.path_edges],
            "schema_version": SCHEMA_VERSION,
            "scope": self.scope,
            "sink": {"event": self.sink_event, "tool": self.sink_tool},
            "summary": self.summary,
            "tier": self.tier,
        }

    def to_json_line(self) -> str:
        """One NDJSON line. ``sort_keys=True`` is the determinism contract."""
        return json.dumps(self.to_dict(), sort_keys=True)


# --- The capability tiers (posture, reachable) ------------------------------
#
# A capability finding is a DIFFERENT TYPE from a realized one, deliberately.
#
# `CLAUDE.md` invariant 3 says a lower tier must never borrow a higher tier's
# severity, colour or language. The strongest way to guarantee that is to make it
# unsayable: this dataclass has no `path`, no `masked_values`, no `path_basis` and
# no `legs_observed` — because posture and reachable observed NOTHING. They read a
# captured inventory; they never opened a payload. There is no field in which to
# accidentally write the stronger claim, and no code path by which realized's
# evidence can leak into a tier that has none.
#
# What they carry instead is the honest currency of a capability claim: which
# context, which tools carry which leg, and why the catalog said so.


@dataclass(frozen=True)
class ToolCitation:
    """One tool carrying a leg, and the catalog entry that assigned it."""

    tool: str
    note: str
    catalog_entry: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_entry": self.catalog_entry,
            "note": self.note,
            "tool": self.tool,
        }


@dataclass(frozen=True)
class CapabilityLeg:
    """One leg of a capability finding: a role, and every tool that supplies it.

    Plural, unlike a realized :class:`Leg` — a context may expose eight tools that
    can read a file. Naming them all is the point: the user's next move is to look
    at that list and decide which ones actually needed to be there.
    """

    role: Role
    tools: tuple[ToolCitation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "tools": [t.to_dict() for t in self.tools]}


@dataclass(frozen=True)
class CapabilityFinding:
    """A posture or reachable finding. Serializes to exactly one NDJSON line."""

    family: str
    tier: str
    summary: str
    #: The agent context this is a claim about. For posture, the synthetic union of
    #: every context — which announces itself as such, in both the id and the note.
    context: str
    context_provenance: str
    sink_tool: str
    legs: tuple[CapabilityLeg, ...]
    legs_present: tuple[Role, ...]
    legs_absent: tuple[Role, ...]
    note: str
    scope: str
    #: What this tier is worth **on this particular stack** (D1). `note` is fixed
    #: text about what the tier means; this is a claim about the stack in hand —
    #: above all, whether reachable has collapsed into posture here. It rides on the
    #: finding rather than sitting only in the report, because a consumer reading
    #: the NDJSON alone would otherwise take a collapsed reachable tier at face
    #: value.
    disclosure: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": {"id": self.context, "provenance": self.context_provenance},
            "disclosure": self.disclosure,
            "family": self.family,
            "legs": [leg.to_dict() for leg in self.legs],
            "legs_absent": list(self.legs_absent),
            "legs_present": list(self.legs_present),
            "note": self.note,
            "schema_version": SCHEMA_VERSION,
            "scope": self.scope,
            "sink": {"tool": self.sink_tool},
            "summary": self.summary,
            "tier": self.tier,
        }

    def to_json_line(self) -> str:
        """One NDJSON line. ``sort_keys=True`` is the determinism contract."""
        return json.dumps(self.to_dict(), sort_keys=True)


class NdjsonSerializable(Protocol):
    """What the append-stream needs of a finding, at any tier."""

    def to_json_line(self) -> str: ...


def write_ndjson(findings: Iterable[NdjsonSerializable], stream: TextIO) -> int:
    """Write findings as they are found. Returns how many were written.

    Consumes the iterator lazily and flushes each line, so a consumer piping the
    stream sees a finding at the moment the engine derives it.
    """
    written = 0
    iterator: Iterator[NdjsonSerializable] = iter(findings)
    for finding in iterator:
        stream.write(finding.to_json_line() + "\n")
        stream.flush()
        written += 1
    return written
