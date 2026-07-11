"""demo/run_live.py — entrypoint for ``make demo-live`` (human-run, task 1.2).

This is the single credentialed step in the project. The autonomous build agent
runs with no key and no local model and must not run this to completion
(AGENT.md, ENVIRONMENT.md). Run it, review the spans it writes, and commit them
as ``fixtures/demo_exfil.jsonl`` — that recorded trace is captured here, never
hand-authored (FIXTURES.md, CLAUDE.md).

``DEMO_ENDPOINT`` picks the transport (default ``anthropic``):

    # Anthropic Messages API — needs a key in your own environment:
    ANTHROPIC_API_KEY=... make demo-live

    # Local open model via an Ollama OpenAI-compatible endpoint — no key,
    # but set the model id and (optionally) the base URL:
    DEMO_ENDPOINT=ollama DEMO_MODEL=mistral:7b make demo-live
    DEMO_ENDPOINT=ollama DEMO_MODEL=qwen2.5:7b \\
        DEMO_OLLAMA_BASE_URL=http://localhost:11434/v1 make demo-live

    # or, to write elsewhere while iterating:
    ANTHROPIC_API_KEY=... uv run --extra demo python -m demo.run_live OUT.jsonl
"""

from __future__ import annotations

import os
import sys

# Default output is the file the human reviews and commits for task 1.2.
DEFAULT_OUTPUT = "fixtures/demo_exfil.jsonl"
API_KEY_ENV = "ANTHROPIC_API_KEY"
ENDPOINT_ENV = "DEMO_ENDPOINT"
MODEL_ENV = "DEMO_MODEL"
OLLAMA_BASE_URL_ENV = "DEMO_OLLAMA_BASE_URL"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    output_path = args[0] if args else DEFAULT_OUTPUT

    # Imported first so both paths share its endpoint/model/base-url defaults.
    from demo import agent, providers

    endpoint = os.environ.get(ENDPOINT_ENV, agent.DEFAULT_ENDPOINT)

    if endpoint == providers.ANTHROPIC:
        if not os.environ.get(API_KEY_ENV):
            print(
                f"ERROR: {API_KEY_ENV} is not set.\n"
                "  The anthropic endpoint makes real model calls and needs a "
                "key in your own environment.\n"
                f"  Set it and re-run, e.g.:  {API_KEY_ENV}=sk-... "
                "make demo-live\n"
                "  (The build agent runs with no key and does not capture the "
                "trace; you do — see demo/README.md.)",
                file=sys.stderr,
            )
            return 2
        model = os.environ.get(MODEL_ENV, agent.DEFAULT_MODEL)
    elif endpoint == providers.OLLAMA:
        model = os.environ.get(MODEL_ENV, "")
        if not model:
            print(
                f"ERROR: {MODEL_ENV} is not set.\n"
                "  The ollama endpoint has no default model; set the local "
                "model id, e.g.:\n"
                f"  {ENDPOINT_ENV}=ollama {MODEL_ENV}=mistral:7b make demo-live",
                file=sys.stderr,
            )
            return 2
    else:
        print(
            f"ERROR: {ENDPOINT_ENV}={endpoint!r} is not recognized; "
            f"expected {providers.ANTHROPIC!r} or {providers.OLLAMA!r}.",
            file=sys.stderr,
        )
        return 2

    base_url = os.environ.get(
        OLLAMA_BASE_URL_ENV, agent.DEFAULT_OLLAMA_BASE_URL
    )
    result = agent.run(
        output_path=output_path,
        endpoint=endpoint,
        model=model,
        ollama_base_url=base_url,
    )

    print(f"Wrote {result.tool_calls} tool span(s) to {result.output_path}")
    if result.received:
        for line in result.received:
            print(f"  sink: {line}")
    else:
        print(
            "  sink: nothing received — the model did not call the webhook "
            "this run (an honest outcome; the agent is not rigged to leak)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
