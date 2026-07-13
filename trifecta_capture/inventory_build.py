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
    """One server we can get a tool list from — by launching it, or by being handed one.

    Exactly one of the two is set. ``command`` means *we launch it over stdio and ask*.
    ``tools_list_path`` means *the operator already has the answer* — from a remote or
    hosted server we cannot launch, obtained by whatever means their stack allows — and
    we read it from a file (``DECISIONS.md`` D11).

    Both are captures. Neither is a fabrication. What distinguishes them is not who
    typed the command but whether the tool list came from a **real running server** —
    and the only thing that separates them *for us* is what we may honestly say in the
    provenance note, which is why the distinction is carried in the type rather than
    flattened away.
    """

    id: str
    command: str | None
    args: tuple[str, ...]
    env: dict[str, str] | None
    tools_list_path: str | None = None

    @property
    def launchable(self) -> bool:
        """True when we obtain the tool list ourselves, over stdio."""
        return self.command is not None


@dataclass(frozen=True)
class ContextSpec:
    """One agent context: an id, the servers it is exposed to, an operator note."""

    id: str
    servers: tuple[str, ...]
    note: str | None
    #: Contexts this one can hand data to (D15). Declared, never inferred — a tools/list
    #: response says what an agent can REACH, never who it TALKS TO.
    delegates_to: tuple[str, ...] = ()


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
                f"{p}: server {name!r} has no 'command', so it cannot be launched — "
                "trifecta-capture speaks stdio, and a remote or hosted server has no "
                "command to run.\n"
                "That is not a dead end. Get its tools/list response however your "
                "stack allows (curl, a client script, the host's own API) and hand us "
                f"the JSON:\n"
                f"    trifecta-capture --from-tools-list {name}=tools.json ...\n"
                "A tool list obtained from a real running server is a capture, whoever "
                "fetched it (DECISIONS.md D11). Servers you CAN launch may stay in "
                "--config; the two mix freely."
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


def parse_tools_list(raw: Any, *, server: str, source: str) -> list[dict[str, Any]]:
    """Parse a ``tools/list`` response the operator obtained themselves (D11).

    We accept the shapes a real operator will actually be holding, because we do not
    control how they got it and there is no honesty at stake in the envelope:

    - the JSON-RPC result itself — ``{"tools": [...]}``,
    - the whole JSON-RPC response — ``{"result": {"tools": [...]}}``,
    - a bare list of tool objects — ``[...]``.

    Anything else fails loudly. We will not dig a tool list out of a shape we do not
    recognise: guessing wrong here would put a tool in the inventory that no server
    listed, which is the one thing that must never happen.
    """
    if isinstance(raw, dict):
        body = raw.get("result", raw)
        tools = body.get("tools") if isinstance(body, dict) else None
    elif isinstance(raw, list):
        tools = raw
    else:
        tools = None

    if not isinstance(tools, list):
        raise CaptureConfigError(
            f"{source}: not a tools/list response for server {server!r}. Expected "
            '{"tools": [...]}, a full JSON-RPC {"result": {"tools": [...]}}, or a bare '
            "list of tool objects."
        )

    parsed: list[dict[str, Any]] = []
    for entry in tools:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise CaptureConfigError(
                f"{source}: server {server!r} has a tool entry with no string 'name'. "
                "The name is the tool's identity; without it there is nothing to "
                "record."
            )
        parsed.append(entry)
    return parsed


