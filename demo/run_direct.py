"""demo/run_direct.py — entrypoint for ``make demo-direct`` (human-run).

The direct-instruction counterpart to :mod:`demo.run_live`. It drives
:func:`demo.agent.run_direct`: a SEPARATE, benign scenario in which the user
directly asks the agent to read the integration key and register it at the
status endpoint. There is no poisoned issue and no injection anywhere — the
instruction is the user's own; it simply walks the vault -> webhook data flow.
The spans it writes are the *realized-positive* capture for the detector
fixtures (tasks 1.6/1.9): a sensitive value observed reaching a sink. This is
flow, not an attack (CLAUDE.md invariant 4) — never label it an injection.

Like ``make demo-live`` this is the credentialed step; the autonomous build
agent runs with no key and must not run it to completion (AGENT.md). Run it,
review the spans, and commit them as ``fixtures/demo_realized.jsonl``.

``DEMO_ENDPOINT`` picks the transport (default ``anthropic``):

    # Anthropic Messages API — needs a key in your own environment:
    ANTHROPIC_API_KEY=... make demo-direct

    # Local open model via an Ollama OpenAI-compatible endpoint — no key,
    # but set the model id and (optionally) the base URL:
    DEMO_ENDPOINT=ollama DEMO_MODEL=mistral:7b make demo-direct

    # Hosted open model via the Hugging Face Inference Providers router —
    # needs an HF token; DEMO_MODEL defaults to Llama-3.3-70B-Instruct:
    DEMO_ENDPOINT=hf HF_TOKEN=hf_... make demo-direct

    # or, to write elsewhere while iterating:
    ANTHROPIC_API_KEY=... uv run --extra demo python -m demo.run_direct OUT.jsonl
"""

from __future__ import annotations

import os
import sys

# Default output is the realized-positive trace the human reviews and commits.
DEFAULT_OUTPUT = "fixtures/demo_realized.jsonl"
API_KEY_ENV = "ANTHROPIC_API_KEY"
ENDPOINT_ENV = "DEMO_ENDPOINT"
MODEL_ENV = "DEMO_MODEL"
OLLAMA_BASE_URL_ENV = "DEMO_OLLAMA_BASE_URL"
HF_TOKEN_ENV = "HF_TOKEN"
HF_BASE_URL_ENV = "DEMO_HF_BASE_URL"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    output_path = args[0] if args else DEFAULT_OUTPUT

    # Imported first so both paths share its endpoint/model/base-url defaults.
    from demo import agent, providers

    endpoint = os.environ.get(ENDPOINT_ENV, agent.DEFAULT_ENDPOINT)
    hf_api_key: str | None = None  # only the hf endpoint uses a token here

    if endpoint == providers.ANTHROPIC:
        if not os.environ.get(API_KEY_ENV):
            print(
                f"ERROR: {API_KEY_ENV} is not set.\n"
                "  The anthropic endpoint makes real model calls and needs a "
                "key in your own environment.\n"
                f"  Set it and re-run, e.g.:  {API_KEY_ENV}=sk-... "
                "make demo-direct\n"
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
                f"  {ENDPOINT_ENV}=ollama {MODEL_ENV}=mistral:7b make demo-direct",
                file=sys.stderr,
            )
            return 2
    elif endpoint == providers.HF:
        # Hugging Face Inference Providers: an OpenAI-compatible router that
        # brokers to a third-party serving provider (observed: Groq). A real
        # token is required. DEMO_MODEL may carry an explicit provider suffix
        # (e.g. "...Llama-3.3-70B-Instruct:sambanova") if the bare id needs it.
        hf_api_key = os.environ.get(HF_TOKEN_ENV, "")
        if not hf_api_key:
            print(
                f"ERROR: {HF_TOKEN_ENV} is not set.\n"
                "  The hf endpoint calls the Hugging Face router and needs a "
                "token in your own environment.\n"
                f"  Set it and re-run, e.g.:  {ENDPOINT_ENV}=hf {HF_TOKEN_ENV}"
                "=hf_... make demo-direct\n"
                "  (The build agent runs with no token and does not capture "
                "the trace; you do — see demo/README.md.)",
                file=sys.stderr,
            )
            return 2
        model = os.environ.get(MODEL_ENV, agent.DEFAULT_HF_MODEL)
    else:
        print(
            f"ERROR: {ENDPOINT_ENV}={endpoint!r} is not recognized; expected "
            f"{providers.ANTHROPIC!r}, {providers.OLLAMA!r}, or {providers.HF!r}.",
            file=sys.stderr,
        )
        return 2

    base_url = os.environ.get(
        OLLAMA_BASE_URL_ENV, agent.DEFAULT_OLLAMA_BASE_URL
    )
    hf_base_url = os.environ.get(HF_BASE_URL_ENV, agent.DEFAULT_HF_BASE_URL)
    result = agent.run_direct(
        output_path=output_path,
        endpoint=endpoint,
        model=model,
        ollama_base_url=base_url,
        hf_base_url=hf_base_url,
        hf_api_key=hf_api_key,
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
