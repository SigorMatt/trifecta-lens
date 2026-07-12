# DECISIONS.md — Phase 2 decision record

Decisions taken in the Phase 2 planning conversation (2026-07-12), after
Checkpoint C. Each was resolved deliberately, in planning, **not silently in
code** — which is what `OPEN_QUESTIONS.md` existed to force.

Two of them (D1, D2) were forced by research findings that contradicted the
committed specs. Those findings are recorded in full because the specs were
*wrong*, and a future reader needs to know why they changed.

`OPEN_QUESTIONS.md` §§1–4 are resolved here as D3, D4, D5, D6.

---

## Findings that forced D1 and D2

**F1 — the "MCP manifest" does not contain tools.** `SPEC.md` §7 said: *"Manifest:
MCP server/tool config (the same file the host loads)."* This is false. The file
the host loads (`claude_desktop_config.json` / `.mcp.json`) contains only
`mcpServers: {name: {command, args, env}}` — launch config. It carries no tool
list, no descriptions, no schemas. Tool definitions (`name`, `description`,
`inputSchema`, optional `outputSchema`, `annotations`) exist **only at runtime**,
returned by a `tools/list` JSON-RPC request to a *running* server
([MCP spec, 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)).

Both untried tiers were therefore keyed to data that is in no file — and core may
not go get it: launching a server and speaking a transport to it violates
invariant 1 (read-only).

**F2 — reachable-as-type-compatibility is near-vacuous.** `DESIGN.md` §1 defined
reachable's edges as tool-I/O schema type-compatibility. Three problems, in
increasing severity:

1. `outputSchema` is **optional** in MCP and usually absent.
2. Where schemas exist, nearly every property is `{"type": "string"}` — our own
   demo proves it (`demo/agent.py:111-162`: five tools, all-string properties,
   zero output schemas).
3. **The model's context is a universal connector.** In an agent, data does not
   flow tool→tool through matching types; it flows tool→model→tool, and the model
   will retype, reformat and copy any string anywhere. Type-compatibility
   therefore does not *constrain* reachability **at all**.

A type-compat graph over a real stack comes out near-fully-connected. Realized ⊆
reachable ⊆ posture would still hold — trivially — while reachable carried no
information. That is the failure the tier honesty invariant exists to prevent,
appearing *inside* the tier structure itself.

---

## D1 — Reachable is redefined as co-exposure in one agent context

**Decision.** Reachable = *all required legs are exposed to the **same agent
context's** effective tool set*, so a single run **could** wire them. Posture =
the roles exist **anywhere** across the configured stack, including contexts that
never share a session.

```
posture    the roles exist somewhere in the stack
             |  tighter
reachable  all legs exposed to ONE agent context
             |  tighter
realized   a run DID wire it; value observed at the sink, verbatim
```

This is what the lethal-trifecta condition actually means, it is genuinely
tighter than posture, and it is computable from a captured inventory. **The
automaton is unchanged** — this changes only what an *edge* means during Stage 1
graph construction, which is inside the tunability boundary (`DESIGN.md` §4).
`SPEC.md` §5 and `DESIGN.md` §§1, 3 must be updated to say so.

**Binding constraints on shipping it** (this tier does not ship as
informative-by-assertion):

- **Detect and disclose the collapse case.** On a single-context stack, reachable
  is necessarily equal to posture. The tool must *detect* that
  (`reachable set == posture set`) and *say so* in the output — "reachable adds no
  information on this stack: all legs share one context" — rather than presenting
  a tier that silently carries nothing.
- **Prove non-vacuity on a real inventory.** There must exist a **real** captured
  inventory on which `reachable ⊊ posture`. See D7.

**Rejected:** keeping type-compat (ships a tier we already know is thin);
dropping to two tiers (the three-tier framing is load-bearing, and there *is* a
sound middle definition).

## D2 — The tool inventory is a new, captured input artifact

