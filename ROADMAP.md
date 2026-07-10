# ROADMAP.md — phased plan

Each phase exits with a **demoable** result and a **shareable moment**. Build in
this order; resist pulling later work forward. Tiers and scope per `SPEC.md`;
engine architecture per `DESIGN.md`.

## Phase 0 — Skeleton & contract
Repo, license, `CLAUDE.md`, `SPEC.md`, this file, CI (ruff/mypy/pytest + the
"no network in core" check), and the trace-fixture format.
- **Exit:** `trifecta-lens --version` runs; one fixture loads and parses.
- **Shareable:** none yet (internal).

## Phase 1 — Vertical slice (the demo)
Realized-only, single hardcoded path (`fetch → vault → webhook`). Ingest
OTel/OpenInference spans → events; assign the three roles for the demo's three
tools; verbatim taint match; tiered text report + the SVG. Ship the recorded
demo trace so `make demo` is deterministic; add `make demo-live` for the real
model run.
- **Exit:** `make demo` reproducibly prints the masked exfil verdict and renders
  the red-edge SVG from the recorded trace.
- **Shareable:** the red-edge screenshot + the `RECEIVED API_KEY=…` line. First
  public-able artifact (post it even before the repo is public).

## Phase 2 — Generalize to the engine
Extract the role **catalog** (config-driven labels) and the **path engine** from
the slice — the engine is the fixed property automaton over labeled graphs
(`DESIGN.md` §§2–5), consuming events as an incremental fold and emitting
findings as an NDJSON append-stream (both binding, `DESIGN.md` §6). Implement
all three tiers per spec: realized from trace, reachable from tool I/O schema,
posture from manifest. Ship the default catalog for the v1 exfil family (common
MCP servers, the source/sink lists in `SPEC.md` §4). Support `--catalog` overlay.
- **Exit:** runs against an *arbitrary* MCP manifest + trace and emits tiered
  findings; "point it at your own agent" works end-to-end.
- **Shareable:** "run it on your own MCP agent in one command" demo/gif.

## Phase 3 — Harden for public launch
README with the documented-incident citations and the honesty section;
`CONTRIBUTING.md` framing catalog entries as the contribution path (the
flywheel); swappable-payload story; `pipx`/`uvx` install; findings NDJSON schema
frozen; benign-fixture suite proving low false-positive noise.
- **Exit:** a stranger installs and runs it on their own agent in ~60s.
- **Shareable:** the launch (HN / Show, social, the awesome-lists). This is the
  public moment.

## Phase 4 — Fast-follow: action hijack + CI surface
Action-hijack family (source → `sink:impact`), **posture + reachable only** —
hold realized until there's a defensible causation signal, and say so. Add SARIF
output and a GitHub Action so findings land in code-scanning.
- **Exit:** action-hijack posture/reachable findings + SARIF in a CI run.
- **Shareable:** "gate your agent's PRs on trifecta findings" Action.

## North star (parked — not promised)
Transformed taint, cross-agent multi-hop, memory-poisoning, cross-session state.
Also parked here:
- **Streaming / live mode** — the engine consuming spans as agents run, so
  detections fire when they occur rather than in a daily batch. Batch is the
  same fold over a closed file; a file-tailing mode preserves the no-network
  posture, while an OTLP-listener mode would renegotiate it (a deliberate
  decision, not a drift). The insurance is already paid in two binding
  constraints: engine-as-incremental-fold and findings-as-append-stream
  (`DESIGN.md` §6). New work when unparked: out-of-order/incomplete-span
  buffering and taint-set retention policy.
- **Immediate-action hooks** — these are and will remain the *user's* plumbing,
  consuming the findings NDJSON stream. Outbound calls from core are
  **permanently forbidden**, not parked (`DESIGN.md` §7); any first-class
  emitter is a separate userland/`contrib/` consumer of stdout.

Direction only. Never represented as shipped (`SPEC.md` §8).
