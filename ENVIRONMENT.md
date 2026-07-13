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

## Repo layout
- `trifecta_lens/`      — core analyzer. Pure, deterministic, **no network**.
  Console script `trifecta-lens` (`cli.py`).
- `trifecta_capture/`   — the inventory capture (`trifecta-capture`). **Its own
  package, outside core**, because it must launch MCP servers and speak a transport
  — which core may never do (invariant 1). Ships in the `capture` extra. It **lists**
  capability; it calls no tool.
- `demo/`               — the demo agent + harness. **Outside core**; network/exec
  are allowed here and ONLY here.
- `fixtures/`           — traces and inventories. Every one is disclosed as
  **captured** or **hand-authored** in `fixtures/FIXTURES_PROVENANCE.md`. That line
  never moves.
- `schema/`             — the two public contracts: `findings.schema.json` (output,
  versioned) and `inventory.schema.json` (input — a file we ask the *user* to produce).
- `tests/`              — pytest, including the honesty/architecture gates (0.8) and
  the acceptance checks (0.7).

## Network policy (three zones — do not blur them)
1. **Build / CI:** may reach PyPI (via uv) to install dependencies. Nothing else.
2. **Analyzer core (`trifecta_lens/`):** makes **no network connection, ever** —
   enforced by the no-network guard (task 0.4). It reads trace + inventory files and
   writes only its own report. It never connects to a "target system."
3. **Outside core — `trifecta_capture/` and `demo/`:** may speak a transport.
   `trifecta-capture` launches the user's own MCP servers over stdio and asks
   `tools/list`; `demo/` may use a model API and is human-run (`make demo-live`).
   **This separation is why the core guard holds structurally** rather than by promise:
   the one thing in the project that opens a pipe is not in the analyzer.

## Credentials
- The **autonomous agent runs with no secrets and no model API key.** It
  therefore cannot (and must not) capture the demo trace.
- The single credentialed step is the human-run `make demo-live` (task 1.2),
  which needs a model API key in the human's own environment. Keep keys out of
  the repo and out of the agent's environment.
