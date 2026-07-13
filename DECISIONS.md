# DECISIONS.md — the decision record

D1–D9 were taken in the **Phase 2** planning conversation (2026-07-12), after
Checkpoint C. **D10** — the launch claim — was taken in the **Phase 3** planning
conversation (2026-07-13) and is recorded at the end. Each was resolved
deliberately, in planning, **not silently in code** — which is what
`OPEN_QUESTIONS.md` existed to force.

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

## D10 — The launch claim is the tier gap, not a trifecta in the wild

*Taken in the Phase 3 planning conversation (2026-07-13); an operator decision.
Recorded here, in the 3.1 PR, because it is the decision the README is built on.*

**The fork.** Phase 2 shipped three working tiers on a real MCP stack — and the
realized tier's captured anchor is a **direct-instruction** run, not a prompt
injection. Nobody has ever handed this tool a captured trace of a real lethal
trifecta being realized in the wild, and neither have we. So: what does the launch
*claim*?

Three framings were live:

- **A — "we caught a lethal trifecta."** Requires a captured injection run. We do
  not have one, and the only ways to get one are to attempt a real capture against
  a real system (out of scope, and a spend the operator declined) or to author one
  and call it captured. The second is the line that never moves.
- **B — "posture scanner for MCP."** True, shippable today, and boring: posture
  overlaps every static scanner in the category. It leads with our weakest tier.
- **C — "the tier gap is the hero."** Lead with **reachable vs realized**: *this
  agent could wire the trifecta, and in the run we captured it didn't.* Both halves
  rest on real, committed artifacts. **Chosen.**

**Decision: framing C.** The launch headlines the **"could, but didn't" gap** on
real artifacts. A **realized lethal trifecta in the wild is NOT claimed**, anywhere.
The realized *trifecta* is exercised only by `fixtures/worked_example.jsonl`, which
is **hand-authored** and disclosed as such every time it is named. No
injection-capture attempt; no paid-credential spend (**3.2 is DROPPED**, recorded
rather than silently skipped).

**Why the weaker claim is the right one.** The strong claim is the one we could not
support without manufacturing evidence, and this tool's entire value is that it
does not say what it cannot support. A product whose pitch is *"we only tell you
what we actually saw"* cannot open with something it did not actually see — the
first reader to check would be right to discard everything else in the report. The
gap claim is also, on inspection, the more useful one: nobody has a trace of their
agent leaking data, and everybody has a topology that could.

**Binding on the README (enforced, not promised).** `tests/test_readme.py` fails the
build if the README carries causal/attack language, claims a read-only analyzer
prevents anything, shows a line of output the tool did not really print, shows a
findings JSON that is not byte-for-byte the real finding, omits any of the four
honest gaps, or mentions `worked_example` in a paragraph that does not call it
hand-authored. The honesty gate now scans the front page, because far more people
read the front page than run the tool.

## D11 — The inventory is a published input contract; the capture tool is a convenience

*Taken 2026-07-13, after a read of the launch docs against the code.*

**The finding that forced it.** `trifecta-capture` launches servers over stdio and
therefore **cannot capture a remote or hosted MCP server** — one has no command to
launch, and the tool says so and exits. That limitation is honest, correct, and
appeared **nowhere in the README**, whose 60-second quickstart opens with
`trifecta-capture --config .mcp.json`. A hosted-MCP user met a hard error on first
contact. Worse, nothing told them the error was *survivable*: the README presents the
capture tool as the only route to an inventory, so the reasonable inference is "this
tool does not work for my stack."

That inference is false, and the reason is a fact the docs never stated: **the
analyzer reads only `context.id`, `server`, and `tool.name`.** Descriptions and
schemas are recorded verbatim for the auditor and read by no detector (they *can't*
be — F2 is the finding that schemas cannot constrain reachability). An inventory is
cheap to assemble by hand, and deliberately so.

**Decision, in three parts.**