def load_tools_list(path: str | Path, *, server: str) -> list[dict[str, Any]]:
    """Read and parse one operator-supplied ``tools/list`` response from a file."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaptureConfigError(f"{p}: no such file (--from-tools-list)") from exc
    except json.JSONDecodeError as exc:
        raise CaptureConfigError(f"{p}: invalid JSON: {exc}") from exc
    return parse_tools_list(raw, server=server, source=str(p))


def supplied_servers(declared: list[str]) -> dict[str, ServerSpec]:
    """Turn ``--from-tools-list <server>=<file>`` declarations into server specs."""
    servers: dict[str, ServerSpec] = {}
    for decl in declared:
        server_id, sep, path = decl.partition("=")
        server_id = server_id.strip()
        path = path.strip()
        if not sep or not server_id or not path:
            raise CaptureConfigError(
                f"--from-tools-list {decl!r} must be of the form <server>=<file.json>"
            )
        if NAMESPACE_SEP in server_id:
            raise CaptureConfigError(
                f"server id {server_id!r} contains {NAMESPACE_SEP!r}; the qualified "
                f"tool name <server>{NAMESPACE_SEP}<tool> would be ambiguous."
            )
        if server_id in servers:
            raise CaptureConfigError(
                f"--from-tools-list given twice for server {server_id!r}"
            )
        servers[server_id] = ServerSpec(
            id=server_id, command=None, args=(), env=None, tools_list_path=path
        )
    return servers


def merge_servers(
    launchable: dict[str, ServerSpec], supplied: dict[str, ServerSpec]
) -> dict[str, ServerSpec]:
    """Known servers = the ones we launch + the ones we were handed. They mix freely.

    A server named in *both* is ambiguous — we would not know whether the inventory
    records what the server said when we asked it or what the operator's file says, and
    those can differ. Fail rather than pick one.
    """
    clash = sorted(set(launchable) & set(supplied))
    if clash:
        raise CaptureConfigError(
            f"server(s) {clash} are both launchable from the config and supplied via "
            "--from-tools-list. Pick one source per server: we will not silently "
            "prefer a file over the server itself, or the reverse."
        )
    return {**launchable, **supplied}


def parse_delegates(
    raw: list[str], context_ids: set[str]
) -> dict[str, tuple[str, ...]]:
    """``--delegates a=b,c`` -> which contexts each one can hand data to (D15).

    A handoff to a context that was never declared would silently shrink the delegation
    chain and UNDER-report cross-agent reachability, so it fails rather than shrinks.
    """
    out: dict[str, tuple[str, ...]] = {}
    for decl in raw:
        source, sep, targets = decl.partition("=")
        source = source.strip()
        names = tuple(n.strip() for n in targets.split(",") if n.strip())
        if not sep or not source or not names:
            raise CaptureConfigError(
                f"--delegates {decl!r} must be of the form "
                "<context>=<context>,<context>"
            )
        unknown = sorted({source, *names} - context_ids)
        if unknown:
            raise CaptureConfigError(
                f"--delegates {decl!r} names undeclared context(s) {unknown}; "
                f"declared: {sorted(context_ids)}"
            )
        out[source] = names
    return out


def resolve_contexts(
    servers: dict[str, ServerSpec],
    declared: list[str],
    notes: dict[str, str],
    delegates: dict[str, tuple[str, ...]] | None = None,
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
                id=context_id,
                servers=server_ids,
                note=notes.get(context_id),
                delegates_to=(delegates or {}).get(context_id, ()),
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


#: True of the artifact however its tool lists were obtained (``DECISIONS.md`` D2).
EFFECTIVE_SET_ONLY = (
    "The inventory records the effective tool set, not the cause of it — an allowlist, "
    "a deny list and a smaller server loadout all look identical here."
)


def provenance_for(
    context: ContextSpec,
    servers: dict[str, ServerSpec],
    config_path: str | None = None,
) -> str:
    """The context's provenance note: the operator's words, then ours, separated.

    We never write prose in the operator's voice. Their note (if any) comes first and
    is theirs; the method sentence is ours and describes only what the machine did
    (``DECISIONS.md`` D2).

    **And it describes what the machine did PER SERVER.** A context can mix servers we
    launched with servers whose ``tools/list`` the operator handed us (D11), and those
    are not the same claim. Saying "launched over stdio and recorded verbatim" about a
    file someone gave us would be a fabrication of exactly the kind this project exists
    not to commit — small, invisible, and in the one field a reader consults to decide
    whether to believe the rest. So the two get different sentences, and the supplied
    one says plainly that we did not launch the server and cannot attest to how its
    response was obtained.
    """
    launched = sorted(s for s in context.servers if servers[s].launchable)
    supplied = sorted(s for s in context.servers if not servers[s].launchable)

    method: list[str] = []
    if launched:
        method.append(
            f"Captured by trifecta-capture from {config_path}: "
            f"{', '.join(launched)} were launched over stdio and their tools/list "
            "responses recorded verbatim. No model and no credentials are involved."
        )
    if supplied:
        sources = ", ".join(
            f"{s} from {servers[s].tools_list_path}" for s in supplied
        )
        was = "was" if len(supplied) == 1 else "were"
        method.append(
            f"The tools for {', '.join(supplied)} {was} supplied by the operator as a "
            f"tools/list response ({sources}). trifecta-capture did NOT launch "
            f"{'that server' if len(supplied) == 1 else 'those servers'} and cannot "
            "attest to how the response was obtained — only that it recorded the "
            "entries verbatim, and invented none."
        )
    method.append(EFFECTIVE_SET_ONLY)
    return " ".join([context.note or NO_NOTE, *method])


def build_inventory(
    contexts: tuple[ContextSpec, ...],
    listed: dict[str, list[dict[str, Any]]],
    servers: dict[str, ServerSpec],
    config_path: str | None = None,
) -> dict[str, Any]:
    """Assemble the inventory artifact (``DECISIONS.md`` D2's shape, ``SPEC.md`` §7.2).

    ``listed`` maps a server id to its ``tools/list`` entries, verbatim — whether we
    got them by launching the server or by reading the operator's file. Tools are
    recorded per context: the same tool appears in every context exposed to its server,
    which is what makes posture (the union) and reachable (per context) two different
    questions over one artifact.

    ``servers`` is here only so the provenance note can say, per server, which of those
    two happened.
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
        entry: dict[str, Any] = {
            "id": context.id,
            "provenance": provenance_for(context, servers, config_path),
            "servers": list(context.servers),
            "tools": tools,
        }
        # Only written when declared. An absent key means "you told us nothing about
        # handoffs", which is honest; an empty list would look like "there are none".
        if context.delegates_to:
            entry["delegates_to"] = list(context.delegates_to)
        out_contexts.append(entry)
    return {"contexts": out_contexts}
