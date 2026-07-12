"""demo/mcp_config.py — the real-MCP demo topology, as data (task 2.4/2.5).

This is the single source of truth for *which real MCP servers exist* and *which
agent context is exposed to which of them*. Both capture halves read it, which is
exactly why the two captured artifacts describe **one** system:

* the **inventory** capture (:mod:`demo.capture_inventory`, task 2.5) speaks
  ``tools/list`` to each server in each context and records the effective tool
  set, and
* the **trace** capture (:mod:`demo.run_mcp`, task 2.4) drives one context's
  servers with a model and records an OTLP trace.

Both name a tool the same way — :func:`qualify` — so the trace's tool names are a
subset of the inventory's tool names by construction (the composability join,
``DECISIONS.md`` D8). Nothing here labels roles for the analyzer: role labeling is
core's job via the catalog (Track C). The ``ROLE_HINT`` map below exists only to
write human-readable provenance notes, never to feed detection.

Three real servers, chosen for **realness + ease, not scenario drama**
(``DECISIONS.md`` D8):

* ``fetch``      — the ``mcp-server-fetch`` reference server (``uvx``). Fetches
  web content: an *untrusted source*.
* ``filesystem`` — the ``@modelcontextprotocol/server-filesystem`` reference
  server (``npx``), scoped to :data:`VAULT_DIR`. Reads local files: *sensitive
  data*.
* ``notify``     — :mod:`demo.sink_server`, a small **inert, fail-closed** MCP
  server we ship. Its ``send`` tool records a body and never opens a network
  connection: an *outbound sink* with **no real credentials** and no real
  exfiltration (``DECISIONS.md`` D8).

Network/process side effects live here in ``demo/`` and only here; the analyzer
core never launches a server or speaks a transport (``CLAUDE.md`` invariant 1).
The ``mcp`` SDK is imported lazily so this module imports without the ``demo``
extra installed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # import only for type-checkers; never at runtime import time
    from mcp import StdioServerParameters

DEMO_DIR = Path(__file__).resolve().parent
#: The directory the filesystem server is scoped to — the demo "vault". Holds a
#: clearly-fake secret (never a real credential; ``DECISIONS.md`` D8).
VAULT_DIR = DEMO_DIR / "vault"
#: The fake sensitive value the trace flows to the sink. Committed demo data.
VAULT_SECRET_FILE = "integration_key.txt"

#: Namespacing separator. MCP hosts qualify a tool by its server so that two
#: servers can each expose a ``read`` without colliding (real hosts use forms
#: like ``mcp__<server>__<tool>``). We use ``<server>__<tool>`` and split on the
#: FIRST separator; server ids are constrained (below) to contain no ``__`` so
#: the split is unambiguous even though tool names do contain single underscores
#: (e.g. ``read_text_file``). The separator is also in the OpenAI/Groq
#: function-name charset ``[A-Za-z0-9_-]``, so the model can call the qualified
#: name directly — a literal ``::`` would be rejected by that endpoint.
NAMESPACE_SEP = "__"


class MCPConfigError(ValueError):
    """The declared demo topology is malformed."""


def qualify(server_id: str, tool_name: str) -> str:
    """Return the namespaced tool name ``<server>__<tool>``.

    Used by both capture halves so inventory and trace agree on tool identity.
    """
    if NAMESPACE_SEP in server_id:
        raise MCPConfigError(
            f"server id {server_id!r} contains the namespace separator "
            f"{NAMESPACE_SEP!r}; server ids must not, or the split is ambiguous"
        )
    return f"{server_id}{NAMESPACE_SEP}{tool_name}"


def split_qualified(qualified: str) -> tuple[str, str]:
    """Inverse of :func:`qualify`: ``<server>__<tool>`` -> ``(server, tool)``.

    Splits on the first separator only, so a tool name's own underscores are
    preserved (``filesystem__read_text_file`` -> ``("filesystem",
    "read_text_file")``).
    """
    server_id, sep, tool_name = qualified.partition(NAMESPACE_SEP)
    if not sep or not tool_name:
        raise MCPConfigError(
            f"tool name {qualified!r} is not namespaced as <server>"
            f"{NAMESPACE_SEP}<tool>"
        )
    return server_id, tool_name


#: The real servers, by id. Each entry is enough to launch the server over stdio.
#: ``role_hint`` is documentation only (provenance notes), never fed to the
#: analyzer — role labeling is the catalog's job (Track C).
SERVERS: dict[str, dict[str, Any]] = {
    "fetch": {
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "role_hint": "untrusted_source",
        "note": "mcp-server-fetch reference server; fetches web content.",
    },
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", str(VAULT_DIR)],
        "role_hint": "sensitive_data",
        "note": (
            "@modelcontextprotocol/server-filesystem reference server, scoped to "
            "demo/vault; reads local files."
        ),
    },
    "notify": {
        # Run our inert sink server with the same interpreter that launched the
        # client, so it works under `uv run` without a separate console-script.
        "command": sys.executable,
        "args": ["-m", "demo.sink_server"],
        "role_hint": "sink:exfil",
        "note": (
            "demo.sink_server: inert, fail-closed MCP sink; records a body and "
            "never opens a network connection."
        ),
    },
}

#: Agent contexts and the servers each is exposed to. Two contexts, deliberately
#: asymmetric so that reachable is a STRICT subset of posture (``DECISIONS.md``
#: D1/D7): ``assistant`` sees all three roles (a broad personal agent);
#: ``triage`` sees the source and the sensitive store but has **no outbound
#: sink** (a restricted subagent). The union has the whole trifecta; no single
#: context but ``assistant`` does — so ``reachable != posture``.
CONTEXTS: dict[str, list[str]] = {
    "assistant": ["fetch", "filesystem", "notify"],
    "triage": ["fetch", "filesystem"],
}

#: The context the trace capture drives. Must have the sink, or no realized flow
#: could be observed.
TRACE_CONTEXT = "assistant"


def server_ids_for(context_id: str) -> list[str]:
    """The server ids exposed to ``context_id`` (validated)."""
    if context_id not in CONTEXTS:
        raise MCPConfigError(
            f"unknown context {context_id!r}; known: {sorted(CONTEXTS)}"
        )
    return list(CONTEXTS[context_id])


def server_params(
    server_id: str, *, vault_dir: Path | None = None
) -> StdioServerParameters:
    """Build the stdio launch params for one server (``mcp`` imported lazily).

    ``vault_dir`` overrides the filesystem server's scope (tests point it at a
    throwaway dir); production uses :data:`VAULT_DIR`.
    """
    from mcp import StdioServerParameters  # lazy: only a live capture needs it

    if server_id not in SERVERS:
        raise MCPConfigError(
            f"unknown server {server_id!r}; known: {sorted(SERVERS)}"
        )
    spec = SERVERS[server_id]
    args = list(spec["args"])
    if server_id == "filesystem" and vault_dir is not None:
        args = ["-y", "@modelcontextprotocol/server-filesystem", str(vault_dir)]
    return StdioServerParameters(command=spec["command"], args=args)
