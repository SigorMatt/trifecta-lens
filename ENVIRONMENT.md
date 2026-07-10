# ENVIRONMENT.md — runtime & toolchain contract

Ground truth for the build environment. The agent conforms to this; it does not
choose its own runtime. Kept consistent with `CLAUDE.md` — if the two disagree,
fix one deliberately, don't let them drift.

## Runtime
- Python **3.11+** (matches `CLAUDE.md`).
- OS: Linux or macOS. CI runs on `ubuntu-latest`.

## Toolchain
- **`pyproject.toml` is the single source of truth** for metadata and dependencies.
- Dependency tool: **uv**. The committed **`uv.lock`** pins exact versions so
  installs and findings are reproducible byte-for-byte (`CLAUDE.md` determinism
  invariant). `uv.lock` is committed and MUST NOT be gitignored.
- Lint/format: **ruff**. Types: **mypy** (code is fully type-annotated). Tests:
  **pytest**.

## Commands (exact — the agent uses these, does not invent them)
- Setup:  `uv sync --extra dev`
- Lint:   `uv run ruff check .`
- Types:  `uv run mypy trifecta_lens`
- Tests:  `uv run pytest`
- Gate:   `make check`  (the acceptance harness, task 0.7 — must pass before a
  task counts as done; the Makefile target wraps the `uv run ...` calls above)

## Repo layout (expected)
- `trifecta_lens/`      — core analyzer. Pure, deterministic, **no network**.
- `trifecta_lens/cli.py`— CLI entrypoint (`trifecta-lens`).
- `demo/`               — the vulnerable demo agent + harness. **Outside core**;
  network/exec are allowed here and ONLY here.
- `fixtures/`           — trace fixtures (the worked format-validation fixture
  `worked_example.jsonl`; later the human-recorded `demo_exfil.jsonl`).
- `tests/`              — pytest, including the honesty/architecture gates (0.8)
  and the acceptance checks (0.7).

## Network policy (three zones — do not blur them)
1. **Build / CI:** may reach PyPI (via uv) to install dependencies. Nothing else.
2. **Analyzer core (`trifecta_lens/`):** makes **no network connection, ever** —
   enforced by the no-network guard (task 0.4). It reads trace + config files and
   writes only its own report. It never connects to a "target system."
3. **`demo/` harness:** may use the network and a model API — but it is human-run
   (`make demo-live`, task 1.2), lives outside core, and never runs in the
   analyzer's path.

## Credentials
- The **autonomous agent runs with no secrets and no model API key.** It
  therefore cannot (and must not) capture the demo trace.
- The single credentialed step is the human-run `make demo-live` (task 1.2),
  which needs a model API key in the human's own environment. Keep keys out of
  the repo and out of the agent's environment.
