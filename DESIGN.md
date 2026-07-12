# DESIGN.md — detection engine architecture (design note)

**Status:** binding design for the Phase 2 engine extraction. Phase 0–1 work is
unaffected except for two constraints marked **[binding now]** (§6). Companion
to `SPEC.md` §5 (tier behavior) and `CLAUDE.md` (invariants).

## 1. Two graphs, not one

- **Topology graph** — vertices are the tools in the captured **inventory**; edges
  are **co-exposure within one agent context** (`SPEC.md` §5, `DECISIONS.md` D1):
  two tools are connected when the same agent context can invoke both, because the
  model between them will move data freely. Input to **reachable**; its degenerate
  form (vertices only, no edges — the union across all contexts) is the input to
  **posture**.

  > **Edges are NOT tool-I/O type-compatibility.** That was this document's
  > original definition and it is wrong (`DECISIONS.md` F2). In an agent, data does
  > not flow tool→tool through matching types; it flows **tool→model→tool**, and the
  > model is a universal connector that will retype and copy any value anywhere.
  > Type-compat therefore constrains nothing: `outputSchema` is optional and usually
  > absent, string-typed properties dominate where schemas do exist, and the graph
  > comes out near-complete. Co-exposure is the edge relation that actually carries
  > information.
- **Trace event graph** — vertices are events (spans); edges are causal
  ancestry (`parent_id`) plus temporal order. Input to **realized**.

Messages/responses live in the trace graph; capability lives in the topology
graph. Keeping them separate is what keeps tier honesty enforceable.

## 2. The property automaton (fixed)

Detection is **one small state machine** evaluated over labeled graphs.

**Alphabet** — emitted by the catalog labeling function
`L(vertex) → set of symbols`: `SRC` (untrusted_source), `SEN` (sensitive_data),
`SINK_X` (sink:exfil), `SINK_I` (sink:impact). Unlabeled vertices emit nothing;
a vertex may emit several symbols.

**States** — a leg-set lattice, **not a strict sequence**:
`{} → {SRC} / {SEN} → {SRC,SEN} → accept`. The order in which source and
sensitive legs are seen is immaterial (reading the vault before fetching the
poisoned page is the same exposure); the sink terminates the path:

- **Exfil trifecta** (`exfil_trifecta`) accepts on `SINK_X` when `{SRC, SEN}`
  are present in the path's ancestry.
- **Two-leg exfil** (`sensitive_to_exfil_sink`) accepts on `SINK_X` when `{SEN}`
  is present — `SRC` **not** required. This is a **relaxation of the trifecta's
  acceptance predicate on the same machine**, not a second machine: same states,
  same lattice, same guard; one conjunct dropped. Since `{SRC,SEN} ⊃ {SEN}`,
  every trifecta-accepting run is also a two-leg-accepting run — so the engine
  emits **one finding per accepting sink, at the strongest family that accepts**
  (trifecta if `SRC` is present, else two-leg), and the finding always names the
  legs observed and not-observed (`SPEC.md` §3.1). The `SEN` leg is required by
  both: exfil is about *sensitive* data leaving, so a run with no sensitive leg
  is not an exfil finding at any strength.
- **Action-hijack family** accepts on `SINK_I` when `{SRC}` is present.

The two-leg condition is what a trace with no untrusted-source leg can honestly
support. Its existence is the reason the machine never needs a "close enough"
label: when `SRC` is genuinely absent, the machine reports the weaker family
rather than pretending the stronger one accepted.

Every state self-loops on non-advancing symbols (unlabeled vertices, repeated
legs) — absorbed, never errors. The lattice is **monotone**: legs accumulate,
states never retreat. Same machine, two accepting conditions — this realizes
`SPEC.md` §3's "one engine, family determined by the sink subtype."

**Register + guard (realized tier only).** The run carries
`T: set of tainted values`, populated by extracting values (`SPEC.md` §6) at
`SEN`- and `SRC`-labeled events. The accepting transition gains a **guard**: it
fires only if some value in `T` matches — normalized-verbatim, per `SPEC.md`
§6 — the sink event's `inputs`. Symbols advance state; **data admits
acceptance**. The guard is precisely what separates realized from reachable.

## 3. Tiers = one machine, three relaxations

| Tier | Graph | Edges | Register/guard |
|---|---|---|---|
| Realized | trace event graph | causal + temporal | **on** |
| Reachable | topology graph | **co-exposure in one context** | off |
| Posture | bag of inventory roles (union of contexts) | none | off |

Drop the guard → reachable. Drop the edges → posture. Therefore
**realized ⊆ reachable ⊆ posture by construction** — tier honesty becomes a
structural property of the machine, not editorial discipline in report text
(though the text invariants in `CLAUDE.md` still apply and are still gated).

The tier relaxations and the family relaxation are **orthogonal**: tiers weaken
the *input* (edges, then the guard), families weaken the *acceptance predicate*
(one leg). Containment therefore holds **within each family** — realized
trifecta ⊆ reachable trifecta ⊆ posture trifecta, and likewise for the two-leg
family — and, at a fixed tier, **trifecta ⊆ two-leg**. A finding never moves up
a tier *or* up a family; both are lattice-monotone, which is what makes the
honesty claim structural rather than editorial.

For realized, the accepting run itself (the ordered events) is the reported
path; the matched value (masked) is the evidence.

