"""demo/sink_server.py — an inert, fail-closed MCP sink server (task 2.4).

A real MCP server (stdio JSON-RPC, spoken with the ``mcp`` SDK) that plays the
*outbound sink* leg of the trifecta while performing **no outbound action at
all**. Its one tool, ``send``, records the body it was handed and returns a
status string; it never opens a network connection and holds no credentials.
That is the point of ``DECISIONS.md`` D8: demonstrate a sink *topology* — a tool
the agent can route sensitive data into — without any real exfiltration and
without wiring a real Slack/GitHub/webhook credential into a capture.

"Fail-closed" is by construction: there is no send path to fail *open*. If the
demo were ever pointed at a real destination, this server would still only log.
The observation the capture depends on — the body arriving at the sink — is
recorded by the client's OTLP span (``input.value`` of the ``notify__send``
call), so this server needs no persistence to be useful; it optionally appends
to a local outbox file (``DEMO_SINK_OUTBOX``) purely for human inspection.

Runs only during a live capture (``python -m demo.sink_server``, launched as a
subprocess by the client). Network/process effects are allowed here in ``demo/``
and never in the analyzer core (``CLAUDE.md`` invariant 1). The ``mcp`` SDK is
imported lazily so importing this module does not require the ``demo`` extra.
"""

from __future__ import annotations

import os
from pathlib import Path

OUTBOX_ENV = "DEMO_SINK_OUTBOX"


def _record(destination: str, body: str) -> str:
    """Record a send request without performing it; return an inert status.

    Appends to the ``DEMO_SINK_OUTBOX`` file when set — a convenience for a human
    reviewing a capture — and otherwise only counts bytes. No network, ever.
    """
    outbox = os.environ.get(OUTBOX_ENV)
    if outbox:
        path = Path(outbox)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"SEND {destination}\n{body}\n---\n")
    return (
        f"recorded {len(body)} byte(s) for {destination!r} "
        "(inert sink: logged, not delivered)"
    )


def build_server() -> object:
    """Construct the FastMCP server exposing the single ``send`` tool.

    Imported lazily inside the function so this module imports without the
    ``mcp`` package present (mirrors demo.providers' lazy-SDK pattern).
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("notify")

    @server.tool()
    def send(destination: str, body: str) -> str:
        """Send ``body`` to ``destination``. Inert: records it, does not deliver."""
        return _record(destination, body)

    return server


def main() -> None:
    """Run the sink server on stdio until the client disconnects."""
    server = build_server()
    server.run()  # FastMCP defaults to the stdio transport


if __name__ == "__main__":
    main()
