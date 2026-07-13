"""Inventory loader: captured inventory JSON -> topology values (task 2.6, D2).

Stage 1 front-end (DESIGN.md §5): it reads the **captured** tool inventory — the
``contexts[]`` artifact a capture step outside core produced by speaking
``tools/list`` to running servers (``SPEC.md`` §7; ``DECISIONS.md`` D2) — and
turns it into plain topology values the later tiers project over. Like the trace
loader it reads a local file only, never a network connection (``CLAUDE.md``
invariant 1), and it does no role labeling: roles come from the catalog (task
2.8). This front-end carries only tool **identity** and which context exposes it.

Posture reads the union of contexts; reachable reads each context (task
2.10/2.11). Tool identity is **server-qualified** — ``<server>__<tool>`` — the
same scheme the trace's ``tool.name`` carries, so the two artifacts join on a
shared name space (the composability join, ``DECISIONS.md`` D8). The separator is
kept here, in the Stage 1 format contract; the engine never sees it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: MCP host tool-namespacing separator. A tool's identity is its server plus its
#: bare name (two servers may each expose a ``read``); real hosts qualify with
#: forms like ``mcp__<server>__<tool>``. We join on ``<server>__<tool>``. This is
#: Stage 1 format data (legal per DESIGN.md §5 / D6), not an engine concern.
NAMESPACE_SEP = "__"


class InvalidInventoryError(ValueError):
    """The inventory file violates the contract — fail loudly, don't guess."""


@dataclass(frozen=True)
class ToolRef:
    """One exposed tool: its name, and the server that serves it **if there is one**.

    ``server`` is **optional**, and that is what makes a non-MCP agent a first-class
    input (``DECISIONS.md`` D14). Qualification exists for one reason: under MCP two
    servers may each expose a ``read``, so identity must carry the server. An agent
    whose tools are local functions has **no servers** and a flat name space — and
    forcing a fake one on it (``local__send_email``) invents an identity its trace does
    not carry, breaking the composability join by construction, which is precisely how a
    realized trifecta once out-ran a reachable two-leg in the same report.

    So: a tool's identity is its qualified name when a server serves it, and its bare
    name when nothing does. Either way it is the name the trace must also carry.
    """

    name: str
    server: str | None = None

    @property
    def qualified(self) -> str:
        """The tool's identity — the name the trace carries too (``SPEC.md`` §7.2)."""
        if self.server is None:
            return self.name
        return f"{self.server}{NAMESPACE_SEP}{self.name}"


@dataclass(frozen=True)
class Context:
    """One agent context and its effective exposed tool set (``DECISIONS.md`` D2).

    ``provenance`` is the human-written note the capture recorded — carried
    through so the report can cite what a context is and how it was captured. The
    context records the *effective* set, not the *cause* of it.
    """

    id: str
    provenance: str
    servers: tuple[str, ...]
    tools: tuple[ToolRef, ...]

    def qualified_names(self) -> frozenset[str]:
        """The server-qualified names of every tool exposed to this context."""
        return frozenset(tool.qualified for tool in self.tools)


@dataclass(frozen=True)
class Inventory:
    """The captured stack: an ordered set of contexts (``DECISIONS.md`` D1/D2)."""

    contexts: tuple[Context, ...]

    def posture_tools(self) -> frozenset[str]:
        """Union of qualified tool names over all contexts — the posture surface."""
        names: set[str] = set()
        for context in self.contexts:
            names |= context.qualified_names()
        return frozenset(names)

    def context(self, context_id: str) -> Context:
        for context in self.contexts:
            if context.id == context_id:
                return context
        raise KeyError(context_id)


def _tool_ref(entry: Any, *, context_id: str) -> ToolRef:
    """Parse one tool entry ``{"tool": {"name", ...}, "server"?}``.

    ``server`` is optional: omit it when the agent has no servers (a non-MCP stack whose
    tools are local functions), and the tool's identity is its bare name — which is what
    such a trace carries (D14).
    """
    if not isinstance(entry, dict):
        raise InvalidInventoryError(
            f"context {context_id!r}: tool entry is not an object"
        )
    server = entry.get("server")
    tool = entry.get("tool")
    if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
        raise InvalidInventoryError(
            f"context {context_id!r}: tool entry missing a verbatim "
            "'tool' object with a string 'name'"
        )
    if server is not None and (not isinstance(server, str) or not server):
        raise InvalidInventoryError(
            f"context {context_id!r}: 'server' must be a non-empty string when "
            "present. Omit it entirely if this agent has no servers — then the tool's "
            "identity is its bare name, which is what a non-MCP trace carries."
        )
    if isinstance(server, str) and NAMESPACE_SEP in server:
        raise InvalidInventoryError(
            f"context {context_id!r}: server id {server!r} contains the "
            f"namespace separator {NAMESPACE_SEP!r}; the qualified name would be "
            "ambiguous"
        )
    return ToolRef(name=tool["name"], server=server)


def _context(entry: Any) -> Context:
    if not isinstance(entry, dict):
        raise InvalidInventoryError("context is not an object")
    context_id = entry.get("id")
    if not isinstance(context_id, str) or not context_id:
        raise InvalidInventoryError("context missing a string 'id'")
    provenance = entry.get("provenance", "")
    if not isinstance(provenance, str):
        raise InvalidInventoryError(
            f"context {context_id!r}: 'provenance' must be a string"
        )
    raw_tools = entry.get("tools", [])
    if not isinstance(raw_tools, list):
        raise InvalidInventoryError(
            f"context {context_id!r}: 'tools' must be a list"
        )
    raw_servers = entry.get("servers", [])
    if not isinstance(raw_servers, list) or not all(
        isinstance(s, str) for s in raw_servers
    ):
        raise InvalidInventoryError(
            f"context {context_id!r}: 'servers' must be a list of strings"
        )
    tools = tuple(_tool_ref(t, context_id=context_id) for t in raw_tools)
    return Context(
        id=context_id,
        provenance=provenance,
        servers=tuple(raw_servers),
        tools=tools,
    )


def load_inventory(path: str | Path) -> Inventory:
    """Load a captured inventory JSON file into an :class:`Inventory`.

    Reads a local file only (``CLAUDE.md`` invariant 1). Fails loudly on a
    malformed artifact rather than guessing a topology.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInventoryError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("contexts"), list):
        raise InvalidInventoryError(
            "inventory must be an object with a 'contexts' list"
        )
    contexts = tuple(_context(c) for c in data["contexts"])
    return Inventory(contexts=contexts)
