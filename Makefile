# Acceptance harness (task 0.7). `make check` is the gate a task must pass
# before it counts as done (ENVIRONMENT.md): it wraps the exact toolchain
# commands plus the Phase 0 done-whens as runnable checks.

.PHONY: check install-check golden demo demo-mcp demo-live demo-direct

check:
	uv run ruff check .
	uv run mypy trifecta_lens trifecta_capture
	uv run pytest
	uv run trifecta-lens --version
	uv run python -c "from trifecta_lens.loader import load_trace; n = len(load_trace('fixtures/worked_example.jsonl')); assert n == 4, f'expected 4 events, got {n}'"

# Task 3.6's done-when, executable: the console script INSTALLS AND RUNS from a
# clean environment. Not `uv run` — that has the source tree on the path, so it
# cannot tell you whether what we SHIP works. This builds the wheel, installs it
# into a throwaway venv with no dev deps, and runs it from a directory that is not
# the repo.
#
# It does not stop at `--version`. The catalog is package DATA, not code: a wheel
# that builds, imports and reports its version perfectly can still be missing
# `catalogs/exfil_v1.yaml` — and the labeling function is the only reason any of
# this finds anything. So the check demands a real finding, with its catalog
# citation, out of the installed package. Verified by deleting the catalog from
# the installed venv and watching the run fail.
install-check:
	rm -rf dist .install-check
	uv build --wheel
	uv venv --quiet .install-check/venv
	VIRTUAL_ENV=.install-check/venv uv pip install --quiet dist/*.whl
	.install-check/venv/bin/trifecta-lens --version
	.install-check/venv/bin/trifecta-capture --help > /dev/null
	cd .install-check && ./venv/bin/trifecta-lens \
		--trace ../fixtures/demo_mcp_trace.otlp.json \
		--inventory ../fixtures/inventory.json \
		--findings findings.ndjson > report.txt
	grep -q "\[REALIZED\]" .install-check/report.txt
	grep -q "\[REACHABLE, NOT OBSERVED\]" .install-check/report.txt || grep -q "\[REACHABLE\]" .install-check/report.txt
	grep -q "catalog: mcp.notify.send" .install-check/report.txt
	grep -q '"schema_version"' .install-check/findings.ndjson
	@echo "install-check: the shipped wheel installs clean and finds what it should."

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

# The Phase 2 exit, demoable (task 2.12). ALL THREE TIERS in one run, over the two
# REAL Checkpoint D artifacts: the captured OTLP trace and the captured tool
# inventory. No model call, no network, no key — it reads committed captures and
# writes local files.
#
# What it shows: the captured run realized only the TWO-LEG family (no untrusted
# source was in the path), while the same `assistant` context is also exposed to
# fetch — so the full trifecta is REACHABLE and no run was observed wiring it. The
# `triage` context cannot wire it at all, which is why reachable is strictly
# tighter than posture here rather than a restatement of it.
demo-mcp:
	uv run trifecta-lens --trace fixtures/demo_mcp_trace.otlp.json \
		--inventory fixtures/inventory.json \
		--findings out/demo_mcp.findings.ndjson \
		--svg out/demo_mcp.svg

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
