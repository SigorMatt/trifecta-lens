# ROADMAP.md — phased plan

Each phase exits with a **demoable** result and a **shareable moment**. Build in
this order; resist pulling later work forward. Tiers and scope per `SPEC.md`;
engine architecture per `DESIGN.md`.

## How this plan is made (read before asking for a master schedule)

**Plan one phase deep. Execute it stage-by-stage. Let it inform the next
planning chat.**

Phases 0–2 are specified. Phases 3–4 are deliberately **provisional**, and the
stage/PR breakdown *inside* a phase does not exist until that phase's planning
conversation produces it. This is structural, not a gap in the plan:

- Phase 1's real shape only became knowable **after** Phase 0 shipped.
- Phase 1 then forced a spec change **nobody could have scheduled in advance** —
  the two-leg `sensitive_to_exfil_sink` family, which only became necessary once
  a real captured trace turned out to have no untrusted-source leg.
- Phase 2 planning then proved **two committed specs wrong** (`DECISIONS.md` F1,
  F2): the MCP "manifest" contains no tools, and reachable-as-type-compatibility
  is near-vacuous. Neither was foreseeable from Phase 1.

A detailed Phase 3/4 breakdown written today would be **fiction** — and writing
it would be the "pulling breadth forward" `CLAUDE.md` forbids. Each phase's exit
becomes the brief for the next phase's planning chat.

**The cadence:** planning chat → phase task list with halt points → execute →
phase exit → next planning chat. It is what got Phase 1 through cleanly, and it
is why the checkpoints (human capture steps) fall where they do.

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
> Start from `DECISIONS.md` (D1–D9, taken in Phase 2 planning). Two of them
> correct the specs: the MCP "manifest" does not contain tools, and reachable is
> co-exposure in one agent context — not type-compatibility. `OPEN_QUESTIONS.md`
> §§1–4 are resolved there. One human capture (Checkpoint D) is the root
> dependency for the two new tiers and for OTLP.

Extract the role **catalog** (config-driven labels) and the **path engine** from
the slice — the engine is the fixed property automaton over labeled graphs
(`DESIGN.md` §§2–5), consuming events as an incremental fold and emitting
findings as an NDJSON append-stream (both binding, `DESIGN.md` §6). Implement
all three tiers: **realized** from the trace, **reachable** as co-exposure in one
agent context, **posture** as the roles present across the captured inventory's
contexts (D1). Ship the default catalog for the v1 exfil family and the
`--catalog` overlay.

**The prediction in this file's earlier draft landed, and the reality is worse
than it guessed.** Phase 2 was expected to need "a manifest-sourcing human step,
analogous to Checkpoint B." It does — but there is no manifest to source: the
file the host loads carries no tools at all, so the human step is a **real-MCP
capture** producing a *tool inventory* + a real OTLP trace (**Checkpoint D**,
D2/D8). Sourcing it **early**, as its own checkpoint, so the engine is designed
against a real inventory rather than a guessed one, is decided: it is the phase's
**root dependency**, not a mid-phase surprise. Same lesson as capturing the real
trace instead of hand-authoring it.

- **Exit:** runs against a real MCP stack's **captured inventory** + a real trace
  and emits tiered findings; "point it at your own agent" works end-to-end.
- **Shareable:** "run it on your own MCP agent in one command" demo/gif.
- Tasks: `TASKS.md` 2.1–2.13. Decisions: `DECISIONS.md` D1–D9.

### ✅ Phase 2 is complete (2026-07-13). Exit met.

`make demo-mcp` runs the two **real** Checkpoint D artifacts — the captured tool
inventory and the captured OTLP trace — through one command and emits all three
tiers. `main` is green at 210 tests.

**What the real capture actually says**, and it is the product in one line:

| Tier | Family | Sink |
|---|---|---|
| realized | `sensitive_to_exfil_sink` (two-leg) | `notify__send` |
| reachable | `exfil_trifecta` | `notify__send` |
| posture | `exfil_trifecta` | `notify__send` |

The captured run wired the **lesser** family — a file read reaching an outbound
sink, with no untrusted content in the path. But the same `assistant` context is
*also* exposed to `fetch__fetch`, so the **full trifecta was reachable and no run
was observed wiring it**. "Could, but didn't" is exactly the gap the three tiers
exist to show, and it appears on the real artifacts without being staged.