## 4. Tunability boundary

- **The automaton is fixed and closed to users** — states, transitions,
  acceptance. It is the honesty contract: a user-rewired machine would break
  tier honesty and cross-run comparability (CI gating, auditability).
- **The only knob is the catalog** — the labeling function. Users extend
  coverage by relabeling their stack (`--catalog` overlay: "my `jira_read` is
  an untrusted_source"), never by editing the machine. This is the
  formal-language restatement of `CLAUDE.md` invariant 2.
- **Extraction parameters** (what counts as a secret-like token, normalization
  rules) are a possible later, cautiously exposed third layer — Phase 2+, each
  knob disclosed in findings output ("detected under config X").

> **NOTE (Phase 2): see `OPEN_QUESTIONS.md` §2.** Phase 1 already introduced such
> a knob — `MIN_VALUE_CHARS = 8` in `trifecta_lens/taint.py` — and it is **not**
> disclosed per-finding. Phase 2 must either disclose it or promote it into this
> exposed layer properly; an undisclosed threshold silently bounds what realized
> can see, which makes "no finding" un-auditable.

## 5. Two stages, one process

- **Stage 1 — construction (front-end).** Pure functions: raw inputs → labeled
  graph values. Trace JSONL → event graph (loader + ancestry reconstruction);
  inventory → topology graph (co-exposure edges); inventory → posture bag. Catalog
  labeling happens here — vertices come out carrying their symbols. All
  parsing mess (mime types, missing payloads, malformed spans) is confined
  here.
- **Stage 2 — engine.** Labeled graph in → findings out. Never sees JSONL,
  OpenInference attribute keys, or the inventory format.

These are **in-process stages, not OS processes**: one deterministic run, no
IPC or serialization boundary where ordering/encoding could drift. The seam —
the labeled-graph type — is the internal API; the Phase 2+ OTLP adapter
(`FIXTURES.md`) is a new Stage 1 front-end, never an engine change. An
optional `--dump-graph` debug flag may serialize the seam so the engine is
testable against committed graph fixtures.

## 6. Streaming readiness **[binding now]**

Live mode — consuming spans as agents run — is a **north-star item**
(`ROADMAP.md`), not promised. The architecture pays its entire insurance
premium in two constraints that bind from Phase 1 onward, so streaming stays
additive (a new front-end + a flag) rather than a redesign:

1. **Engine as incremental fold.** The engine consumes events one at a time in
   deterministic order, updating `(state, T)` and possibly emitting a finding.
   It must never require the complete trace as a precondition — no global
   backward passes over the full graph. Batch mode is the same fold applied to
   a closed file; monotonicity guarantees a finding never needs retraction.
2. **Findings as append-stream.** Findings output is NDJSON — one finding
   object per line, keys sorted, emitted as found. Never a monolithic
   end-of-run findings document.

Deferred to the north star itself (do not build now): out-of-order /
incomplete-span buffering, taint-set retention/windowing for long-lived runs,
and whether an OTLP-listener mode is ever worth renegotiating the network
posture. Note: **file-tailing mode needs no renegotiation** — reading an
appended file is not a network connection.

## 7. Action hooks: stdout only **[permanent, not parked]**

Core never makes an outbound call — **not even to deliver a finding**. A
built-in webhook would spend the no-network moat to save the user one line of
plumbing. Detection-to-action wiring is the user's responsibility, consuming
the NDJSON stream:

```
trifecta-lens ... | while read f; do curl -X POST myhook -d "$f"; done
```

The `curl` lives in the user's shell, not in our process. If a first-class
emitter is ever wanted, it is a separate userland/`contrib/` process consuming
stdout — the same architectural move as `demo/` living outside core so its
network use never trips the 0.4 guard.

## 8. Technology decisions

- **Language/runtime:** Python 3.11+, fully typed — per `ENVIRONMENT.md`. The
  audience lives in Python; the workload is small-DAG traversal, no
  performance case for anything else in v1.
- **Core is stdlib-pure.** Hand-roll the graph type (frozen dataclasses,
  sorted adjacency, explicit iteration order). **No networkx** (would be a
  glorified adjacency dict with iteration-order nondeterminism), **no automata
  libraries** (the machine is smaller than any dependency), **no graphviz**
  (system binary breaks `uvx`-in-60s; layouts unstable across versions —
  breaks determinism). The SVG is hand-positioned; the paths are short linear
  chains.
- **Algorithms (all textbook, all hand-rolled):** Kahn's topological sort for
  the event DAG, tie-broken by `(start_time, span_id)` — **the tie-break rule
  is a determinism invariant**; worklist/fixpoint iteration for the automaton
  run (terminates: finite monotone lattice); plain normalized substring match
  for taint at v1 scale. Aho-Corasick (`pyahocorasick`) is the noted Phase 2+
  upgrade for many-values × many-sinks matching — not now.
- **Serialization:** stdlib `json` with `sort_keys=True` everywhere findings
  are written — enforce with a test, not convention.
- **Accepted dependencies:** PyYAML for the catalog (human-edited contributor
  format earns YAML). Pydantic only if catalog/inventory validation errors get
  painful — start without; a dependency tree readable in one screen is itself
  a feature for a tool whose moat is auditability.
- **SARIF** (Phase 4) is plain JSON; no library.
