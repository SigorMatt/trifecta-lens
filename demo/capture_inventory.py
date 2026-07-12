"""demo/capture_inventory.py — capture the tool inventory (task 2.5, D2).

The inventory is the input the two untried tiers key on. It is a **captured**
artifact, produced here **outside** the analyzer core, because the tool
definitions it records exist only at runtime: they are the ``tools/list`` entries
a *running* MCP server returns, and core may not launch a server or speak a
transport (``CLAUDE.md`` invariant 1; ``DECISIONS.md`` D2/F1). This script does
exactly that — for each configured agent **context**, it launches that context's
servers over stdio, calls ``tools/list``, and records each context's **effective
exposed tool set** verbatim.

Needs **no model** and no credentials — it only lists tools — so it is the free
half of the capture and is run first. Output shape (``DECISIONS.md`` D2)::

    {"contexts": [
       {"id": ...,
        "provenance": "<human-written: what this context is, how captured>",
        "servers": [...],
        "tools": [{"server": <id>, "tool": <verbatim tools/list entry>}, ...]}
    ]}

Posture reads the union of contexts; reachable reads each context. The inventory
records the **effective** set, not the *cause* of it — a context narrowed by a
subagent allowlist, a deny list, or a smaller server loadout all look identical
(flow-not-causation applied to topology, ``DECISIONS.md`` D2). Tool identity is
kept verbatim under ``tool``; the server that exposed it is recorded alongside so
the loader can form the same ``<server>__<tool>`` name the trace uses (the
composability join).

The ``mcp`` SDK is imported lazily so this module imports without the ``demo``
extra.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from demo import mcp_config

DEFAULT_OUTPUT = "fixtures/inventory.json"

# Human-written provenance, one per context (``DECISIONS.md`` D2 requires a
# human note, not a machine-generated one). These state what each context is and
# are completed at capture time with the capture method; they are prose an
# operator stands behind, describing intent the tool set alone cannot show.
CONTEXT_INTENT: dict[str, str] = {
    "assistant": (
        "A broad-access personal assistant context, exposed to all three "
        "reference servers: fetch (web content — an untrusted source), "
        "filesystem scoped to demo/vault (a sensitive store), and the inert "
        "notify sink (an outbound channel). It holds the whole trifecta, so it "
        "is the context a single run could wire end to end."
    ),
    "triage": (
        "A restricted subagent context for issue triage, exposed only to fetch "
        "and filesystem — deliberately NOT to the notify sink. It can read the "
        "untrusted source and the sensitive store but has no outbound leg, so "
        "no single run in this context could complete an exfil flow. Its "
        "smaller tool set is the effective exposure; this inventory does not "
        "model whether that is a deny list, an allowlist, or a smaller loadout."
    ),
}


def _capture_note(context_id: str) -> str:
    """The provenance note: the context's intent plus the capture method."""
    intent = CONTEXT_INTENT.get(context_id, "")
    method = (
        " Captured by demo.capture_inventory: the context's servers were "
        "launched over stdio and their tools/list responses recorded verbatim. "
        "No model and no credentials are involved in this half of the capture."
    )
    return intent + method


async def _capture_context(context_id: str) -> dict[str, Any]:
    """Launch a context's servers, list tools, and record the effective set."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    server_ids = mcp_config.server_ids_for(context_id)
    tools: list[dict[str, Any]] = []
    for server_id in server_ids:
        params = mcp_config.server_params(server_id)
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            listed = await session.list_tools()
            for tool in sorted(listed.tools, key=lambda t: t.name):
                entry = tool.model_dump(mode="json", exclude_none=True)
                tools.append({"server": server_id, "tool": entry})
    return {
        "id": context_id,
        "provenance": _capture_note(context_id),
        "servers": server_ids,
        "tools": tools,
    }


async def capture(context_ids: list[str]) -> dict[str, Any]:
    """Capture the inventory for the given contexts, in order."""
    contexts = [await _capture_context(cid) for cid in context_ids]
    return {"contexts": contexts}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    output_path = args[0] if args else DEFAULT_OUTPUT

    inventory = asyncio.run(capture(list(mcp_config.CONTEXTS)))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Wrote inventory with {len(inventory['contexts'])} context(s) to {out}")
    for context in inventory["contexts"]:
        names = sorted(
            mcp_config.qualify(t["server"], t["tool"]["name"])
            for t in context["tools"]
        )
        print(f"  {context['id']}: {len(names)} tool(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