**Decision.** Introduce a **tool inventory**: a JSON artifact holding a
`contexts[]` array. Each context is an id plus its **effective exposed tool set**
(the captured `tools/list` entries actually reachable by that agent context).

```json
{
  "contexts": [
    {"id": "triage-agent",
     "provenance": "<human-written note: what this context is, how it was captured>",
     "servers": ["github", "fetch"],
     "tools": [ /* tools/list entries, verbatim */ ]}
  ]
}
```

- **Posture** = union of tools over all contexts. **Reachable** = evaluated *per
  context*.
- **The inventory records the effective tool set, not the cause of it.** A context
  restricted by a subagent allowlist, a deny list, or simply a smaller server
  loadout all look the same: a smaller tool set. We do not model *why*. This is
  **flow-not-causation applied to topology** — the same discipline as invariant 4,
  one level up.
- Each context carries a **human-written provenance note**. Not machine-generated:
  a human states what the context is and how it was captured, the same discipline
  as `fixtures/FIXTURES_PROVENANCE.md`.
- The capture script lives **outside core** (the `demo/` precedent), so its
  transport use never trips the 0.4 no-network gate. Core reads the captured file,
  read-only.

`SPEC.md` §7's manifest description is **wrong** and must be corrected. The launch
config (`mcp.json`) remains useful only for server identity.

**Rejected:** deriving the tool list from the trace. Only tools a run actually
*called* would appear, with no schemas — and posture/reachable exist precisely to
flag capability **no run exercised**. Deriving them from a run is circular.

## D3 — Taint match is containment *(resolves `OPEN_QUESTIONS.md` §1)*

**Decision.** A value matches when the normalized value **occurs in** a normalized
payload string. "Verbatim" constrains transformation *of the value* (no base64,
no splitting, no paraphrase) — **not** the surrounding request body. A secret
pasted into a larger JSON body has still reached the sink.

This is what `SPEC.md` §5 step 3 ("appears in") and `DESIGN.md` §8 ("substring
match") already said, and what Phase 1 ships. **`SPEC.md` §6's "Match = exact" is
the passage that is wrong**; all three must be reconciled to one wording.

Taken **jointly with D4**: containment and the length threshold set the
false-positive rate *together*, so they land in one PR with one measurement.

## D4 — `MIN_VALUE_CHARS` stays fixed, and is disclosed *(resolves `OPEN_QUESTIONS.md` §2)*

**Decision.** The threshold remains a **fixed constant**, but is promoted into a
declared extraction config and **disclosed in every finding** and in the report:

```json
"detected_under": {"match": "containment", "min_value_chars": 8,
                   "normalization": "trim|casefold|collapse-ws"}
```

It ships with a **measured false-positive justification for the constant** — not
an asserted one. Not user-tunable: that would create a second tunable layer, and
"the automaton is fixed; tunability only via the catalog" (invariant 2) must stay
literally true. Revisit in Phase 3 only if real stacks demand it.

## D5 — `path_basis` is a required field *(resolves `OPEN_QUESTIONS.md` §3)*

**Decision.** Every finding carries a required `path_basis` (`causal` | `temporal`
| `mixed`), and each path edge carries its own basis. The SVG annotates the edge.
**This lands before any public artifact.**

Today's path rests on temporal order alone (in the anchor, all tool spans are
siblings under the root, so `parent_id` contributes nothing). Nothing we emit is
false — but an unlabelled arrow in an artifact built to be screenshotted out of
context is read as causation, and that is the single largest overclaim risk in
the product. Labelling it also *unlocks* something: where instrumentation emits
true parent chains, we can honestly report the **stronger** path instead of
flattening everything to "observed before."

## D6 — The architecture gate becomes module-scoped *(resolves `OPEN_QUESTIONS.md` §4)*

