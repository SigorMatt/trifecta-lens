# trifecta-lens

**Your agent probably could exfiltrate your data. It probably hasn't yet. That gap
is the finding.**

trifecta-lens is a **read-only** analyzer for MCP-based agent systems. It reads a
captured execution **trace** and a captured **tool inventory**, and answers three
different questions — kept strictly apart, because they carry very different
weight:

| tier | the question | what it takes to say it |
|---|---|---|
| **realized** | a run **did** wire it | a sensitive value was **observed** at an outbound sink, verbatim, in the trace |
| **reachable** | one agent context **could** wire it | all three legs are exposed to the *same* context. No run was observed doing so. |
| **posture** | the legs exist **somewhere** in the stack | the roles are present in the union of contexts. Weakest tier; overlaps ordinary static scanners. |

`realized ⊆ reachable ⊆ posture`, structurally: the tiers are the same fixed
automaton run over more or less evidence.

The middle tier is the one that pays. Almost nobody has a captured trace of their
agent leaking something. Almost everybody is one bad web page away from being able
to — and that is a fact about their **topology**, which they *can* check today.

## What it says about a real stack

Our own captured MCP stack — the [`fetch`](https://github.com/modelcontextprotocol/servers)
reference server, `filesystem` scoped to a vault directory, and an inert `notify`
sink — analyzed from a real OTLP trace and a real `tools/list` inventory:

```text
$ trifecta-lens --trace fixtures/demo_mcp_trace.otlp.json --inventory fixtures/inventory.json

[REALIZED]  sensitive_to_exfil_sink  (two-leg — NOT the trifecta)
  tainted data observed reaching notify__send

  path   485697cce52b7fa2 (filesystem__read_text_file, sensitive_data) -> 4b85b6426897725d (notify__send, sink:exfil)
  basis  temporal — the steps were observed in this ORDERING; the trace carries no parent-child link between them, so this does not establish that one fed the other
  value  sk-demo-...MASKED
  legs NOT observed:
    untrusted_source  not seen anywhere in this trace
...
[REACHABLE]  exfil_trifecta  (all three legs)
  all legs of exfil_trifecta are exposed to agent context 'assistant'; a single run could wire them to notify__send
...
  reachable states capability, not observation: every leg is exposed to this one agent context, so a single run could wire them together. No run was observed doing so. This is the lethal-trifecta condition as a topology — it is not evidence that any data moved.
```

Read the two together and you have the product:

- The run that **was** captured moved a secret to an outbound sink — but no
  untrusted content was in that path, so it is reported as the **lesser two-leg
  family**, and the missing leg is named. It is not called a trifecta.
- The **full trifecta** — untrusted web content, the vault, and the outbound sink,
  all three exposed to the *same* `assistant` context — is **reachable**. One run
  could wire it end to end. **No run was observed doing so.**
- The `triage` context in the same stack **cannot** wire it: it has no outbound
  leg. Posture is structurally unable to see that distinction, which is why
  reachable is a tier and not a restatement.

Could, but didn't. That sentence is the whole tool.

## 60 seconds

**Not on PyPI yet** — install from the repo. (When it is published, this line
becomes `pipx install "trifecta-lens[capture]"`; we are not going to write that
here before it is true.)

```
pipx install "trifecta-lens[capture] @ git+https://github.com/SigorMatt/trifecta-lens"

# 1. Capture your agent's tool inventory. Launches your STDIO servers, asks each
#    one tools/list, calls nothing. --context declares which agent sees which
#    servers — that declaration is what the reachable tier reads.
trifecta-capture --config .mcp.json --out inventory.json \
    --context assistant=github,fetch,vault \
    --context triage=github \
    --note triage="our issue-triage subagent"

# 2. Read your stack.
trifecta-lens --inventory inventory.json

# 3. If you have an OpenInference/OTLP trace of a run, add it and the realized
#    tier turns on too.
trifecta-lens --trace run.otlp.json --inventory inventory.json \
    --findings findings.ndjson --svg path.svg
```

The analyzer itself has one runtime dependency (a YAML parser) — a dependency tree
you can read in one screen is a feature for a tool whose whole pitch is
auditability. The MCP SDK rides only on the `[capture]` extra.

The inventory alone gets you posture and reachable — the two tiers that need no
trace at all. A tier with no input **does not run, and says so**; it never reports
a clean result it did not check for.

### If you don't use MCP

The engine has never heard of MCP, and never will. It reads exactly three things about each
tool: **which agent context reaches it, an optional server, and its name.** A LangChain,
LlamaIndex, CrewAI or hand-rolled agent works today — its tools are ordinary functions, so
there is nothing to capture: you **write the inventory**, and it is a dozen lines.

```json
{"contexts": [
  {"id": "researcher",
   "provenance": "transcribed by hand from our agent's tool registry. Not an MCP capture.",
   "tools": [{"tool": {"name": "crm_lookup"}}, {"tool": {"name": "send_email"}}]}
]}
```

No `server` key — a flat agent has none, so a tool is identified by its bare name, which is
what its trace already emits. Point `--trace` at any OpenInference trace and all three tiers
run. The worked example, including what to do when the catalog has never heard of your CRM,
is [`USAGE.md`](USAGE.md) scenario 4.

### If your servers are remote or hosted

`trifecta-capture` launches servers over **stdio**. A remote or hosted MCP server has
no command to launch, so it cannot start one — and it will tell you so rather than
quietly leaving a leg out of your topology.

That is not a dead end, because **the inventory is a file, not a privilege**. Fetch
that server's `tools/list` response however your stack allows, and hand it over:

```
trifecta-capture --config .mcp.json --from-tools-list wiki=wiki-tools.json \
    --out inventory.json --context assistant=vault,wiki
```

Servers you *can* launch stay in `--config`; the two mix in one inventory. A tool list
that came from a real running server **is a capture, whoever fetched it** — the line
this project holds is captured-versus-fabricated, and it has never been
automated-versus-manual. The provenance note records which servers we launched and
which you supplied, and it does not claim we launched yours.

You can also skip the tool entirely and write the file. Its shape is a published
contract — [`schema/inventory.schema.json`](schema/inventory.schema.json) — and it is
small on purpose, because **the analyzer reads only the context id, the server, and the
tool name**:

```json
{"contexts": [
  {"id": "assistant",
   "provenance": "fetched tools/list from our hosted wiki by hand, 2026-07-13",
   "tools": [{"server": "wiki", "tool": {"name": "publish_page"}}]}
]}
```

Descriptions and `inputSchema`s are recorded verbatim when a capture produces them —
for the human who will audit the artifact — and are read by no detector. (They
*couldn't* be: tool schemas cannot constrain reachability, which is [why the middle
tier is co-exposure and not type-compatibility](DECISIONS.md).) A test holds this
honest: an inventory carrying only names yields byte-identical findings to our full
captured one. The one thing that must never happen is recording a tool **no server
listed**.

