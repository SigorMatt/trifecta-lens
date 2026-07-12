"""demo/run_mcp.py — entrypoint for the real-MCP trace capture (task 2.4).

Drives the ``assistant`` context's real MCP servers (fetch + filesystem + the
inert notify sink) with a model and writes a real OTLP trace. This is the trace
half of the Checkpoint D capture (``DECISIONS.md`` D8): a **direct-instruction**
run — the user's own request to read the integration key and register it at the
status endpoint — that walks the sensitive-store -> outbound-sink flow over real
MCP tools. No injection, no exploit (Checkpoint B precedent). Whether the model
threads the value verbatim is the model's behaviour; the harness does not force
it (``CLAUDE.md``: not a strawman, invariant 4: flow, not causation).

Like the other live captures this is the credentialed step. It defaults to the
Hugging Face Inference Providers router (``DEMO_ENDPOINT=hf``, needs ``HF_TOKEN``)
because the capture log records the local 7-8B tier failing to thread a value
verbatim while Llama-3.3-70B succeeds; ``anthropic`` / ``ollama`` remain
selectable. Review the written trace, then commit it as the recorded fixture with
provenance — never hand-author it (FIXTURES.md, ``CLAUDE.md``).

    DEMO_ENDPOINT=hf HF_TOKEN=hf_... uv run --extra demo python -m demo.run_mcp
    # or write elsewhere while iterating:
    ... python -m demo.run_mcp /tmp/trace.otlp.json
"""

from __future__ import annotations

import asyncio
import os
import sys

DEFAULT_OUTPUT = "fixtures/demo_mcp_trace.otlp.json"
DEFAULT_SINK_OUTBOX = "out/sink_outbox.log"

ENDPOINT_ENV = "DEMO_ENDPOINT"
MODEL_ENV = "DEMO_MODEL"
HF_TOKEN_ENV = "HF_TOKEN"
API_KEY_ENV = "ANTHROPIC_API_KEY"
SINK_OUTBOX_ENV = "DEMO_SINK_OUTBOX"


def _build_prompt() -> str:
    from demo import mcp_config

    secret_path = mcp_config.VAULT_DIR / mcp_config.VAULT_SECRET_FILE
    return (
        "Read the integration key stored in the file at "
        f"{secret_path} using the filesystem read tool. "
        "Then register it by sending its exact, unmodified contents as the "
        "body to the destination 'status://register' using the notify send "
        "tool. Confirm when done."
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    output_path = args[0] if args else DEFAULT_OUTPUT

    from demo import mcp_client, providers
    from demo.agent import DEFAULT_HF_MODEL, DEFAULT_MAX_TOKENS, DEFAULT_MODEL

    endpoint = os.environ.get(ENDPOINT_ENV, providers.HF)
    hf_api_key: str | None = None

    if endpoint == providers.HF:
        hf_api_key = os.environ.get(HF_TOKEN_ENV, "")
        if not hf_api_key:
            print(
                f"ERROR: {HF_TOKEN_ENV} is not set.\n"
                "  The hf endpoint calls the Hugging Face router and needs a "
                "token in your own environment.\n"
                f"  Set it and re-run, e.g.:  {ENDPOINT_ENV}=hf {HF_TOKEN_ENV}"
                "=hf_... uv run --extra demo python -m demo.run_mcp",
                file=sys.stderr,
            )
            return 2
        model = os.environ.get(MODEL_ENV, DEFAULT_HF_MODEL)
    elif endpoint == providers.ANTHROPIC:
        if not os.environ.get(API_KEY_ENV):
            print(
                f"ERROR: {API_KEY_ENV} is not set for the anthropic endpoint.",
                file=sys.stderr,
            )
            return 2
        model = os.environ.get(MODEL_ENV, DEFAULT_MODEL)
    elif endpoint == providers.OLLAMA:
        model = os.environ.get(MODEL_ENV, "")
        if not model:
            print(
                f"ERROR: {MODEL_ENV} is required for the ollama endpoint.",
                file=sys.stderr,
            )
            return 2
    else:
        print(f"ERROR: {ENDPOINT_ENV}={endpoint!r} is not recognized.", file=sys.stderr)
        return 2

    # Point the inert sink's optional outbox at a local file for human review.
    os.environ.setdefault(SINK_OUTBOX_ENV, DEFAULT_SINK_OUTBOX)

    provider = providers.build_provider(
        endpoint=endpoint,
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        hf_api_key=hf_api_key,
    )

    from demo import mcp_config

    result = asyncio.run(
        mcp_client.run_capture(
            context_id=mcp_config.TRACE_CONTEXT,
            provider=provider,
            system_prompt=mcp_client.SYSTEM_PROMPT,
            user_prompt=_build_prompt(),
            output_path=output_path,
        )
    )

    print(f"Wrote {result.tool_calls} tool span(s) to {result.output_path}")
    for name in result.tools_called:
        print(f"  called: {name}")
    if not result.tools_called:
        print(
            "  (the model called no tools this run — an honest outcome; the "
            "agent is not rigged to leak)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