**Decision.** The 0.8 gate learns the `DESIGN.md` §5 two-stage seam. Tool-name-keyed
data (string comparisons, dict tables) is **legal in Stage 1** (loader, inventory
front-end, catalog/labeling) and **illegal in Stage 2** (engine, findings, report,
svg). Today's gate catches `if tool == "..."` but would not catch a per-tool dict
table smuggled into the engine; the seam is the boundary it should have been
policing all along.

## D7 — Non-vacuity is proven real-first; the constructed fallback is held to a topology bar

**Decision.** Capture **real-first**: from a real MCP stack. A **constructed**
inventory is built **only if** the real capture turns out to be single-context.

The constructed inventory is held to a strict bar: it must **instantiate a
documented in-the-wild topology** — not merely "discriminate." Building a topology
*because* it makes reachable fire is rigging the measurement; instantiating a
topology someone has documented as real practice is evidence. If no such topology
can be documented, we do not ship the constructed inventory as evidence.

**Either way**, the disclosure in D1 stands: reachable **does** collapse on
single-context stacks, and the tool says so.

## D8 — The demo becomes a real MCP client; the capture is Checkpoint D

**Decision.** The demo harness is rebuilt as a **real MCP client** (MCP SDK over
stdio, against real reference servers) with real OpenInference instrumentation and
OTLP export.

**Why this is the *cheapest* total-cost path, not the expensive one.** The demo
today contains no MCP at all — the "tools" are local Python functions handed to a
model API (`demo/tools.py`, `demo/agent.py:111-162`). The alternatives are worse:

- Splitting the capture (inventory from a real MCP client, trace from the existing
  local-function harness) means the two artifacts **describe different systems**.
  Tool names would not correspond, so reachable and realized could not be composed
  on one target — it **breaks the subset invariant on every real target**, which is
  the structural guarantee the whole tier design rests on.
- Deferring OTLP to Phase 3 relocates the biggest Phase 2 work into the launch
  phase, under worse conditions.

**Bounded to a minimum-viable real-MCP capture:**

- The **smallest** real setup that yields (i) a multi-context inventory where
  `reachable ⊊ posture` and (ii) a **namespace-matching** OTLP trace.
- Reference servers chosen for **realness + ease**, not scenario drama.
- **Inert, fail-closed sink. No real credentials.** We demonstrate a trifecta
  *topology* without any real outbound exfiltration, and never wire real
  GitHub/Slack write credentials into a capture.
- **Direct-instruction is fine** — no live exploit required, per the Checkpoint B
  precedent (`fixtures/demo_realized.provenance.md`).

**Checkpoint D is a Checkpoint-B-class human halt point.** A human runs the
capture and commits the artifacts with provenance. The build agent must never
fabricate an inventory or a trace.

**The composability join is a fixture assertion.** Trace tool-names must match
inventory tool-names — an executable test, not a hope. It is what makes "the three
tiers describe one system" a checkable property.

## D9 — OTLP adapter lands in Phase 2, built against a real captured trace

**Decision.** A real OTLP / OpenInference front-end is a Phase 2 task, built and
tested against the **real captured trace** from Checkpoint D — not against a
hand-shaped approximation of what we imagine OTLP looks like.

Honest fallback, retained: if it overruns, **reword the Phase 2 exit** and defer
the adapter to Phase 3. What we do *not* do is claim "point it at your own agent"
while only our own hand-shaped JSONL loads.

---

## Sequencing

**The Checkpoint D capture is the root dependency.** One real capture session
yields **both** the inventory and the OTLP trace.

```
Track A (independent — starts immediately, on the existing realized tier)
  D3+D4 containment + disclosed threshold
  D5    path_basis labelling
  D6    gate hardening

Track B (the root dependency)
  D8    real-MCP demo client  ──►  CHECKPOINT D (human capture)  ──►  inventory
                                                                  └──► OTLP trace
Track C (gated on Checkpoint D)
  catalog ──► engine extraction ──► posture ──► reachable (+collapse disclosure,
                                                 +non-vacuity proof)
```
