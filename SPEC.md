# SPEC.md — technical specification

Source of truth for behavior. Code conforms to this; when they disagree, fix one
of them deliberately (don't let them silently diverge). Companions: `CLAUDE.md`
(process + invariants), `ROADMAP.md` (sequencing), `DESIGN.md` (engine
architecture: the property automaton, stage seam, and technology decisions).

## 1. Goal and scope

Detect data-exfil exposure in MCP/agent systems by analyzing a captured trace
plus the MCP manifest, and report findings in three tiers. **v1 scope is the
exfil family** (untrusted source → sensitive data → outbound sink). The
action-hijack family (source → impact sink) is fast-follow, posture/reachable
only. See §8 for explicit non-goals.

## 2. Data model

Spans are normalized into a flat **Event** stream; every tier is a projection
over the same stream + the manifest.

```
Event:
  id:           str            # stable id (span id)
  parent_id:    str | None     # causal/span parent
  ts:           float          # start time
  actor:        str            # agent / sub-agent / tool that acted
  action:       str            # e.g. tool_call, tool_result, llm_msg
  tool:         str | None     # tool name when applicable
  inputs:       dict | None    # tool args / message content (payload-level)
  outputs:      dict | None    # tool result / model output (payload-level)
  roles:        set[str]       # role tags assigned by the catalog (§4)
  values:       list[Value]    # extracted taint-bearing values (§6)
```

`inputs`/`outputs` require **payload-level** spans. If absent, realized
detection is `UNAVAILABLE` for that event (see §7 degradation).

## 3. Two finding families (one engine)

| Family | Legs required | Sink subtype | Harm |
|---|---|---|---|
| Exfil trifecta | untrusted_source + sensitive_data + sink | `sink:exfil` | data leaves the boundary |
| Action hijack | untrusted_source + sink | `sink:impact` | untrusted content drives a consequential action |

Same path engine; the family is determined by which sink subtype terminates the
path and whether the sensitive leg is required.

## 4. Role catalog

The catalog is **data**, not code. A new tool/source/sink is a catalog entry.
Architecturally, the catalog is the engine's **labeling function** — the only
user-tunable layer of detection; the automaton itself is fixed (`DESIGN.md` §4).

```
CatalogEntry:
  match:   {tool: str|regex} | {tag: str}    # how to recognize
  role:    untrusted_source | sensitive_data | sink
  subtype: exfil | impact | null             # for sinks
  note:    str                               # human rationale, shown in output
```

Default v1 entries (extend via user catalog, see §7):

- `untrusted_source`: web/url fetch; inbound email; issue/PR/comment text;
  RAG / retrieved-document reads; shared-file reads; another agent's output.
- `sensitive_data`: secret/credential reads; PII; source-code reads; internal
  doc / private path reads; DB row reads; agent memory reads.
- `sink:exfil`: `http_post` / outbound request; external email send;
  image-render-by-URL; DNS; write to a shared/public location.
- `sink:impact` (catalog present, used by action-hijack in fast-follow):
  `shell.exec`; destructive file/db writes; transfers; PR merge.

Labeling is heuristic and *will* be imperfect; that is acceptable and is the
contributor flywheel. Every finding cites which catalog entry assigned each role
so a user can see and correct it.

## 5. Tier definitions and algorithms

All three tiers are projections of **one fixed property automaton** — a
leg-set lattice whose acceptance condition is the family's sink with the
required legs present in the path's ancestry (source/sensitive order is
immaterial; the sink terminates the path) — evaluated over progressively
weaker inputs. Realized runs it over the trace event graph with a
value-match guard; reachable over the schema topology graph without the guard;
posture over the bag of manifest roles without edges. **Realized ⊆ reachable ⊆
posture by construction.** Full formulation in `DESIGN.md` §§2–3.

Three tiers, three different inputs. All three are computable from **one trace +
the manifest** — reachable does not require multiple runs.

### Posture — keyed to the manifest
Compute the set of roles present among the manifest's tools. Emit a finding if a
family's required legs are all present (exfil: all three; hijack: source +
impact). Breadth: covers every present combination. This tier overlaps existing
static scanners — **never headline it.**

### Reachable — keyed to the tool I/O schemas
Build a type-compatibility graph: tool A's output type can feed tool B's input
type. Emit a finding if a path connects a `source`-role tool to a `sink`-role
tool (through a `sensitive` tool for the exfil family). It means "a data path
*connects* even though no run wired it." Still no runtime required.

### Realized — keyed to the trace
1. Tag values originating in `untrusted_source` and `sensitive_data` spans
   (§6).
2. Propagate tags forward by value identity across events.
3. Emit a finding if a tagged value appears in a `sink` span's `inputs` and the
   causal/temporal ancestry includes the required legs (leg order immaterial).
4. Report the concrete path (the ordered events) and mask sensitive values.

Output language is fixed: *"tainted data observed reaching <sink>"* — never a
causal/attack claim (CLAUDE.md invariant 4).

## 6. Taint matching (v1)

- A `Value` is a string extracted from span payloads (secret-like tokens, file
  contents, PII matches, or whole tool outputs).
- Match = **exact** after light normalization (trim, case-fold, collapse
  whitespace). Nothing more.
- **Explicitly not handled in v1:** encoded (base64/hex), split/concatenated,
  summarized, or paraphrased values. These break verbatim matching by design.
  Realized therefore covers the *verbatim-exfil subset only* — state this in the
  README and in `--help`. Do not attempt to paper over it.

## 7. Input/output contracts

The on-disk trace-fixture format (span schema + attribute->Event mapping) is
defined in `FIXTURES.md`.

**Inputs**
- Trace: OTel GenAI / OpenInference spans, JSON lines. Required fields per event:
  id, parent/trace linkage, start time, tool name, and **payload-level**
  input/output. Missing payloads → realized `UNAVAILABLE`, posture/reachable
  still run.
- Manifest: MCP server/tool config (the same file the host loads).
- User catalog: optional overlay file that adds/overrides role entries (§4).
  This is how a user extends coverage to their own stack without touching code.

**Outputs**
- Findings **NDJSON** (stable schema): one finding object per line, keys sorted
  (`sort_keys=True`), **emitted as findings are found** — an append-stream,
  never a monolithic end-of-run document (`DESIGN.md` §6). Fields: family,
  tier, legs with citing catalog entries, path (for realized), masked values,
  confidence note.
- Human report: tiered, each finding labeled with its tier badge.
- SVG: the path visualization (the shareable artifact).
- SARIF: fast-follow, for CI / code-scanning surfaces.
- Emission surface is stdout/files **only**. Core never delivers findings over
  the network; detection-to-action wiring is the user's plumbing consuming the
  NDJSON stream (`DESIGN.md` §7).

**Invocation shape**
```
trifecta-lens <manifest> --trace <spans.jsonl> [--catalog user.yaml]
trifecta-lens <manifest>                 # posture + reachable only (no trace)
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
