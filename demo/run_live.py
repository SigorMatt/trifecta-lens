"""demo/run_live.py — entrypoint for ``make demo-live`` (human-run, task 1.2).

This is the single credentialed step in the project. It requires a model API
key in the human's own environment; the autonomous build agent runs with no key
and must not run this to completion (AGENT.md, ENVIRONMENT.md). Run it, review
the spans it writes, and commit them as ``fixtures/demo_exfil.jsonl`` — that
recorded trace is captured here, never hand-authored (FIXTURES.md, CLAUDE.md).

Usage:
    ANTHROPIC_API_KEY=... make demo-live
    # or, to write elsewhere while iterating:
    ANTHROPIC_API_KEY=... uv run --extra demo python -m demo.run_live OUT.jsonl
"""

from __future__ import annotations

import os
import sys

# Default output is the file the human reviews and commits for task 1.2.
DEFAULT_OUTPUT = "fixtures/demo_exfil.jsonl"
API_KEY_ENV = "ANTHROPIC_API_KEY"
MODEL_ENV = "DEMO_MODEL"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    output_path = args[0] if args else DEFAULT_OUTPUT

    if not os.environ.get(API_KEY_ENV):
        print(
            f"ERROR: {API_KEY_ENV} is not set.\n"
            "  'make demo-live' makes real model calls and needs a key in "
            "your own environment.\n"
            f"  Set it and re-run, e.g.:  {API_KEY_ENV}=sk-... make demo-live\n"
            "  (The build agent runs with no key and does not capture the "
            "trace; you do — see demo/README.md.)",
            file=sys.stderr,
        )
        return 2

    # Imported here so a missing key fails fast, before importing the SDK.
    from demo import agent

    model = os.environ.get(MODEL_ENV, agent.DEFAULT_MODEL)
    result = agent.run(output_path=output_path, model=model)

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
