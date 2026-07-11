# Acceptance harness (task 0.7). `make check` is the gate a task must pass
# before it counts as done (ENVIRONMENT.md): it wraps the exact toolchain
# commands plus the Phase 0 done-whens as runnable checks.

.PHONY: check demo-live

check:
	uv run ruff check .
	uv run mypy trifecta_lens
	uv run pytest
	uv run trifecta-lens --version
	uv run python -c "from trifecta_lens.loader import load_trace; n = len(load_trace('fixtures/worked_example.jsonl')); assert n == 4, f'expected 4 events, got {n}'"

# Human-run only (task 1.2). Makes real model calls: needs the `demo` extra
# (the Anthropic SDK) and ANTHROPIC_API_KEY in your environment. Fails cleanly
# with a message if the key is absent. Writes payload-level OpenInference spans
# to fixtures/demo_exfil.jsonl; review them, then commit that file as the
# recorded trace. The build agent runs with no key and never runs this.
demo-live:
	uv run --extra demo python -m demo.run_live
