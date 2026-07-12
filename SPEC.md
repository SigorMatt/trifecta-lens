# SPEC.md — technical specification

Source of truth for behavior. Code conforms to this; when they disagree, fix one
of them deliberately (don't let them silently diverge). Companions: `CLAUDE.md`
(process + invariants), `ROADMAP.md` (sequencing), `DESIGN.md` (engine
architecture: the property automaton, stage seam, and technology decisions).

## 1. Goal and scope

Detect data-exfil exposure in MCP/agent systems by analyzing a captured trace
plus the agent's captured tool inventory (§7), and report findings in three
tiers. **v1 scope is the exfil family** (untrusted source → sensitive data → outbound sink). The
action-hijack family (source → impact sink) is fast-follow, posture/reachable
only. See §8 for explicit non-goals.

## 2. Data model

Spans are normalized into a flat **Event** stream; every tier is a projection
over the same stream + the inventory.

```
Event:
  id:           str            # stable id (span id)
  parent_id:    str | None     # causal/span parent
  ts:           float          # start time
  actor:        str            # agent / sub-agent / tool that acted
  action:       str            # e.g. tool_call, tool_result, llm_msg
  tool:         str | None     # tool identity when applicable (see below)
  inputs:       dict | None    # tool args / message content (payload-level)
  outputs:      dict | None    # tool result / model output (payload-level)
  roles:        set[str]       # role tags assigned by the catalog (§4)
  values:       list[Value]    # extracted taint-bearing values (§6)
  role_labels:  dict[str, RoleLabel]   # role -> {entry, note} that assigned it (§4)
```

`role_labels` is how a finding cites *why* a role was assigned — and *which entry
to edit* — without the engine ever learning a tool name: the catalog (Stage 1)
attaches the citation to the event, and the engine reads it **keyed by role**
(`DESIGN.md` §5). Both halves matter: the `note` is what a human reads to judge the
call, the `entry` id is what they change to correct it.

### 2.1 The topology values (the capability tiers' input)

Realized projects over the Event stream. Posture and reachable project over the
**captured inventory** (§7), labeled by the same catalog (§4). That gives the
second of `DESIGN.md` §1's two graphs:

```
LabeledTool:    name: str            # server-qualified, <server>__<tool>
                roles: set[str]      # assigned by the catalog
                role_notes: dict[str,str]

LabeledContext: id: str              # one agent context
                provenance: str      # the human-written capture note
                tools: [LabeledTool] # its EFFECTIVE exposed tool set

LabeledStack:   contexts: [LabeledContext]
```

These are the **only** things the engine sees of an inventory. It never sees the
inventory file's shape, the `tools/list` entries, or the `<server>__<tool>`
separator — those are Stage 1's business (`DESIGN.md` §5). Reachable runs per
`LabeledContext`; posture runs over the union of their tools.

`inputs`/`outputs` require **payload-level** spans. If absent, realized
detection is `UNAVAILABLE` for that event (see §7 degradation).

**Tool identity is server-qualified under MCP.** A real MCP trace names a tool by
its server (two servers may each expose a `read`), so `tool` carries the
**`<server>__<tool>`** form the instrumentation emits (e.g.
`filesystem__read_text_file`) — the same name space the inventory records, which
is what lets a trace and an inventory join on shared identity (§7,
`DECISIONS.md` D8). The Phase 1 flat fixtures carry bare names (`vault`,
`webhook`); both are valid `tool` values. The OTLP front-end
(`load_otlp_trace`, task 2.7) carries `tool.name` through verbatim — qualifying is
the instrumentation's job, not the loader's, and the engine still sees only roles.

## 3. Finding families (one engine)

| Family id | Legs required | Sink subtype | Harm |
|---|---|---|---|
| `exfil_trifecta` | untrusted_source + sensitive_data + sink | `sink:exfil` | sensitive data leaves the boundary, and untrusted content was also in the path |
| `sensitive_to_exfil_sink` | sensitive_data + sink | `sink:exfil` | sensitive data leaves the boundary; **no untrusted-source leg observed** |
| `action_hijack` | untrusted_source + sink | `sink:impact` | untrusted content is in the path of a consequential action |

Same path engine; the family is determined by which sink subtype terminates the
path and which legs are present.

### 3.1 The two-leg family (`sensitive_to_exfil_sink`)

`sensitive_to_exfil_sink` is a **relaxation of the same exfil automaton**, not a
separate detector: it drops the `untrusted_source` leg from the trifecta's
acceptance condition and keeps everything else, including the verbatim guard
(§6). Formally,

> a trifecta finding is exactly a two-leg finding **plus** an observed
> `untrusted_source` leg.

It exists because sensitive data reaching an outbound sink is a real, reportable
exposure even when no untrusted content was observed in the path — and because
inventing a source leg to make the trifecta accept would be a lie about the
threat model. (The v1 realized anchor is precisely this case: a
direct-instruction run in which the principal's own prompt, not ingested
untrusted content, precedes the vault→webhook flow.)

**It is the lesser finding, and must always read as one.** Binding output rules:

- Its family id is `sensitive_to_exfil_sink`, **never** `exfil_trifecta`.
- Every finding names the source leg explicitly, as observed or not-observed:
  `legs_observed` and `legs_not_observed` are both required fields, and a
  two-leg finding carries a note stating the `untrusted_source` leg was not
  observed and that this is **not** a trifecta finding.
- It is **never** headlined as the trifecta result, and never borrows the
  trifecta's severity or language (`CLAUDE.md` invariant 3).
- The summary text is the same fixed flow-not-causation line (§5).
- Realized ⊆ reachable ⊆ posture continues to hold **within each family**.

The trifecta family remains defined and available; it simply does not accept on a
trace with no untrusted-source leg. **That silence is correct, and must not be
"fixed" by relabeling** — neither a sensitive read nor the principal's own prompt
is an untrusted source.

## 4. Role catalog

The catalog is **data**, not code. A new tool/source/sink is a catalog entry.
Architecturally, the catalog is the engine's **labeling function** — the only
user-tunable layer of detection; the automaton itself is fixed (`DESIGN.md` §4).

```
CatalogEntry:
  id:      str                               # stable entry id, cited in output
  match:   {tool: str|regex}                 # how to recognize
  role:    untrusted_source | sensitive_data | sink
  subtype: exfil | impact | null             # for sinks
  note:    str                               # human rationale, shown in output
```

**Concretely (v1).** The catalog is a YAML file (`trifecta_lens/catalogs/exfil_v1.yaml`,
loaded by `trifecta_lens/catalog.py` — Stage 1). `match.tool` is a **regex,
fully anchored** (`re.fullmatch`), evaluated against the event's `tool` name — which
is server-qualified under MCP (§2), so an entry may match either a bare name
(`vault`) or a qualified one (`filesystem__read_text_file`). A tool matching several
entries receives the **union** of their roles; the note cited for a role is the
first matching entry's, in file order, so labeling is deterministic. `{tag: ...}`
matching is **not implemented in v1** — the captured inventory carries no tags.

A `--catalog user.yaml` **overlay** is the user's extension point: its entries are
consulted **before** the defaults, so it can add roles the defaults miss and
override the note cited for one. It cannot remove a default entry in v1.

The catalog is the **only** tunable layer. Adding coverage is adding an entry —
never a branch in the engine (`CLAUDE.md` invariant 2, enforced by the stage-seam
gate).

**What v1 actually ships** (`catalogs/exfil_v1.yaml` is the source of truth; this
list is its summary, and a test keeps the two honest):

- `untrusted_source`: web/URL fetch (incl. the MCP `fetch` server); issue / PR /
  comment text; inbound email & messages.
- `sensitive_data`: secret/credential reads; local file **content** reads (the MCP
  `filesystem` server's `read_*` tools); agent memory reads.
- `sink:exfil`: outbound HTTP request; email/chat send; **write to a shared/public
  location** (a comment on a public issue publishes the payload just as surely as a
  POST does); the demo `notify` sink.
- `sink:impact` (catalog present; **no v1 family accepts on it** — action-hijack is
  fast-follow, §3): `shell.exec`; destructive file writes; PR merge.

**Deliberately NOT in v1, and why.** RAG / retrieved-document reads are a real
untrusted source, but real tools spell them `search`, `query`, `retrieve` — names
shared with a dozen harmless things, including `filesystem__search_files`, which
returns *names*, not content. No captured trace yet carries a RAG read, and a
pattern invented for one would be a guess. Likewise directory listings and file
metadata are **not** `sensitive_data`: they return names, and labeling them would
make every `ls` a leg of an exfil finding. Coverage lands when a real trace
justifies it.

Coverage is deliberately conservative, because **a wrong label is worse than a
missing one**: a missing label loses a finding, while a wrong one manufactures a
confident finding about a role nobody assigned — and this tool's only asset is that
it says nothing it cannot support.

Labeling is heuristic and *will* be imperfect; that is acceptable and is the
contributor flywheel. Every finding cites the **catalog entry id** that assigned
each role, alongside the rationale — so a user can both judge the call and know
exactly what to edit or override. See `CONTRIBUTING.md`.

## 5. Tier definitions and algorithms

All three tiers are projections of **one fixed property automaton** — a
leg-set lattice whose acceptance condition is the family's sink with the
required legs present in the path's ancestry (source/sensitive order is
immaterial; the sink terminates the path) — evaluated over progressively
weaker inputs. Realized runs it over the trace event graph with a
value-match guard; reachable over the co-exposure topology graph without the
guard; posture over the bag of inventory roles without edges. **Realized ⊆ reachable ⊆
posture by construction.** Full formulation in `DESIGN.md` §§2–3.

Three tiers, three different inputs. All three are computable from **one trace +
the inventory** — reachable does not require multiple runs.

### Posture — keyed to the inventory, across all contexts
Compute the set of roles present in the **union** of the tool inventory's contexts
(§7). Emit a finding if a family's required legs are all present anywhere in the
stack (exfil: all three; hijack: source + impact) — **even if no single agent
context can reach them all**. Breadth: covers every present combination. This tier
overlaps existing static scanners — **never headline it.**

### Reachable — keyed to co-exposure within one agent context
Emit a finding if a family's required legs are **all exposed to the same agent
context's effective tool set** — i.e. one run *could* wire them, though none did.
This is the lethal-trifecta condition proper. Still no runtime required.

**Reachable is NOT a tool-I/O type-compatibility graph.** That was the original
design and it is wrong (`DECISIONS.md` D1/F2): in an agent, the **model's context
is a universal connector** — data flows tool → model → tool, and the model will
retype, reformat and copy any string anywhere. Schema type-compatibility therefore
does not *constrain* reachability, `outputSchema` is optional and usually absent
in practice, and the resulting graph is near-fully-connected. Such a tier would
satisfy `realized ⊆ reachable ⊆ posture` **trivially, while carrying no
information** — the tier-honesty failure, occurring inside the tier structure.

**Binding on this tier:** on a single-context stack, reachable is *necessarily*
equal to posture. The tool must **detect that collapse and disclose it** ("reachable
adds no information on this stack: all legs share one context") rather than
presenting a tier that silently says nothing.

### Realized — keyed to the trace
1. Tag values originating in `untrusted_source` and `sensitive_data` spans
   (§6).
2. Propagate tags forward by value identity across events.
3. Emit a finding if a tagged value appears in a `sink` span's `inputs` and the
   causal/temporal ancestry includes the required legs (leg order immaterial).
4. Report the concrete path (the ordered events) and mask sensitive values.

**One finding per accepting sink event, at the strongest family that accepts.**
A sink event that satisfies the trifecta's legs also satisfies the two-leg
family's (the latter's legs are a subset), so reporting both would double-count
one flow. The engine emits the trifecta finding in that case, and the two-leg
finding when the `untrusted_source` leg is absent. Either way the finding states
which legs were observed and which were not (§3.1), so the weaker result can
never be mistaken for the stronger one.

Output language is fixed: *"tainted data observed reaching <sink>"* — never a
causal/attack claim (CLAUDE.md invariant 4). This is identical across families:
the family is carried by the `family` field and the leg lists, never by
escalating the verb.

## 6. Taint matching (v1)

- A `Value` is a string extracted from span payloads (secret-like tokens, file
  contents, PII matches, or whole tool outputs).
- **Match = CONTAINMENT of the untransformed value** (`DECISIONS.md` D3): the
  value matches when it **occurs in** a payload string of the sink, after light
  normalization (trim, case-fold, collapse whitespace).

  **"Verbatim" constrains transformation *of the value*, not the surrounding
  payload.** A secret pasted into a larger request body has still reached the
  sink; requiring the value to *equal* a whole field would silently miss the
  common real case. This is what §5's realized step 3 ("a tagged value **appears
  in** a sink span's `inputs`") and `DESIGN.md` §8 ("normalized substring match")
  already meant. Whole-field equality is the strictly weaker special case.

- **Explicitly not handled in v1:** encoded (base64/hex), split/concatenated,
  summarized, or paraphrased values. These break verbatim matching by design.
  Realized therefore covers the *verbatim-exfil subset only* — state this in the
  README and in `--help`. Do not attempt to paper over it.

### 6.1 Extraction parameters — fixed, and disclosed

Matching is bounded by declared **extraction parameters** (`DESIGN.md` §4,
`DECISIONS.md` D4). They are **fixed**, not user-tunable: the catalog stays the
only knob (invariant 2). But they **must be disclosed**, because an undisclosed
threshold silently bounds what the realized tier can see — which makes "no
finding" un-auditable, the same honesty failure as an overclaim, pointed the
other way.

| Parameter | v1 value | Meaning |
|---|---|---|
| `min_value_chars` | 8 | Values shorter than this are not tracked — a short string collides with ordinary payload text and yields noise, not evidence. |
| `match` | `containment` | Per above. |
| `normalization` | `trim`, `casefold`, `collapse-whitespace` | Light only. Nothing more. |

Every finding carries these under a **`detected_under`** field, and the human
report states them. The `min_value_chars` value is justified by a **measured**
false-positive rate over the benign corpus — a number, not an assertion.

## 7. Input/output contracts

The on-disk trace-fixture format (span schema + attribute->Event mapping) is
defined in `FIXTURES.md`.

**Inputs**
- Trace: OTel GenAI / OpenInference spans, JSON lines. Required fields per event:
  id, parent/trace linkage, start time, tool name, and **payload-level**
  input/output. Missing payloads → realized `UNAVAILABLE`, posture/reachable
  still run.
- **Tool inventory**: a **captured** artifact — one file, holding a `contexts[]`
  array; each context is an id, a human-written provenance note, and its
  **effective exposed tool set** (the `tools/list` entries actually reachable by
  that agent context). Posture reads the union of contexts; reachable reads each
  context. Each tool entry records the verbatim `tools/list` object under `tool`
  plus the `server` that exposed it. Tool **identity is server-qualified** —
  `<server>__<tool>` — the same name space the trace's `tool.name` carries, so
  the two artifacts join on shared identity (the **composability join**: the
  trace's tool names are a subset of the inventory's; `DECISIONS.md` D8). The
  inventory front-end is `trifecta_lens/inventory.py` (Stage 1); qualification is
  a front-end concern and the engine never sees the separator (`DESIGN.md` §5).

  > **The MCP "manifest" does not contain tools.** An earlier draft of this spec
  > said the manifest was "MCP server/tool config (the same file the host loads)."
  > That is **false** (`DECISIONS.md` D2/F1). The file the host loads
  > (`claude_desktop_config.json` / `.mcp.json`) carries only
  > `mcpServers: {command, args, env}` — launch config. Tool definitions (`name`,
  > `description`, `inputSchema`, optional `outputSchema`, `annotations`) exist
  > **only at runtime**, returned by a `tools/list` request to a *running* server.
  > Core may not go get them: launching a server and speaking a transport to it
  > violates invariant 1. Hence a **captured** inventory, produced by a capture
  > step outside core — the same architectural move as `demo/`.
  >
  > That capture step ships as **`trifecta-capture`** (the `trifecta_capture`
  > package, installed with the `capture` extra — outside the analyzer package, so
  > the no-network gate on core still holds structurally). It reads the user's own
  > host config, launches each configured server over stdio, records `tools/list`
  > verbatim, and writes this artifact. It **lists** capability; it calls no tool.
  > Contexts are declared by the operator (`--context id=serverA,serverB`); with
  > none declared the whole config is one context, which is honest and is also the
  > collapse case reachable discloses (`DECISIONS.md` D1). Provenance is never
  > written in the operator's voice: their `--note` is theirs, and when there is no
  > note the artifact **says so** rather than describing a context it cannot know.
  >
  > The inventory records the **effective** tool set, not the *cause* of it. A
  > context narrowed by a subagent allowlist, a deny list, or a smaller server
  > loadout all look identical: a smaller tool set. We do not model why. This is
  > **flow-not-causation applied to topology**.

- The launch config (`mcp.json`) remains useful only for **server identity**, and
  is optional.
- User catalog: optional overlay file that adds/overrides role entries (§4).
  This is how a user extends coverage to their own stack without touching code.

**Outputs**
- Findings **NDJSON** (frozen public schema, v1): one finding object per line,
  keys sorted (`sort_keys=True`), **emitted as findings are found** — an
  append-stream, never a monolithic end-of-run document (`DESIGN.md` §6).

### 7.1 The frozen findings schema (public contract)

The NDJSON line shape is a **public API**, versioned and frozen as of v1. The
machine-readable contract is `schema/findings.schema.json` (JSON Schema); this
section is its prose companion, and `tests/test_findings_schema.py` fails if the
code, the schema file, and this section ever disagree.

- **In-band version.** Every line carries `schema_version` (currently `"1.0"`).
  The NDJSON stream has no header, so a consumer parsing a single line must be
  able to tell which contract it is reading; the version rides on the line.
- **Two line variants**, discriminated by `tier`:
  - **Realized** (`tier: "realized"`) — evidence from the trace. Keys:
    `schema_version`, `tier`, `family`, `summary`, `note`, `scope`, `sink`
    (`{event, tool}`), `path`, `path_edges` (`[{from, to, basis}]`),
    `path_basis`, `legs` (`[{role, event, tool, note, catalog_entry}]`),
    `legs_observed`, `legs_not_observed`, `masked_values`, `detected_under`
    (`{match, min_value_chars, normalization}`).
  - **Capability** (`tier: "posture" | "reachable"`) — read from the inventory,
    nothing observed. Keys: `schema_version`, `tier`, `family`, `summary`,
    `note`, `scope`, `sink` (`{tool}`), `context` (`{id, provenance}`), `legs`
    (`[{role, tools:[{tool, note, catalog_entry}]}]`), `legs_present`,
    `legs_absent`, `disclosure`. A capability line **structurally cannot** carry
    realized's evidence keys (`path*`, `masked_values`, `legs_observed`,
    `detected_under`) — it is a different type with nowhere to put them
    (`CLAUDE.md` invariant 3).