1. **`schema/inventory.schema.json` is published as a public input contract**, with
   the same discipline the findings NDJSON gets: a machine-readable schema, a prose
   companion (`SPEC.md` §7.2), and a test that fails the build when the code, the
   schema, and the prose disagree. The *output* was frozen while the *input* — the
   one file we ask the world to produce — was implicit. That asymmetry was backwards.

2. **An inventory is a capture if its tool list came from a real running server, by
   any means.** Curl, a five-line script, a hosted server's own API, a transport MCP
   has not invented yet: all capture. The distinction this project enforces is
   **captured vs fabricated** — it was never automated vs manual, and reading it that
   way turns an honest operator away for no reason. `trifecta-capture` is the
   *convenient* path for stdio stacks; it is not the definition of a legitimate one.
   The line that never moves is unchanged and now stated where it belongs: **never
   record a tool that no server listed.**

3. **The provenance note must describe what actually happened, per server.**
   `provenance_for()` writes *"launched over stdio and their tools/list responses
   recorded verbatim."* It must **never** say that about a response the operator
   handed us from a file. Out-of-band servers get their own method sentence, naming
   the source and stating plainly that trifecta-capture did not launch the server and
   cannot attest to how the response was obtained. This is
   never-fabricate-a-captured-artifact applied to the *note*, which is the one place a
   capture tool can lie without touching a single tool name.

**Shipped with it:** `trifecta-capture --from-tools-list <server>=<file>`, so the
escape hatch is a supported path rather than a documented chore — it composes with
`--context`, makes `--config` optional, and supports **mixed** stacks (some local
stdio, some hosted), which is the realistic shape.

**Rejected:** teaching `trifecta_capture` every MCP transport (HTTP, SSE, whatever is
next) — a growing surface that chases a moving spec, to reach the same `tools/list`
response the operator can already obtain. One transport-agnostic entry point covers
all of them and cannot rot.

**The gate that would have caught this, and now does.** `tests/test_readme.py` scanned
for causal language, overclaiming, and unrunnable install commands — and passed a
README whose quickstart fails for an entire class of stacks. The missing class is
**unstated preconditions**, and a tool whose moat is *saying what it cannot do* has to
gate for silence, not only for false statements.

## D12 — One convention, two envelopes; a format is a Stage-1 front-end *(resolves `OPEN_QUESTIONS.md` §5)*

*Taken 2026-07-13, prompted by the question "what trace shapes do we actually support?"
— which the documents and the code answered differently.*

**The findings that forced it.** Two doc/code drifts, in opposite directions, neither
visible to any test:

- **`SPEC.md` §7 said the trace input was *"OTel GenAI / OpenInference spans."*** No
  `gen_ai.*` key is read anywhere in core. And it does not *degrade* — the OpenInference
  span kind is a **required** attribute, so an OTel GenAI trace is **refused on span
  one**. The source-of-truth document named a format the loader hard-fails on, and the
  error blamed the user's file ("malformed fixture") for our own limit.
- **`FIXTURES.md`'s attribute→Event table carried a `retrieval.documents.*` row** for two
  phases. Nothing has ever read it. That table *is* the contract a contributor writes a
  fixture against: the promise was real, the delivery was silence.

**The conceptual error underneath both** — and the thing worth carrying: **envelope and
semantic convention are two different axes**, and the docs conflated them. An envelope is
how spans are *packaged* (flat JSONL; OTLP/JSON's nested `resourceSpans`, base64 ids,
`AnyValue` attribute arrays). A convention is what the attribute keys *mean*
(OpenInference's `tool.name` / `input.value`; OTel GenAI's `gen_ai.tool.name`). Shipping
a second **envelope** (task 2.7) felt like broadening format support, and in the docs it
quietly became a claim about **conventions**. It was not one.

**Decision.**

