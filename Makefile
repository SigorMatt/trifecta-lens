# Acceptance harness (task 0.7). `make check` is the gate a task must pass
# before it counts as done (ENVIRONMENT.md): it wraps the exact toolchain
# commands plus the Phase 0 done-whens as runnable checks.

.PHONY: check

check:
	uv run ruff check .
	uv run mypy trifecta_lens
	uv run pytest
	uv run trifecta-lens --version
	uv run python -c "from trifecta_lens.loader import load_trace; n = len(load_trace('fixtures/worked_example.jsonl')); assert n == 4, f'expected 4 events, got {n}'"
