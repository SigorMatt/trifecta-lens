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
    load_tools_list,
    merge_servers,
    parse_delegates,
    resolve_contexts,
    supplied_servers,
)

_MISSING_SDK = (
    "trifecta-capture needs the MCP SDK, which ships in the `capture` extra:\n"
    "    pipx install 'trifecta-lens[capture]'      (or)\n"
    "    uvx --from 'trifecta-lens[capture]' trifecta-capture ...\n"
    "The analyzer itself (`trifecta-lens`) needs none of it: it reads files."
)


async def _list_tools(server: ServerSpec) -> list[dict[str, Any]]:
    """Launch one server over stdio and record its ``tools/list`` entries."""
    if server.command is None:  # pragma: no cover - _capture never routes one here
        raise CaptureConfigError(
            f"server {server.id!r} has no command to launch; its tools must come from "
            "--from-tools-list."
        )
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
    """Get a tool list once per server that some context is exposed to.

    Two sources, and the operator is told which is which as it happens: we launch the
    stdio servers ourselves, and we read the ones they handed us (``DECISIONS.md`` D11).
    Both are captures; only one of them is ours to attest to.
    """
    needed = sorted({s for context in contexts for s in context.servers})
    listed: dict[str, list[dict[str, Any]]] = {}
    for server_id in needed:
        server = servers[server_id]
        if server.launchable:
            print(f"  listing tools: {server_id} (launching) ...", file=sys.stderr)
            listed[server_id] = await _list_tools(server)
        else:
            assert server.tools_list_path is not None
            print(
                f"  reading tools: {server_id} <- {server.tools_list_path} "
                "(supplied; not launched)",
                file=sys.stderr,
            )
            listed[server_id] = load_tools_list(
                server.tools_list_path, server=server_id
            )
    return listed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trifecta-capture",
        description=(
            "Capture an MCP tool inventory for trifecta-lens: launches each "
            "configured stdio server, asks it for its tools, and writes the inventory "
            "JSON. Lists capability; calls no tool. For servers it cannot launch "
            "(remote, hosted), hand it their tools/list response with "
            "--from-tools-list — that is a capture too."
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
        help=(
            "the MCP host config to read (.mcp.json, claude_desktop_config.json). "
            "Its servers are launched over stdio and asked for their tools. Optional "
            "if every server is supplied with --from-tools-list."
        ),
    )
    parser.add_argument(
        "--from-tools-list",
        action="append",
        default=[],
        metavar="SERVER=FILE.json",
        help=(
            "use a tools/list response you already have, instead of launching the "
            "server (repeatable). This is the path for remote/hosted servers, which "
            "have no command to launch: fetch their tools/list however your stack "
            "allows and hand us the JSON. A tool list from a real running server is a "
            "capture whoever fetched it. Mixes freely with --config."
        ),
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
        "--delegates",
        action="append",
        default=[],
        metavar="ID=ID,ID",
        help=(
            "declare that a context can hand data to others (repeatable). Turns on the "
            "reachable_cross_agent tier: agents that pass data between them can pool "
            "legs no single one of them holds. It cannot be inferred — a tool list "
            "says what an agent can REACH, never who it TALKS TO. Omitting it is "
            "honest; the tier just does not run."
        ),
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
        if args.config is None and not args.from_tools_list:
            raise CaptureConfigError(
                "nothing to capture: give --config (servers we launch over stdio), "
                "--from-tools-list (a tools/list response you already have), or both."
            )
        launchable = load_host_config(args.config) if args.config else {}
        supplied = supplied_servers(list(args.from_tools_list))
        servers = merge_servers(launchable, supplied)
        notes = _notes(list(args.note))
        declared_ids = {
            d.partition("=")[0].strip() for d in args.context
        } or {"default"}
        delegates = parse_delegates(list(args.delegates), declared_ids)
        contexts = resolve_contexts(servers, list(args.context), notes, delegates)
        if len(contexts) == 1:
            print(
                "note: one context declared, so reachable will equal posture on this "
                "stack. The report discloses that rather than presenting a tier that "
                "carries nothing. If your stack really is partitioned (a restricted "
                "subagent, a narrower loadout), declare it with --context.",
                file=sys.stderr,
            )
        listed = asyncio.run(_capture(servers, contexts))
        inventory = build_inventory(
            contexts,
            listed,
            servers,
            config_path=str(args.config) if args.config else None,
        )
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