1. **We ship two envelopes and exactly one convention: OpenInference.** Stated in
   `SPEC.md` §7.3, with the complete six-key list, and the bound that follows from it:
   **only tool spans carry roles.** Roles are matched against `Event.tool`, so a span
   with no `tool.name` contributes nothing to any finding — LLM, AGENT and RETRIEVER
   spans are parsed, ordered, and **inert**. That is the single largest bound on what the
   realized tier can see, and until now it was written nowhere.

2. **Adding a format is a new Stage-1 front-end, never an engine branch.** This is
   invariant 2 ("catalog, not per-path code") extended to the ingest layer, and it is not
   speculative: `load_otlp_trace` is the worked precedent — a whole second envelope, zero
   engine change, because both decode into one intermediate span shape and share one
   attribute→`Event` mapping (`DESIGN.md` §5). A convention adapter lands the same way.

3. **A second convention lands only against a real captured trace of it** (D9's rule,
   restated). We hold no GenAI-instrumented capture and no RAG trace, so we build
   neither. Until then they are **named as unsupported** — not "coming soon" — and the
   loader **refuses loudly, and explains itself**: it says which convention we read, says
   `gen_ai.*` is a different one, and states plainly that the user's trace is *not
   malformed, we simply do not speak it*. An honest refusal is the product.

4. **The documented surface and the read surface are pinned to each other.**
   `tests/test_trace_contract.py`: every key in `FIXTURES.md`'s table is read by the
   loader, every key the loader reads is in the table, the GenAI refusal is tested
   behaviour, and "only tool spans carry roles" is executable rather than folklore.
   Neither side can grow in silence again.

**Rejected:** building the GenAI front-end now (violates D9 — we would be guessing at a
convention we have never captured, which is precisely how the "manifest contains tools"
error happened); and leaving the docs to describe an aspiration (a spec that names a
format the loader refuses is an overclaim in the one document the rest are derived from).

**Related:** this is the same defect class as **D11** — the drift was a *silence* on one
side and a *false statement* on the other, and neither was gated. The gates now cover
both.

## D13 — Labeling coverage is disclosed, and unmatched tools are never adjudicated

*Taken 2026-07-13, after pointing the tool at a stack it had no entries for.*

**The finding.** Given an inventory of Slack + Postgres + Linear —
`slack__read_channel_history` (untrusted content), `postgres__query` (private data),
`slack__post_to_channel` (an outbound sink), all exposed to one agent context, which is a
**textbook lethal trifecta** — trifecta-lens printed:

> `no findings at this tier: the captured inventory does not carry all the legs of any
> family we detect.`

It had matched **none** of the four tools against its 16-entry catalog, and never said so.
A reader takes that for a clean bill of health.

**This was our own principle, unattended.** D4 promoted `min_value_chars` into a disclosed
`detected_under` field on the argument that *"an undisclosed threshold silently bounds what
the realized tier can see, which makes 'no finding' un-auditable — the same honesty failure
as an overclaim, pointed the other way."* The **catalog** bounds the search far harder than
`min_value_chars` ever could, and it was the one bound never disclosed. `report.py` even
carried the rule in its own docstring — *"a tier that did not run is not a tier that found
nothing"* — and then let a starved tier print like a clean one.

**Decision.**

1. **Every report over an inventory carries a COVERAGE section, before the tiers** (it
   bounds everything below it), stating how many tools matched and **naming every tool that
   did not**. A count tells a reader they have a problem; the list tells them which entries
   to write. `SPEC.md` §6.2.

2. **A silent capability tier now says which of three things it means** — the catalog
   matched *nothing* (the tier is **starved**, not clean — say so, and warn on stderr);
   matched *some* (silence holds only among those); matched *everything* (silence is a
   genuine result about the stack). One sentence could not honestly serve all three.

