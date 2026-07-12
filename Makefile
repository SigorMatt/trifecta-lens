# Acceptance harness (task 0.7). `make check` is the gate a task must pass
# before it counts as done (ENVIRONMENT.md): it wraps the exact toolchain
# commands plus the Phase 0 done-whens as runnable checks.

.PHONY: check golden demo demo-live demo-direct

check:
	uv run ruff check .
	uv run mypy trifecta_lens
	uv run pytest
	uv run trifecta-lens --version
	uv run python -c "from trifecta_lens.loader import load_trace; n = len(load_trace('fixtures/worked_example.jsonl')); assert n == 4, f'expected 4 events, got {n}'"

# Regenerate the findings regression anchor (fixtures/golden/). Run this ONLY
# when a change is MEANT to alter the findings output, and commit the result in
# the same change so the diff is reviewable. `make check` fails if the live
# pipeline and the committed bytes disagree — that failure is the point.
golden:
	uv run python -m tests.regenerate_golden

# Replay-only (task 1.2 done-when: "make demo replays it with no model call").
# Replays the frozen anchor through the analyzer: prints the observed spans, then
# runs the realized detector and writes the report, the findings NDJSON, and the
# path SVG (tasks 1.6-1.8). NO model call, NO network, NO API key, NO demo extra
# — it reads committed spans and writes local files. Deterministic: the same
# input yields byte-identical outputs every run.
demo:
	uv run python -m demo.replay fixtures/demo_realized.jsonl
	uv run trifecta-lens --trace fixtures/demo_realized.jsonl \
		--findings out/demo_realized.findings.ndjson \
		--svg out/demo_realized.svg

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
