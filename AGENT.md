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

## Scope of this run (bounded)
Deliver through the **Phase 1 exit** (TASKS 1.9), then **HALT for human review**.
Do **not** begin Phase 2 or later. Phases 2–4 are marked provisional in `TASKS.md`
because their design depends on what the Phase 1 slice reveals; starting them now
is pulling breadth forward, which `CLAUDE.md` forbids. Your deliverable is the
working, honest vertical slice — nothing wider.

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
- **Task 1.2 — the recorded demo trace.** Build the `demo/` harness (1.1), then
  STOP. A human runs `make demo-live` and commits `fixtures/demo_exfil.jsonl`.
  You must NOT hand-author or synthesize this file. A fabricated "recorded" trace
  violates the project's core credibility claim (`FIXTURES.md`, `CLAUDE.md`).
  Wait for the human-committed trace, then continue from task 1.3.
- **Live credentials / real model calls / anything touching a system outside this
  repo.** Stop and request it.
- **The license choice** and any change to `SPEC.md` scope or the invariants —
  including any change to the automaton's structure (states, transitions,
  acceptance — `DESIGN.md` §4). Stop and ask.
- **Phase 1 exit (1.9).** Stop and hand back for review. Do not start Phase 2.

## When blocked or ambiguous
If a task is underspecified, or a change would require an `if tool == ...` branch
in detection, or you're unsure whether output language makes a causal/attack
claim — STOP and ask rather than guessing. On the invariants, halted-and-correct
beats clever-and-wrong.

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