3. **The disclosure counts and names. It never adjudicates.** This is the part that will be
   tempting to "fix" later, so it is written down: *"matched no entry"* has **two causes and
   we cannot distinguish them* — a tool we have never heard of (`postgres__query`), and a
   tool we know and **deliberately** leave unlabeled (`list_directory` returns names, not
   content; §4 says labeling it "would make every `ls` a leg"). On the real Checkpoint D
   capture, **every one** of the six unmatched tools is of the second kind. So we may not
   call an unmatched tool "uncovered" (overclaims a gap) or "safe" (overclaims a clearance).
   Flow-not-causation, applied to the labeling layer.

**Why disclosure before catalog breadth.** Breadth is endless — there will always be an
uncovered stack — so disclosure is what makes *every* stack honest, including the ones we
never cover. It is also what **starts the `CONTRIBUTING.md` flywheel**: until now a stranger
with an unrecognised stack got no signal that an overlay was the answer; the tool simply
looked like it had found nothing. A test walks the whole loop — unrecognised stack →
coverage disclosure → the user writes four catalog entries → the **unmodified** engine
surfaces the trifecta.

**No findings-schema change.** `schema_version` stays `1.0`. The dangerous case has **zero**
findings, so no per-finding field could have carried this — the disclosure has to live where
the silence does.

**Binding on Phase 4.** When the CI / SARIF surface lands, **coverage must ride into it.** A
CI job consuming an empty `findings.ndjson` would otherwise report "clean" on a stack the
tool never recognised — this same bug, with a worse blast radius and no human reading a
report to catch it.

**Deliberately not done:** new catalog entries. Disclosure is the honesty fix; breadth is the
usefulness fix, and it is a separate, larger piece of work with a fixture bar
(`CONTRIBUTING.md`) that this PR would have had to shortcut.

## D14 — Tool identity is bare when there is no server; the join is checked at runtime

*Taken 2026-07-13, while writing `USAGE.md`'s non-MCP scenario — which is how it was found.*

**The bug.** `DESIGN.md` §3 says containment is *"a structural property of the machine, not
editorial discipline in report text."* It is — **for two artifacts that share a tool name
space.** Nothing checked that they did. The tiers never meet: realized labels the *events of
the trace*, the capability tiers label the *tools of the inventory*, and each is
individually correct on its own input.

So a non-MCP agent — an OpenInference trace emitting bare `fetch`, and a hand-written
inventory forced to emit qualified `local__fetch` — produced **this, in one report, with no
complaint**:

```
[REALIZED]   exfil_trifecta            (all three legs)
[REACHABLE]  sensitive_to_exfil_sink   (two-leg — NOT the trifecta)
```

A **realized trifecta that the reachable tier says cannot be wired.** `realized ⊄
reachable` — the guarantee the entire tier design rests on, violated silently, in the one
place this project calls it structural. D8 already called the join *"a fixture assertion —
an executable test, not a hope"*, and it is: `tests/test_inventory.py` pins it **for our own
artifacts**. Nothing pinned it for the **user's**. A guarantee that holds only for inputs we
happened to author is not a guarantee; it is a coincidence.

**Decision, two parts.**

1. **`server` is optional. A tool with no server is identified by its bare name.**
   Qualification exists for exactly one reason (D8): under MCP, two servers may each expose
   a `read`. An agent whose tools are ordinary local functions — LangChain, LlamaIndex, a
   hand-rolled loop — has **no servers** and a flat name space, and its trace emits
   `send_email`, not `local__send_email`. Forcing a fake server on such a stack **invents an
   identity its trace does not carry**, and the join could then *never* hold. This was not a
   cosmetic wart: it made the containment guarantee unsatisfiable for every non-MCP user.
   `schema/inventory.schema.json` and `SPEC.md` §7.2 updated; this **widens** the input
   contract (every existing inventory still validates).

2. **The composability join is computed at runtime and disclosed when it fails.** Two
   failures, and the report distinguishes them because the reader's next move differs:
   *disjoint* (no shared names at all — almost always a name-space mismatch) and *unlisted*
   (the trace called a tool the inventory lacks — the inventory is incomplete, D8's subset
   condition). Both mean the tiers are **not describing one system** and must not be
   compared. stderr warns too.

