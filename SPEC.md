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

> **NOTE (Phase 2): see `OPEN_QUESTIONS.md` §1.** "Match = exact" below is in
> tension with `DESIGN.md` §8 ("normalized **substring** match") and with §5's
> realized step 3 ("a tagged value **appears in** a sink span's `inputs`"). Phase
> 1 implements containment of the untransformed value; the three passages must be
> reconciled to one wording in Phase 2.

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
