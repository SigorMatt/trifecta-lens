"""Core data model — **the stage seam** (SPEC.md §2, DESIGN.md §5). Pure, no I/O.

Everything in this module is what Stage 1 *produces* and Stage 2 (the engine)
*consumes*. It is the internal API between them, and it is deliberately narrow:
past this point nothing knows what JSONL, OTLP, a `tools/list` entry or a
`<server>__<tool>` separator is.

Two graphs live here (DESIGN.md §1), because the tiers project over two different
inputs:

* ``Event`` — a vertex of the **trace event graph**. Realized runs over these.
* ``LabeledTool`` / ``LabeledContext`` / ``LabeledStack`` — the **topology graph**
  built from the captured inventory. Reachable runs per context; posture runs over
  the union.

Both carry the same currency: ``roles`` (assigned by the catalog, SPEC.md §4) and
``role_notes`` (why). That shared alphabet is what lets **one** automaton run over
both — which is what makes ``realized ⊆ reachable ⊆ posture`` a structural
property rather than editorial discipline.
"""

from dataclasses import dataclass, field
from typing import Any, TypeAlias

# SPEC.md §6: a Value is a string extracted from span payloads.
Value: TypeAlias = str


@dataclass(frozen=True)
class Event:
    id: str
    parent_id: str | None
    ts: float
    actor: str
    action: str
    tool: str | None
    inputs: dict[str, Any] | None
    outputs: dict[str, Any] | None
    roles: set[str]
    values: list[Value]
    #: role -> the catalog entry's human rationale for assigning it (SPEC.md §4).
    #: Carried on the event so a finding can cite WHY a role was assigned while
    #: the engine stays tool-blind: it reads this keyed by role, never by tool.
    role_notes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible dict; roles are sorted so output is deterministic."""
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "ts": self.ts,
            "actor": self.actor,
            "action": self.action,
            "tool": self.tool,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "roles": sorted(self.roles),
            "values": list(self.values),
            "role_notes": dict(sorted(self.role_notes.items())),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls(
            id=data["id"],
            parent_id=data["parent_id"],
            ts=data["ts"],
            actor=data["actor"],
            action=data["action"],
            tool=data["tool"],
            inputs=data["inputs"],
            outputs=data["outputs"],
            roles=set(data["roles"]),
            values=list(data["values"]),
            role_notes=dict(data.get("role_notes", {})),
        )


# --- The topology graph (SPEC.md §2.1) --------------------------------------
#
# The capability tiers' input. Built by Stage 1 from the CAPTURED inventory
# (DECISIONS.md D2) and labeled by the same catalog that labels events, so the
# engine reads one alphabet over both graphs.


@dataclass(frozen=True)
class LabeledTool:
    """One exposed tool, carrying the roles the catalog assigned it."""

    #: Server-qualified under MCP (`<server>__<tool>`) — but that is just its
    #: identity. The engine compares these for equality and never parses one.
    name: str
    roles: frozenset[str]
    role_notes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LabeledContext:
    """One agent context and its **effective** exposed tool set (DECISIONS.md D2).

    ``provenance`` is the human-written capture note, carried through so the report
    can say what this context *is* — a capability finding about an unexplained
    context id would be a finding nobody can act on.

    The context records the effective set, not the *cause* of it: a narrower
    allowlist, a deny list and a smaller server loadout all look identical here,
    and we do not model why (flow-not-causation, applied to topology).
    """

    id: str
    provenance: str
    tools: tuple[LabeledTool, ...]

    def roles(self) -> frozenset[str]:
        """Every role exposed to this context — the leg set reachable evaluates."""
        roles: set[str] = set()
        for tool in self.tools:
            roles |= tool.roles
        return frozenset(roles)

    def tools_with(self, role: str) -> tuple[LabeledTool, ...]:
        """The tools carrying ``role``, in the inventory's order (deterministic)."""
        return tuple(t for t in self.tools if role in t.roles)


@dataclass(frozen=True)
class LabeledStack:
    """The captured stack: its contexts, labeled (DECISIONS.md D1/D2)."""

    contexts: tuple[LabeledContext, ...]

    def context(self, context_id: str) -> LabeledContext:
        for context in self.contexts:
            if context.id == context_id:
                return context
        raise KeyError(context_id)

    def posture_context(self) -> LabeledContext:
        """The stack collapsed to ONE bag of tools — the posture tier's input.

        Posture asks "do these roles exist *anywhere* in the stack", which is
        exactly reachable's question asked of the union of every context. Building
        it as a ``LabeledContext`` is not a convenience: it is why posture and
        reachable can be the *same code path* over a weaker input (DESIGN.md §3),
        rather than two detectors that must be kept in agreement by hand.
        """
        by_name: dict[str, LabeledTool] = {}
        for context in self.contexts:
            for tool in context.tools:
                if tool.name not in by_name:
                    by_name[tool.name] = tool
        return LabeledContext(
            id=POSTURE_CONTEXT_ID,
            provenance=(
                "the union of every context in the captured inventory — not a real "
                "agent context, and not a claim that any single one exposes all of "
                "these tools"
            ),
            tools=tuple(by_name[name] for name in sorted(by_name)),
        )


#: The synthetic id posture's union carries. Not a real context, and it says so.
POSTURE_CONTEXT_ID: str = "*posture-union*"