**We disclose; we do not repair.** We cannot know whether the inventory is incomplete or the
two artifacts simply disagree on names — the evidence is identical. Renaming a user's tools
to force a match would put a tool in a finding **that no artifact named**, which is the same
line D2 draws about topology and invariant 4 draws about causation. The report offers both
readings and picks neither.

**Why this was invisible for three phases.** Every fixture in the repo was MCP-shaped and
produced by the same capture, so the join always held. The bug was reachable only from an
input we had never written — which is the argument for scenario 4 in `USAGE.md` existing at
all, and for building it from a *real* non-MCP shape rather than a sketch.

## D15 — Cross-agent flow: we already detect it, we denied it, and it broke containment

*Taken 2026-07-13, in answer to "why is cross-agent multi-hop a non-goal — is anything in
the architecture preventing it?" The answer was: nothing. We were already doing it.*

**The finding.** `SPEC.md` §8 listed cross-agent multi-hop as an explicit non-goal, one that
*"must never appear in output, docs, or `--help` as current capability."* Instead of trusting
that, I ran one. **It fires.** The engine folds a trace in time order carrying **one global
taint set and no notion of an agent at all**, so a secret read by agent A and emailed out by
agent B — in one trace — has *always* produced a realized finding.

We shipped the capability, denied it in the spec, and reported it wrong. Two consequences,
and the first is why this was a bug rather than a happy accident:

1. **Containment breaks — the second instance today.** Reachable asks whether **one** agent
   context holds every leg. In a genuine cross-agent flow, **by definition none does** — that
   is what makes it cross-agent. So reachable goes silent *exactly* when realized fires:
   `realized ⊄ reachable`, the guarantee `DESIGN.md` §3 calls *"a structural property of the
   machine."* Unlike **D14** this is not a naming accident; it falls straight out of the tier
   definitions, which is worse.
2. **The finding hid the hop.** The path printed as `r_read -> s_send`, as though one agent
   did both. A flow that changes hands is a materially bigger claim than one that does not.

**The identity was in the trace the whole time.** A tool span's nearest ancestor of kind
`AGENT` *is* the agent that ran it, and both `parent_id` and the span kind are already among
the six OpenInference attributes we read (§7.3). Nothing had ever looked at them together.
No new format, no new attribute, no new convention — `loader.resolve_agents`.

**Decision (Part 1 — shipped).**

- `Event.agent` — the nearest ancestor `AGENT` span. An **opaque identity**: the engine
  compares two for equality to see whether a flow changed hands, and never parses one. It is
  a *span id*, deliberately **not** an inventory context id — the trace and the inventory name
  agents in different vocabularies, and guessing a mapping is the mistake **D14** was.
