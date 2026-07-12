# Acceptance harness (task 0.7). `make check` is the gate a task must pass
# before it counts as done (ENVIRONMENT.md): it wraps the exact toolchain
# commands plus the Phase 0 done-whens as runnable checks.

.PHONY: check demo demo-live demo-direct

check:
	uv run ruff check .
	uv run mypy trifecta_lens
	uv run pytest
	uv run trifecta-lens --version
	uv run python -c "from trifecta_lens.loader import load_trace; n = len(load_trace('fixtures/worked_example.jsonl')); assert n == 4, f'expected 4 events, got {n}'"

# Replay-only (task 1.2 done-when: "make demo replays it with no model call").
# Loads the frozen realized-positive trace through the core loader and prints the
# observed vault -> webhook flow with the secret masked. NO model call, NO
# network, NO API key, NO demo extra — it replays committed spans. The realized
# detector (task 1.6) is not built yet, so it emits NO finding, only a
# pending-verdict line.
demo:
	uv run python -m demo.replay fixtures/demo_realized.jsonl

# Human-run only (task 1.2). Makes real model calls: needs the `demo` extra
# (the Anthropic SDK) and ANTHROPIC_API_KEY in your environment. Fails cleanly
# with a message if the key is absent. Writes payload-level OpenInference spans
# to fixtures/demo_exfil.jsonl; review them, then commit that file as the
# recorded trace. The build agent runs with no key and never runs this.
demo-live:
	uv run --extra demo python -m demo.run_live

# Human-run only. The direct-instruction counterpart to demo-live: same
# credential/extra requirements, but drives demo.run_direct — a SEPARATE, benign
# task in which the user directly asks the agent to read the key and register it
# at the status endpoint (no issues, no injection). Writes the realized-positive
# spans to fixtures/demo_realized.jsonl; review them, then commit that file as
# the detector's realized-flow fixture (tasks 1.6/1.9). Not an attack — this is
# observed vault -> webhook flow requested outright.
demo-direct:
	uv run --extra demo python -m demo.run_direct