- **Compatibility policy.** Adding an optional field is a **minor** bump
  (`1.0 → 1.1`); consumers **must ignore unknown fields**. Removing, renaming,
  or retyping a field, or changing a field's meaning, is a **major** bump
  (`1.x → 2.0`). The frozen key sets are enforced by test, so no field can move
  without the version moving with it.
- Human report: tiered, each finding labeled with its tier badge.
- SVG: the path visualization (the shareable artifact).
- SARIF: fast-follow, for CI / code-scanning surfaces.
- Emission surface is stdout/files **only**. Core never delivers findings over
  the network; detection-to-action wiring is the user's plumbing consuming the
  NDJSON stream (`DESIGN.md` §7).

**Invocation shape**
```
trifecta-lens --inventory <inventory.json> --trace <spans.jsonl> [--catalog user.yaml]
trifecta-lens --inventory <inventory.json>     # posture + reachable only (no trace)
trifecta-lens --trace <spans.jsonl>            # realized only (no inventory)
```

## 8. Explicit non-goals (parked — do not claim support)

- Transformed taint (encoding, splitting, paraphrase).
- Cross-agent multi-hop (source → memory → second agent → sink).
- Memory-poisoning affecting *future* sessions; cross-session state.
- Any causal proof that untrusted content drove an action.
- Live/streaming mode (consuming spans as agents run). North-star direction
  only (`ROADMAP.md`); the engine constraints that keep it cheap to add later
  are already binding (`DESIGN.md` §6).
- Built-in action hooks / outbound delivery of findings. **Permanently
  forbidden from core, not merely parked** — findings emit to stdout/files
  only (`DESIGN.md` §7).

These are the genuinely differentiated, research-frontier cases. They may appear
in `ROADMAP.md` as north-star direction. They must never appear in output, docs,
or `--help` as current capability.
