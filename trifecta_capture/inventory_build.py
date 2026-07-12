"""Pure half of the capture: host config + listed tools -> the inventory artifact.

Everything here is a pure function over values, so the shape of the artifact —
the thing the analyzer's two capability tiers depend on — is unit-testable without
launching a single server. The impure half (stdio transport, ``tools/list``) is
``cli.py``, and it is the only part that needs the MCP SDK.

**On provenance.** ``DECISIONS.md`` D2 asks each context for a human-written note,
because a tool set alone cannot say what a context *is*. This module will not
invent one. It writes exactly what it knows — the config file it read, the servers
it launched, the method — and, if the operator supplied ``--note``, their words,
attributed to them. If they did not, it says so, in the artifact, where a reader
of the report will see it. A machine-written note that reads like a human's would
be a small fabrication of exactly the kind this project exists not to commit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Same separator the analyzer's Stage 1 front-ends use (``<server>__<tool>``).
#: Keeping the two in step is what makes the trace and the inventory join.
NAMESPACE_SEP = "__"


class CaptureConfigError(ValueError):
    """The host config or the declared contexts are malformed — fail loudly."""


@dataclass(frozen=True)
class ServerSpec:
    """How to launch one MCP server over stdio — verbatim from the host config."""

    id: str
    command: str
    args: tuple[str, ...]
    env: dict[str, str] | None


@dataclass(frozen=True)
class ContextSpec:
    """One agent context: an id, the servers it is exposed to, an operator note."""

    id: str
    servers: tuple[str, ...]
    note: str | None


def load_host_config(path: str | Path) -> dict[str, ServerSpec]:
    """Parse an MCP host config (``.mcp.json`` / ``claude_desktop_config.json``).

    This is the file the host actually loads, and it holds **only** launch config —
    ``mcpServers: {name: {command, args, env}}``. That is all we need: we launch
    each server ourselves and ask it what tools it has (``DECISIONS.md`` F1).
    """
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaptureConfigError(f"{p}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CaptureConfigError(f"{p}: config must be a JSON object")

    raw = data.get("mcpServers")
    if not isinstance(raw, dict) or not raw:
        raise CaptureConfigError(
            f"{p}: no 'mcpServers' object. This should be the config your MCP host "
            "loads (.mcp.json, claude_desktop_config.json, ...)."
        )

    servers: dict[str, ServerSpec] = {}
    for name, spec in sorted(raw.items()):
        if not isinstance(spec, dict):
            raise CaptureConfigError(f"{p}: server {name!r} is not an object")
        command = spec.get("command")
        if not isinstance(command, str) or not command:
            raise CaptureConfigError(
                f"{p}: server {name!r} has no 'command'. Only stdio servers can be "
                "captured today; a remote/SSE server has no command to launch."
            )
        if NAMESPACE_SEP in name:
            raise CaptureConfigError(
                f"{p}: server id {name!r} contains {NAMESPACE_SEP!r}; the qualified "
                f"tool name <server>{NAMESPACE_SEP}<tool> would be ambiguous."
            )
        args = spec.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise CaptureConfigError(f"{p}: server {name!r}: 'args' must be strings")
        env = spec.get("env")
        if env is not None and not isinstance(env, dict):
            raise CaptureConfigError(f"{p}: server {name!r}: 'env' must be an object")
        servers[name] = ServerSpec(
            id=name, command=command, args=tuple(args), env=env
        )
    return servers


def resolve_contexts(
    servers: dict[str, ServerSpec],
    declared: list[str],
    notes: dict[str, str],
) -> tuple[ContextSpec, ...]:
    """Turn ``--context id=a,b`` declarations into context specs.

    With no declaration there is exactly **one** context: every server in the
    config. That is the honest default — one host config *is* one agent context
    unless the operator tells us their stack is partitioned — and it is also the
    case where the reachable tier collapses onto posture. The analyzer detects and
    discloses that collapse itself (``DECISIONS.md`` D1); the CLI warns up front so
    the operator knows the second tier will carry no extra information until they
    declare their real contexts.
    """
    if not declared:
        return (
            ContextSpec(
                id="default",
                servers=tuple(sorted(servers)),
                note=notes.get("default"),
            ),
        )

    contexts: list[ContextSpec] = []
    for decl in declared:
        context_id, sep, names = decl.partition("=")
        context_id = context_id.strip()
        if not sep or not context_id:
            raise CaptureConfigError(
                f"--context {decl!r} must be of the form <id>=<server>,<server>"
            )
        server_ids = tuple(n.strip() for n in names.split(",") if n.strip())
        if not server_ids:
            raise CaptureConfigError(f"--context {context_id!r} names no servers")
        unknown = [s for s in server_ids if s not in servers]
        if unknown:
            raise CaptureConfigError(
                f"--context {context_id!r} names server(s) not in the config: "
                f"{unknown}; known: {sorted(servers)}"
            )
        if any(c.id == context_id for c in contexts):
            raise CaptureConfigError(f"duplicate --context id {context_id!r}")
        contexts.append(
            ContextSpec(
                id=context_id, servers=server_ids, note=notes.get(context_id)
            )
        )

    unknown_notes = sorted(set(notes) - {c.id for c in contexts})
    if unknown_notes:
        raise CaptureConfigError(
            f"--note given for undeclared context(s): {unknown_notes}"
        )
    return tuple(contexts)


#: What we say when the operator supplied no note. It is not a description of the
#: context — we do not have one — it is a statement that we do not have one.
NO_NOTE = (
    "No operator note was supplied for this context. This capture records the "
    "EFFECTIVE tool set only; it does not know what this context is for, or why "
    "it is exposed to these servers. Add one with `trifecta-capture --note "
    "<id>=<what this context is>`, or edit this field by hand."
)


def provenance_for(context: ContextSpec, config_path: str) -> str:
    """The context's provenance note: the operator's words, then ours, separated.

    We never write prose in the operator's voice. Their note (if any) comes first
    and is theirs; the method sentence is ours and describes only what the machine
    did (``DECISIONS.md`` D2).
    """
    method = (
        f"Captured by trifecta-capture from {config_path}: the servers exposed to "
        "this context were launched over stdio and their tools/list responses "
        "recorded verbatim. No model and no credentials are involved. The "
        "inventory records the effective tool set, not the cause of it — an "
        "allowlist, a deny list and a smaller server loadout all look identical "
        "here."
    )
    return f"{context.note or NO_NOTE} {method}"


def build_inventory(
    contexts: tuple[ContextSpec, ...],
    listed: dict[str, list[dict[str, Any]]],
    config_path: str,
) -> dict[str, Any]:
    """Assemble the inventory artifact (``DECISIONS.md`` D2's shape).

    ``listed`` maps a server id to its ``tools/list`` entries, verbatim. Tools are
    recorded per context — the same tool appears in every context exposed to its
    server, which is what makes posture (the union) and reachable (per context)
    two different questions over one artifact.
    """
    out_contexts: list[dict[str, Any]] = []
    for context in contexts:
        tools: list[dict[str, Any]] = []
        for server_id in context.servers:
            if server_id not in listed:
                raise CaptureConfigError(
                    f"context {context.id!r}: no tools/list result for server "
                    f"{server_id!r}"
                )
            for tool in sorted(listed[server_id], key=lambda t: str(t.get("name"))):
                tools.append({"server": server_id, "tool": tool})
        out_contexts.append(
            {
                "id": context.id,
                "provenance": provenance_for(context, config_path),
                "servers": list(context.servers),
                "tools": tools,
            }
        )
    return {"contexts": out_contexts}