- Findings `1.0 → **1.1**` (additive, a minor bump under §7.1's own policy): `agents`,
  `crosses_agents`, `legs[].agent`.
- **The report explains why reachable is silent.** Not as an aside: a reader who compares a
  REALIZED finding against a silent REACHABLE tier concludes either that the tool contradicts
  itself, or — far worse — that the silence is reassuring. It is neither. The two tiers are
  answering different questions and only one of them can see a flow that changes hands.
- `SPEC.md` §8 corrected. **Cross-*session* / cross-*trace*** (A writes today, B reads
  tomorrow) remains parked and is a genuinely different problem: different files, taint
  retention across runs, memory poisoning.

**The line this must not cross.** We observed a value in agent A's span and the same value,
verbatim, at agent B's sink. We did **not** observe a handoff — no span says *"A passed this
to B"*, and the value could have reached B by any route. Saying *"one agent handed the secret
to another"* is exactly the causal claim invariant 4 forbids, dressed up as an architectural
insight. A test forbids the words.

**Part 2 — delegation edges (shipped).** A context may declare `delegates_to`. The transitive
closure of those edges is a **delegation chain**, and a chain's pooled tools are handed to the
*same* automaton — as a synthetic `LabeledContext`, exactly as posture's union already is. So
there is **no new machinery**: three bags of tools, one machine, and
`realized ⊆ reachable ⊆ reachable-across-a-chain ⊆ posture` stays structural. Per **D1's
precedent** this redefines a Stage-1 edge, not the automaton, so it is inside the invariants;
it *is* a `SPEC.md` §5 change, hence its place here.

**The tier-honesty risk was the whole of the work.** `reachable_cross_agent` is the **weakest**
claim the tool makes: it rests on an assumption the *operator* supplied, which no captured
artifact corroborates and no trace was consulted to check. So it gets its own tier id, its own
summary and its own note; it states the assumption and whose it is (*"if the declared handoff
is wrong, this finding is wrong"*); it disclaims the stronger tier outright (*"not the
lethal-trifecta condition proper — that is reachable, and reachable did not accept here"*);
and it reports **only what reachable could not**, because emitting an exposure twice would let
the weaker claim ride on the stronger one's evidence.

**And the handoff is never inferred.** An inventory records what each agent can *reach*, never
who it *talks to*. Undeclared means the tier does not run — honest, and the only option that
does not manufacture the finding. A handoff naming a context that does not exist **fails the
load** rather than silently shrinking the chain, which would under-report.

Findings `1.1 → **1.2**`: the `tier` enum gains `reachable_cross_agent`. A consumer switching
on `tier` **must not** fold it into `reachable`.

---

## D16 — A `Family` must declare which tiers may report it *(OPEN — deferred to Phase 4)*

> **This decision is NOT taken.** It is recorded here because four files now point at
> "D16", and a decision number that resolves to nothing is its own kind of silence. Take
> it deliberately at the start of Phase 4; do not let it get settled by whoever writes the
> code first. That is exactly what `OPEN_QUESTIONS.md` used to prevent.

*Raised 2026-07-13, while checking a claim this repo had repeated in three places.*

**The finding.** `DEBT.md`, `ROADMAP.md` and `engine.py`'s own `FAMILIES` comment all said
that adding the action-hijack family was *"adding a row to `FAMILIES`; the automaton does
not move."* The second half is true. **The first half is false**, and it was verified in
code rather than prose: `satisfied_families()` is called by **every** tier, and one of its
call sites is `_accept` — the **realized** path.

```
_accept                       engine.py:274   <- REALIZED
reachable_collapse            engine.py:498/502
detect_capability             engine.py:562   <- REACHABLE
detect_reachable_cross_agent  engine.py:618/627
```

So dropping an `action_hijack` row into `FAMILIES` starts emitting **realized**
action-hijack findings on the very next run — which is precisely what Phase 4 forbids:
*"posture + reachable only — hold realized until there's a defensible causation signal."*
A contributor following our own documentation would have shipped the one finding the
roadmap says we must not make. **The docs were a trap, and they were our trap.**

**The shape of the fix (not yet decided, deliberately).** `Family` gains a declaration of
which tiers may *report* it — acceptance is unchanged, so the machine's states, lattice
and guard genuinely do not move; what moves is the **reporting gate**. That is still a
change to the tier semantics in `SPEC.md` §5, and therefore a decision, not an
implementation detail.

**Why it is not being taken now.** Action-hijack's realized tier is blocked on *"no
defensible causation signal"*, and `path_basis` (D5) is the beginning of a vocabulary for
one, not an answer. Whether a genuine `causal` chain is *sufficient* to release
action-hijack realized is a **halt-and-ask**. Deciding the gate's shape before that
question is answered would be deciding the answer by accident.

Until D16 is taken, the four `sink:impact` catalog entries stay **inert** — live data that
no family accepts on. That inertness is not an accident to be cleaned up; it is the
cleanest demonstration the project has that **coverage lives in the data and acceptance
lives in the fixed machine.**

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
