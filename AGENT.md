# AGENT.md — autonomous build brief

Entrypoint for an autonomous coding agent. Read this first, then `CLAUDE.md`,
then the specific task you're working. This file defines the run loop, the scope
of this run, and the points where you must stop and hand back to a human.

## Document map
- `SPEC.md` — what to build (behavior). Source of truth.
- `CLAUDE.md` — how to build + non-negotiable invariants. Never violate.
- `DESIGN.md` — engine architecture: the fixed property automaton, the
  two-stage seam, technology decisions. Binding for the Phase 2 engine
  extraction; two constraints (incremental fold, NDJSON append-stream) bind
  from Phase 1.
- `ROADMAP.md` — phase sequencing.
- `TASKS.md` — the PR-sized checklist you execute against.
- `FIXTURES.md` — the trace input contract + worked example.
- `ENVIRONMENT.md` — runtime & toolchain contract (exact commands, network
  zones, credentials). Conform to it; never choose your own runtime or invent
  commands.
- This file — orchestration: loop, scope, halt points.

## Autonomy contract (updated 2026-07-12 — supersedes the Phase 0/1 bounded run)

Phase 0 and Phase 1 are shipped. The agent now **drives the project**. Decide,
act, and report — do not queue up permission requests.

**Stop only when:**
1. **A decision needs another brain.** A real fork, where being wrong is expensive
   and the call is *not* derivable from the repo, the specs, or the machine.
   Deliver it as a **written brief** the human can forward to peers: the options,
   what each commits us to, the cost of each, an explicit recommendation, and what
   the decision gates.
2. **A phase is complete**, before starting the next one. The phase exit is the
   brief for the next phase's planning conversation (`ROADMAP.md`).

**Do NOT stop for:** routine approvals; "may I start"; a choice with an obvious
default; or anything answerable by *reading* — the repo, the specs, or the
environment. If you can find out, find out.

**What this does NOT relax.** The invariants in `CLAUDE.md` are not process
preferences and are not negotiable — read-only core, no network in core,
catalog-not-per-path, tier/family honesty, flow-not-causation, no overclaiming.
They are enforced by executable gates in CI, which is precisely why they do not
need a human in the loop to hold.

**The one line that never moves: never fabricate a captured artifact.** A trace, a
tool inventory — *running* a real capture is expected and encouraged; *authoring*
one and calling it captured destroys the only thing this project sells. If a real
capture cannot be obtained, say so and stop. Do not synthesize a substitute.

Changing the automaton's **structure** (states, transitions, acceptance —
`DESIGN.md` §4) remains a halt-and-ask, because it is a spec decision, not an
implementation one.

## Run loop (per task)
1. Read `CLAUDE.md` + the relevant `SPEC.md` section + the current `TASKS.md` entry.
2. Work the lowest-numbered unchecked task only. One task = one PR.
3. Write the fixture/test (and its expected output) before the implementation.
4. Implement until the task's done-when passes.
5. Run the acceptance harness (`make check`). A task is done only when its check
   is green AND the honesty gates pass.
6. Check the box in `TASKS.md` in the same change. Commit. Move to the next task.

## Self-verification (don't self-certify by prose)
"Done" means the executable check passes, not that the output looks right. If a
done-when is not yet expressed as a runnable check, add the check first (tasks
0.7 / 0.8), then satisfy it.

## Halt-and-hand-back points (do NOT proceed past these alone)
- **Fabricating a captured artifact — never.** See the autonomy contract above.
  Run real captures; never author one and call it captured.
- **Live credentials.** You may install and run local tooling (real MCP servers,
  local models) and capture from them. You may not spend the human's paid
  credentials without asking, and you may not touch a system you were not pointed
  at.
- **The license choice**, and any change to `SPEC.md` **scope** or to the
  invariants — including the automaton's structure (`DESIGN.md` §4). These are
  spec decisions. Bring a brief.
- **Phase boundaries.** Complete a phase, then stop for the next planning
  conversation (`ROADMAP.md`: plan one phase deep).

## When blocked or ambiguous
First: try to resolve it yourself — read the spec, read the code, read the
environment. Most "ambiguities" are answerable.

If it is genuinely a fork (the specs contradict each other, or the honest answer
changes what we ship), write the brief and stop. On the invariants,
halted-and-correct still beats clever-and-wrong — that has not changed. What has
changed is that a routine judgment call is *yours to make*, not a reason to wait.

## Standing non-negotiables (from `CLAUDE.md` — repeated because they're load-bearing)
- **Read-only:** the analyzer never executes a tool, opens a network connection,
  or mutates a target. No network imports in core. Findings emit to
  stdout/files only — never delivered over the network.
- **Catalog, not per-path code:** no per-tool branches in detection logic. The
  automaton is fixed; the catalog is the only tunable layer.
- **Tier honesty:** never label posture as realized; never let a lower tier
  borrow a higher tier's severity, color, or language.
- **Flow, not causation:** realized output says *"tainted data observed reaching
  <sink>"* — never "attack", "exfiltration occurred", or "caused".
- **No overclaiming:** verbatim taint only; transformed / cross-agent / memory
  cases are out of scope and must be labeled as such.