## Why this shape

Two documented, primary-source-verified incidents (details, sources and
verification dates in [`INCIDENTS.md`](INCIDENTS.md)):

- **EchoLeak** (CVE-2025-32711, Aim Labs): a single crafted email carried hidden
  instructions into Microsoft 365 Copilot, which then pulled sensitive context and
  sent it outward — zero-click.
- **GitHub MCP** (Invariant Labs): a malicious issue in a public repo steered an
  agent into pulling private repository data and publishing it in a pull request
  the author could read. Invariant call it architectural, not a bug in the server.

Neither is a coding error you can grep for. Both are the same **topology**: private
data + untrusted content + an outbound channel, in reach of one agent
([Simon Willison's "lethal trifecta"](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)).
That is a property of how a stack is *wired*, and it is checkable before anything
happens.

## What it does not do

This is the part most tools bury. It is load-bearing here, and it is enforced by
tests, not by good intentions.

- **It is not an enforcement layer.** It is not a firewall, not a runtime, not a
  gateway. It never sits in the request path, never executes a tool, never opens a
  network connection. It reads two files and writes a report. **That absolute is
  about `trifecta-lens` itself** — and it is structural, not a promise: CI fails the
  build if a network import appears anywhere in the analyzer. The optional
  `trifecta-capture` is a *separate package* precisely so the claim can stay absolute.
  It does launch your MCP servers, exactly as your host does, and asks each one
  `tools/list` — that is the one thing in this project that speaks to anything. It
  **calls no tool**, it runs once, offline, on your machine, and the analyzer never
  needs it: hand `trifecta-lens` an inventory from any source and it will never know
  the difference.
- **It observes flow, never causation.** A realized finding says *"tainted data
  observed reaching `<sink>`"*. It never says untrusted content **made** the agent
  do anything — that would require establishing intent from a trace, and a trace
  cannot carry it. Where the path rests only on ordering, the finding says
  `basis: temporal` and spells out what that does not establish.
- **Verbatim taint only.** v1 matches a value that reaches the sink unchanged
  (after trimming/casefolding/whitespace collapse). A value that was base64'd,
  split across calls, summarized or paraphrased **is not detected**. EchoLeak's own
  exfiltration rode a rendered channel that this would miss — we cite it anyway,
  with that stated.
- **Four honest gaps**, stated because a reader would otherwise reasonably assume
  otherwise:
  1. **RAG / LLM-message ingest is not built.** Retrieved documents
     (`retrieval.documents.*`) and LLM message payloads are not read as untrusted
     sources yet. No captured trace we hold carries them, and inventing an ingest
     path for a format we have never seen is how tools acquire silent bugs. Its
     sibling, which you need to know *before* you point us at a trace: we read
     **one** semantic convention, **OpenInference** — in either envelope (flat JSONL
     or real OTLP/JSON, auto-detected). A trace instrumented with **OTel GenAI**
     (`gen_ai.*` keys) is a *different* convention and **does not load**; it is
     refused with an error that says so, rather than half-read. And only **tool
     spans** carry roles: an LLM or agent span contributes ordering, never a leg.
  2. **The realized anchor is a direct instruction, not a prompt injection.** In
     the captured run, the agent was *asked outright* to read the value and send
     it. Nobody injected anything. It is a real recording of a real flow, and it is
     not an in-the-wild compromise.
  3. **Action-hijack is catalogued but not accepted.** `sink:impact` entries
     (shell, filesystem writes, merges) ship in the catalog and no v1 family
     accepts on them — they change no finding today. That family is fast-follow.
  4. **The realized trifecta has never been captured here.** The only artifact that
     exercises it is [`fixtures/worked_example.jsonl`](fixtures/worked_example.jsonl),
     which is **hand-authored** and says so in its provenance. We therefore **do not
     claim** to have observed a lethal trifecta in the wild, and you will not find
     that claim anywhere in this repo.

Every fixture in [`fixtures/`](fixtures/) is disclosed as **captured** or
**hand-authored** in [`FIXTURES.md`](FIXTURES.md) and a per-file provenance note.
Running a real capture is encouraged; authoring one and calling it captured is the
one thing this project will never do.

## Noise

"Low false positives" is a measurement here, not an adjective: **8 benign traces,
0 realized findings**, at the shipped configuration. Each benign fixture is silent
for a *different, named* reason — a redacted secret, a value reaching a tool that
carries no sink role, a lookalike token at the sink, a source→sink flow with no
sensitive leg — so the silence comes from the guard being exercised, not from the
labeling simply missing everything. The detection bounds ride on every finding and
every report as `detected_under`, including the empty ones: "no finding" is only
auditable if you know what was being looked for.

## Findings are a contract

Findings are **NDJSON** — one finding per line, keys sorted, written as they are
found. Every line carries its `schema_version`; the shape is frozen in
[`schema/findings.schema.json`](schema/findings.schema.json), and a test fails the
build if a field is added, removed or renamed without a version bump.

<details>
<summary>The realized finding from the run above, verbatim</summary>

```json
{
  "agents": [
    "48c39e14c7b99b21"
  ],
  "crosses_agents": false,
  "detected_under": {
    "match": "containment",
    "min_value_chars": 8,
    "normalization": [
      "trim",
      "casefold",
      "collapse-whitespace"
    ]
  },
  "family": "sensitive_to_exfil_sink",
  "legs": [
    {
      "agent": "48c39e14c7b99b21",
      "catalog_entry": "mcp.filesystem.content_read",
      "event": "485697cce52b7fa2",
      "note": "reads file contents from the local filesystem (MCP filesystem server)",
      "role": "sensitive_data",
      "tool": "filesystem__read_text_file"
    },
    {
      "agent": "48c39e14c7b99b21",
      "catalog_entry": "mcp.notify.send",
      "event": "4b85b6426897725d",
      "note": "sends a message body to an outbound notification endpoint",
      "role": "sink:exfil",
      "tool": "notify__send"
    }
  ],
  "legs_not_observed": [
    "untrusted_source"
  ],
  "legs_observed": [
    "sensitive_data",
    "sink:exfil"
  ],
  "masked_values": [
    "sk-demo-...MASKED"
  ],
  "note": "the untrusted_source leg was not observed in this trace, so this is not a trifecta finding: it is the lesser result that sensitive data was observed reaching an outbound sink. It does not claim untrusted content was present.",
  "path": [
    "485697cce52b7fa2",
    "4b85b6426897725d"
  ],
  "path_basis": "temporal",
  "path_edges": [
    {
      "basis": "temporal",
      "from": "485697cce52b7fa2",
      "to": "4b85b6426897725d"
    }
  ],
  "schema_version": "1.1",
  "scope": "verbatim taint only (SPEC.md \u00a76): a value that was encoded, split, summarized or paraphrased between source and sink does not match, and so would not appear here. Absence of a finding is not evidence of absence of a flow.",
  "sink": {
    "event": "4b85b6426897725d",
    "tool": "notify__send"
  },
  "summary": "tainted data observed reaching notify__send",
  "tier": "realized"
}
```

Note what a realized finding carries that a reachable one **cannot**: a path, a
path basis, a masked value. A capability finding has nowhere to put those fields —
it observed nothing. Tier honesty is a property of the types, not of the wording.

</details>

## Your stack, without touching our code

The engine does not know what a "vault" is and never will. Detection is one fixed
automaton over **role-labeled** tools, and the labeling is a data file. Covering a
server we have never heard of is an entry:

```yaml
version: 1
entries:
  - id: acme.crm.rows
    match: {tool: "crm__read_customer_rows"}
    role: sensitive_data
    note: "returns customer PII rows from our CRM"
```

`trifecta-lens --catalog my-stack.yaml ...` and the **unmodified** engine finds the
trifecta on your stack. Every finding cites the catalog entry id that assigned each
role, so when you disagree with a label you know exactly what to edit. CI fails the
build if detection code ever branches on a tool name — coverage lives in data, and
that is structural. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Status

v0.1 — the analyzer, three tiers, a real MCP capture, a frozen findings schema.
Out of scope for v1 and named as such: transformed taint, cross-agent multi-hop,
memory poisoning. Next: the action-hijack family, SARIF, a GitHub Action.

`SPEC.md` (behavior) · `DESIGN.md` (the automaton) · `DECISIONS.md` (why it is
shaped this way) · `INCIDENTS.md` (the citations) · MIT licensed.
