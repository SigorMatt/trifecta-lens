"""Core data model: the flat Event stream (SPEC.md §2). Pure — no I/O.

Spans are normalized into Events by the loader; every detection tier is a
projection over the same stream plus the manifest. ``roles`` are assigned by
the catalog (SPEC.md §4) and ``values`` are extracted by taint matching
(SPEC.md §6) — both downstream of ingest, so they default to empty there.
"""

from dataclasses import dataclass
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
        )
