"""``trifecta-capture`` — capture YOUR agent's tool inventory from YOUR MCP config.

The impure half: it launches each configured server over stdio, calls
``tools/list``, and hands the verbatim entries to :mod:`inventory_build`. It
**reads** capability; it calls no tool, and it writes exactly one thing — the
inventory JSON you asked for.

The MCP SDK is imported lazily, so the console script installs with the analyzer
and fails with a usable message (not an ImportError traceback) if the ``capture``
extra is missing::

    pipx install "trifecta-lens[capture]"
    trifecta-capture --config .mcp.json --out inventory.json
    trifecta-lens --trace your-trace.json --inventory inventory.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from trifecta_capture.inventory_build import (
    CaptureConfigError,
    ContextSpec,
    ServerSpec,
    build_inventory,
    load_host_config,
    resolve_contexts,
)

_MISSING_SDK = (
    "trifecta-capture needs the MCP SDK, which ships in the `capture` extra:\n"
    "    pipx install 'trifecta-lens[capture]'      (or)\n"
    "    uvx --from 'trifecta-lens[capture]' trifecta-capture ...\n"
    "The analyzer itself (`trifecta-lens`) needs none of it: it reads files."
)


async def _list_tools(server: ServerSpec) -> list[dict[str, Any]]:
    """Launch one server over stdio and record its ``tools/list`` entries."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:  # pragma: no cover - exercised by the message test
        raise CaptureConfigError(_MISSING_SDK) from exc

    params = StdioServerParameters(
        command=server.command, args=list(server.args), env=server.env
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        return [
            tool.model_dump(mode="json", exclude_none=True)
            for tool in sorted(listed.tools, key=lambda t: t.name)
        ]


async def _capture(
    servers: dict[str, ServerSpec], contexts: tuple[ContextSpec, ...]
) -> dict[str, list[dict[str, Any]]]:
    """List tools once per server that some context is exposed to."""
    needed = sorted({s for context in contexts for s in context.servers})
    listed: dict[str, list[dict[str, Any]]] = {}
    for server_id in needed:
        print(f"  listing tools: {server_id} ...", file=sys.stderr)
        listed[server_id] = await _list_tools(servers[server_id])
    return listed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trifecta-capture",
        description=(
            "Capture an MCP tool inventory for trifecta-lens: launches each "
            "configured server over stdio, asks it for its tools, and writes the "
            "inventory JSON. Lists capability; calls no tool."
        ),
        epilog=(
            "One agent context per --context. With none declared, the whole config "
            "is treated as ONE context — which is honest, but means the reachable "
            "tier can only restate posture (it says so). Declare your real contexts "
            "to get the tier that distinguishes them."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="the MCP host config to read (.mcp.json, claude_desktop_config.json)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("inventory.json"),
        help="where to write the inventory JSON (default: inventory.json)",
    )
    parser.add_argument(
        "--context",
        action="append",
        default=[],
        metavar="ID=SERVER,SERVER",
        help="declare an agent context and the servers it is exposed to (repeatable)",
    )
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        metavar="ID=TEXT",
        help=(
            "your note on what a context IS — carried into the report verbatim, "
            "in your voice. Without it the artifact records that no note was given."
        ),
    )
    return parser


def _notes(raw: list[str]) -> dict[str, str]:
    notes: dict[str, str] = {}
    for item in raw:
        context_id, sep, text = item.partition("=")
        if not sep or not context_id.strip() or not text.strip():
            raise CaptureConfigError(f"--note {item!r} must be of the form <id>=<text>")
        notes[context_id.strip()] = text.strip()
    return notes


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        servers = load_host_config(args.config)
        notes = _notes(list(args.note))
        contexts = resolve_contexts(servers, list(args.context), notes)
        if len(contexts) == 1:
            print(
                "note: one context declared, so reachable will equal posture on this "
                "stack. The report discloses that rather than presenting a tier that "
                "carries nothing. If your stack really is partitioned (a restricted "
                "subagent, a narrower loadout), declare it with --context.",
                file=sys.stderr,
            )
        listed = asyncio.run(_capture(servers, contexts))
        inventory = build_inventory(contexts, listed, config_path=str(args.config))
    except CaptureConfigError as exc:
        print(f"trifecta-capture: {exc}", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out}: {len(inventory['contexts'])} context(s)", file=sys.stderr)
    for context in inventory["contexts"]:
        print(
            f"  {context['id']}: {len(context['tools'])} tool(s)", file=sys.stderr
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
