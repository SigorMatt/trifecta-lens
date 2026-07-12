"""demo/mcp_client.py — a real MCP client tool-calling loop (task 2.4).

This replaces the Phase 1 harness's *local Python functions handed to a model*
(``demo/tools.py`` + ``demo/agent.py``) with an agent that really drives MCP
servers: it launches each server in a context over stdio with the ``mcp`` SDK,
discovers tools with ``tools/list``, and dispatches the model's calls with
``tools/call`` (``DECISIONS.md`` D8). The recorded trace is therefore a trace of
*real MCP tool use*, and its tool names are the same server-qualified names the
inventory capture records — the composability join that makes "the three tiers
describe one system" a checkable property rather than a hope.

The loop is transport-agnostic about the model: it reuses the provider seam
(:mod:`demo.providers`), so the same open-model endpoints as before drive it. It
is deliberately boring — a plain helpful-assistant system prompt, neutral tool
descriptions straight from the servers, no steering — so that what the trace
shows is the model's behaviour, not the harness's (``CLAUDE.md``: not a
strawman).

Every tool call is instrumented as a real OpenInference span via
:mod:`demo.otel_export`, exported as a real OTLP document. Async, because the MCP
stdio transport is; the sync provider call is offloaded with
:func:`asyncio.to_thread`. All heavy imports (``mcp``, OpenTelemetry) are lazy so
this module imports without the ``demo`` extra.

Network/process side effects live here in ``demo/`` and never in the analyzer
core (``CLAUDE.md`` invariant 1).
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from demo import mcp_config, providers
from demo.otel_export import otlp_recorder

DEFAULT_MAX_TURNS = 8

SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. Use them as needed to "
    "complete the user's request, then give a concise answer."
)


@dataclass
class CaptureResult:
    """Outcome of a live capture, for the entrypoint to report."""

    output_path: Path
    tool_calls: int
    tools_called: list[str]


def _tool_result_text(result: Any) -> tuple[str, bool]:
    """Flatten an MCP ``CallToolResult`` to ``(text, is_error)``.

    Concatenates the text of every text content block; non-text blocks are named
    but not inlined (the demo's tools return text). ``is_error`` marks the span.
    """
    parts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
        else:
            parts.append(f"[{getattr(block, 'type', 'content')}]")
    return "\n".join(parts), bool(getattr(result, "isError", False))


async def _connect_context(
    stack: AsyncExitStack,
    context_id: str,
    *,
    vault_dir: Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Launch every server in a context and return its sessions and tool schemas.

    Returns ``(sessions_by_qualified_name, tool_schemas)`` where each qualified
    tool name (``<server>__<tool>``) maps to the session that serves it, and the
    schemas are in the neutral provider form. Tool identity is namespaced so two
    servers cannot collide and so the trace's names match the inventory's.
    """
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    sessions: dict[str, Any] = {}
    schemas: list[dict[str, Any]] = []
    for server_id in mcp_config.server_ids_for(context_id):
        params = mcp_config.server_params(server_id, vault_dir=vault_dir)
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
        for tool in listed.tools:
            qualified = mcp_config.qualify(server_id, tool.name)
            sessions[qualified] = session
            schemas.append(
                {
                    "name": qualified,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema,
                }
            )
    return sessions, schemas


def _record_tool_span(
    tracer: Any,
    *,
    qualified: str,
    arguments: dict[str, Any],
    output: str,
    is_error: bool,
    parent_context: Any,
    start_ns: int,
    end_ns: int,
) -> None:
    """Emit one TOOL span with OpenInference attributes, parented to the agent.

    Uses explicit start/end timestamps captured around the real ``tools/call`` so
    the span duration reflects the actual call, and an explicit parent context so
    the tool span is a child of the AGENT root (ancestry the loader reconstructs).
    """
    from opentelemetry.trace import Status, StatusCode

    span = tracer.start_span(
        f"tool.{qualified}", context=parent_context, start_time=start_ns
    )
    span.set_attribute("openinference.span.kind", "TOOL")
    span.set_attribute("tool.name", qualified)
    span.set_attribute("input.value", json.dumps(arguments, sort_keys=True))
    span.set_attribute("input.mime_type", "application/json")
    span.set_attribute("output.value", output)
    span.set_attribute("output.mime_type", "text/plain")
    if is_error:
        span.set_status(Status(StatusCode.ERROR))
    span.end(end_time=end_ns)


async def run_capture(
    *,
    context_id: str,
    provider: providers.Provider,
    system_prompt: str,
    user_prompt: str,
    output_path: str | Path,
    vault_dir: Path | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> CaptureResult:
    """Drive one context's real MCP servers with the model; record an OTLP trace.

    Opens every server in ``context_id``, runs the tool-calling loop until the
    model stops (or ``max_turns``), records an AGENT root span plus one TOOL span
    per real ``tools/call``, and writes the OTLP document to ``output_path``.
    """
    from opentelemetry import context as otel_context
    from opentelemetry import trace as otel_trace

    tools_called: list[str] = []
    out_path = Path(output_path)

    with otlp_recorder(out_path) as tracer:
        run_start = time.time_ns()
        agent_span = tracer.start_span("agent.run", start_time=run_start)
        agent_span.set_attribute("openinference.span.kind", "AGENT")
        agent_span.set_attribute("input.value", user_prompt)
        agent_span.set_attribute("input.mime_type", "text/plain")
        parent_context = otel_trace.set_span_in_context(agent_span)

        async with AsyncExitStack() as stack:
            sessions, schemas = await _connect_context(
                stack, context_id, vault_dir=vault_dir
            )

            messages: list[providers.Message] = [
                providers.UserMessage(user_prompt)
            ]
            for _ in range(max_turns):
                turn = await asyncio.to_thread(
                    provider.complete,
                    system_prompt=system_prompt,
                    messages=messages,
                    tool_schemas=schemas,
                )
                messages.append(turn)
                if not turn.tool_calls:
                    break

                results: list[providers.ToolResult] = []
                for call in turn.tool_calls:
                    start_ns = time.time_ns()
                    session = sessions.get(call.name)
                    if session is None:
                        output, is_error = (
                            f"error: unknown tool {call.name!r}",
                            True,
                        )
                    else:
                        _, tool_name = mcp_config.split_qualified(call.name)
                        try:
                            raw = await session.call_tool(tool_name, call.arguments)
                            output, is_error = _tool_result_text(raw)
                        except Exception as exc:  # keep the loop going; record it
                            output, is_error = f"error: {exc}", True
                    end_ns = time.time_ns()

                    # Suppress the current OTel context so the tool span attaches
                    # to the agent root, not to whatever asyncio.to_thread left.
                    token = otel_context.attach(parent_context)
                    try:
                        _record_tool_span(
                            tracer,
                            qualified=call.name,
                            arguments=call.arguments,
                            output=output,
                            is_error=is_error,
                            parent_context=parent_context,
                            start_ns=start_ns,
                            end_ns=end_ns,
                        )
                    finally:
                        otel_context.detach(token)
                    tools_called.append(call.name)
                    results.append(
                        providers.ToolResult(
                            call_id=call.id, name=call.name, content=output
                        )
                    )
                messages.append(providers.ToolResultMessage(results))

        agent_span.end(end_time=time.time_ns())

    return CaptureResult(
        output_path=out_path,
        tool_calls=len(tools_called),
        tools_called=tools_called,
    )
