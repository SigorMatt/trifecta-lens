# CLAUDE.md — operating contract

This file governs how Claude Code works in this repo. Read it at the start of
every session. `SPEC.md` is the source of truth for *what* to build; this file
is the source of truth for *how* and for the lines that must never be crossed.

## What this project is

A **read-only** analyzer that detects lethal-trifecta / data-exfil exposure in
MCP-based agent systems. It consumes a captured execution **trace** and the
agent's **MCP manifest**, and reports findings across three honesty tiers
(realized / reachable / posture). It is not a firewall, not an enforcement
layer, and not a runtime — it never sits in the request path.

## Non-negotiable invariants

These are correctness *and* credibility requirements. A change that violates any
of them is wrong even if it passes tests.

1. **Read-only.** The analyzer never executes a tool, never opens a network
   connection, never writes to or mutates the target system. It reads trace
   files and config files. The only thing it writes is its own report output —
   to stdout/files **only**, never over the network (this includes findings
   delivery: no webhooks, no emitters in core — `DESIGN.md` §7).
2. **Catalog, not per-path code.** Detection is one engine over role-labeled
   tools/spans. New coverage is added as **catalog entries** (data), never as a
   new branch in the detector. If a change adds an `if tool == "specific_tool"`
   to detection logic, it is wrong — move it to the catalog.
3. **Tier honesty.** The three tiers have fixed definitions (see `SPEC.md`).
   Never relabel a posture finding as realized. Never let a lower tier borrow a
   higher tier's severity, color, or language.
4. **Flow, not causation.** A realized finding states that *tainted data was
   observed reaching a sink*. It must never claim "exfiltration occurred," call
   anything an "attack," or assert the untrusted content *caused* the action.
   We observe flow; we do not prove intent.
5. **No overclaiming coverage.** v1 detects **verbatim** taint only. Transformed
   taint (base64, splitting, paraphrase), cross-agent multi-hop, and
   memory-poisoning are explicitly out of scope and must be labeled as such in
   output and docs. Never imply they are supported.

## Architecture invariants

- **Inputs:** OTel / OpenInference spans (trace) + MCP manifest (config). Nothing
  else. No live introspection of a running agent.
- **Pure and deterministic.** Core detection is pure functions over inputs. Same
  inputs → same findings, byte-for-byte. No clocks, no randomness, no hidden
  state in the analysis path.
- **One fixed automaton; tunability only via catalog.** Detection is a fixed
  property automaton over labeled graphs (`DESIGN.md` §§2–4). Its states,
  transitions, and acceptance are closed — the only user-tunable layer is the
  catalog labeling. Changing the machine's structure is a spec change (halt
  point).
- **Two stages, one process.** Stage 1 builds labeled graph values from raw
  inputs; Stage 2 (the engine) sees only labeled graphs — never JSONL,
  OpenInference keys, or manifest formats (`DESIGN.md` §5).
- **Engine is an incremental fold.** The engine consumes events one at a time
  in deterministic order; it never requires the complete trace as a
  precondition (no global backward passes). Batch = the same fold over a
  closed file (`DESIGN.md` §6).
- **Findings are an append-stream.** Findings emit as NDJSON — one finding per
  line, `sort_keys=True`, written as found — never a monolithic end-of-run
  document (`DESIGN.md` §6).
- **Degrade honestly.** If a trace lacks payload-level span content, realized
  detection is *unavailable*, not silently empty — say so and fall back to
  reachable/posture.

## Working agreement

- **Spec-first.** If the change isn't described in `SPEC.md`, update `SPEC.md`
  in the same PR before/with the code. The spec leads, the code follows.
- **Vertical slice before breadth.** Get one path working end-to-end (ingest →
  label → detect → report → render) before adding roles or sinks. Breadth comes
  from catalog entries on top of a proven pipeline, never from a half-built
  pipeline applied to many paths.
- **Tests are the executable spec.** Every detector behavior is anchored by a
  trace/manifest **fixture** plus an expected tiered verdict. Write the fixture
  and the expected output before the detector. Benign fixtures that must produce
  *no realized finding* are as important as malicious ones.
- **Milestones are demoable.** Each phase in `ROADMAP.md` exits with something
  you could screenshot or post. Do not let unshown work pile up.
- **Small PRs.** One milestone slice per PR. Keep diffs reviewable.

## Coding conventions

- Python 3.11+, fully type-annotated. `ruff` + `mypy` clean. `pytest`.
- No network imports in the analysis core (`requests`, `httpx`, sockets) — CI
  fails the build if they appear under the core package.
- **No graph, automata, or layout libraries in core** (no networkx, no
  graphviz, no automata packages). The graph type and the machine are
  hand-rolled with explicit, deterministic iteration order; the SVG is
  hand-positioned (`DESIGN.md` §8).
- Findings serialization uses stdlib `json` with `sort_keys=True` — enforced by
  a test, not convention.
- Catalog and fixtures are data files (YAML/JSON), version-controlled, diff-able.
- Output formats are stable contracts: a findings NDJSON schema, a human
  report, and an SVG. Treat their shapes as public API once published.

## Definition of done (per change)

- [ ] `SPEC.md` reflects the behavior.
- [ ] Fixture(s) added: at least one positive and one benign.
- [ ] Deterministic (re-running gives identical findings).
- [ ] Honesty invariants 3–5 verified in the output text, not just the logic.
- [ ] `ruff`, `mypy`, `pytest` green; no network in core.