**Non-vacuity holds on the real inventory (D1/D7's binding constraint).** The 🛑
halt condition in `TASKS.md` 2.11 did **not** fire: the captured `triage` context
carries the source and sensitive legs but no outbound sink, so it cannot wire what
posture finds — a distinction posture is structurally unable to make. D7's
constructed fallback was never needed. The collapse disclosure ships regardless.

**Honest gaps carried into Phase 3** (none of them block the exit; all of them are
things we must not imply we have):
- **RAG / LLM-message ingestion is not built.** No captured trace carries those
  keys yet, and building an ingest path no real trace exercises is speculative
  breadth. Same rule that governed the OTLP adapter: a real format in hand first.
- **The realized anchor is direct-instruction, not injection.** No captured run
  exists where an untrusted-source leg and a verbatim secret at a sink co-occur —
  which is why the realized tier reports the two-leg family and says so. The
  trifecta's *realized* acceptance path is exercised only by a hand-authored
  fixture (`worked_example.jsonl`), and that is stated, not hidden.
- **Action-hijack (`sink:impact`) is catalogued but no family accepts on it** —
  Phase 4, by design.
- **README + the limitations section are Phase 3**, and the findings NDJSON schema
  is not frozen until then.

## Phase 3 — Harden for public launch
README with the documented-incident citations and the honesty section;
`CONTRIBUTING.md` framing catalog entries as the contribution path (the
flywheel); swappable-payload story; `pipx`/`uvx` install; findings NDJSON schema
frozen; benign-fixture suite proving low false-positive noise.

**The bill that comes due here: the incident citations must be
primary-source-verified.** A tool whose entire moat is not overclaiming cannot
launch on second-hand incident summaries. Budget the verification work; do not
discover it during launch week.

- **Exit:** a stranger installs and runs it on their own agent in ~60s.
- **Shareable:** the launch (HN / Show, social, the awesome-lists). This is the
  public moment — the first phase whose shareable is external, not an internal
  screenshot.

### Phase 3 — COMPLETE (2026-07-13)

Planned in the Phase 3 planning conversation, sharpened to PR granularity in
`TASKS.md` (3.1–3.7). **The launch-claim fork was resolved: framing C — the
tier-gap ("could, but didn't") is the hero; realized-trifecta-in-the-wild is NOT
claimed; no injection-capture attempt** (the honest weaker claim, chosen
deliberately; **D10** in `DECISIONS.md`).

All seven tasks shipped to `main` (green, 250 tests; `make install-check` green):

- **3.3** findings NDJSON frozen as a public contract, in-band `schema_version`.
- **3.4** `INCIDENTS.md` — primary-source-verified incidents (EchoLeak
  CVE-2025-32711; GitHub MCP / Invariant Labs) + the Willison concept source.
- **3.7** benign FP corpus — 8 benign traces, 0 realized false positives, each
  silence load-bearing for a *different, named* reason.
- **3.5** `CONTRIBUTING.md` — the catalog-entry flywheel, with every YAML example
  in it executed by the real parser and the real labeling function.
- **3.6** the install path — and the blocker turned out not to be packaging but the
  missing **input**: `demo/capture_inventory.py` is hard-wired to our own servers, so
  a stranger had no way to produce an inventory for *their* stack. Shipped
  **`trifecta-capture`** (its own package, outside core, `capture` extra) which reads
  the user's own MCP host config. `make install-check` proves the shipped wheel
  installs into a clean venv and *finds something* — not merely that `--version` runs.
- **3.1** the launch README under framing C, with `tests/test_readme.py` holding it to
  the same honesty gates as the output: no causal/attack language, no claim a
  read-only analyzer prevents anything, **every line of shown output regenerated from
  the real capture and compared**, the findings JSON compared as data, the four honest
  gaps present, and `worked_example` never named without "hand-authored" in the same
  paragraph.
- **3.2 DROPPED** (no injection capture; operator declined the spend) — recorded, not
  silently skipped.

**Two things the launch prep caught that prose review would not have.** The README's
first-draft quickstart said `pipx install "trifecta-lens[capture]"` — which **404s**;
the package is not on PyPI, and a launch page whose first command fails has spent the
credibility the rest of the page is asking for. It now installs from the repo, and a
test forbids any code block from carrying an install command that does not resolve
today. And the first draft of the "worked_example must be disclosed" gate passed a
planted violation, because a *neighbouring* paragraph said "hand-authored" about
something else.

**Exit met:** a stranger installs from the repo, captures their own inventory with
`trifecta-capture`, and runs `trifecta-lens` on their own agent. Every README claim
traces to a committed real artifact or a fixture disclosed as hand-authored. **Phase
boundary — stop here for the launch planning conversation.**

**Open, and deliberately not decided by the build agent:** publishing to PyPI (needs
the operator's credentials and is an outward-facing, one-way action), and pushing
`main` to the public remote. Both belong to the launch conversation.

## Phase 4 — Fast-follow: action hijack + CI surface  *(provisional)*
Action-hijack family (source → `sink:impact`), **posture + reachable only** —
hold realized until there's a defensible causation signal, and say so. Add SARIF
output and a GitHub Action so findings land in code-scanning.

**Phase 2 hands this phase a foothold it didn't have:** D5 makes `path_basis`
(`causal` | `temporal` | `mixed`) a required field. Action-hijack's realized tier
is blocked precisely on "no defensible causation signal" — and `path_basis` is
the beginning of the vocabulary for one. Whether a genuine `causal` chain is
*sufficient* to release action-hijack realized is a **halt-and-ask**, not a
default.

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
