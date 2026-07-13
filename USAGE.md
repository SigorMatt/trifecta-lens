# USAGE.md — what to run, what to feed it, how to read what comes out

> Every command in this file is executed by `tests/test_usage.py`, and every line of
> output shown is compared against what the tool really printed. If this document drifts
> from the code, CI goes red. Copy-paste is meant to work.

`README.md` is the pitch. `SPEC.md` is the contract. **This is the manual.**

---

## 1. The one idea that makes the rest obvious

A trace tells you what your agent **did**. Nothing in a trace tells you what your agent
**could have done** — a tool it never called leaves no span behind.

But *"could, but didn't"* is the whole product. So the analyzer takes **two independent
inputs**, feeding different tiers:

| You give it | You get | Because |
|---|---|---|
| `--trace` only | **realized** | evidence of what happened |
| `--inventory` only | **reachable** + **posture** | capability — **no trace needed at all** |
| both | all three, and the **gap between them** | the finding |

**A tier with no input does not run — and says so.** It never reports a clean result it
did not check for.

Most people start with the inventory alone. Almost nobody has a captured trace of their
agent leaking something; almost everybody has a topology that could.

## 2. You do not need MCP

The analyzer reads exactly three things about each tool: **which agent context** can reach
it, an optional **server**, and its **name**. That is all detection consumes.

- **MCP stack?** `trifecta-capture` builds the inventory for you (§4).
- **No MCP** — LangChain, LlamaIndex, CrewAI, a hand-rolled loop? **Write the inventory by
  hand.** It is a documented file ([`schema/inventory.schema.json`](schema/inventory.schema.json)),
  and four tools is a dozen lines. Omit `server` entirely: your agent has none, its tools
  are identified by bare name, and that is exactly what its trace emits. See §7 scenario 4
  — it works end to end.

The engine has never heard of MCP. Only the *capture convenience* is MCP-shaped.

---

## 3. `trifecta-lens` — every flag

```
trifecta-lens --inventory <inventory.json> --trace <spans.jsonl>
              [--catalog user.yaml] [--findings out.ndjson] [--svg path.svg]
```

| Flag | What it is | If you omit it |
|---|---|---|
| `--trace` | A captured trace. **Flat JSONL** spans or a real **OTLP/JSON** document — the format is detected from the file, you don't declare it. | The **realized** tier does not run, and says `NOT RUN`. |
| `--inventory` | The captured tool inventory (§4). | **Posture and reachable** do not run, and say `NOT RUN`. |
| `--catalog` | Your overlay (YAML): teach it *your* tools. Consulted **before** the defaults, so where you disagree with us, you win. | Only the shipped catalog is used — and it has never heard of your CRM. Read the **COVERAGE** section (§6). |
| `--findings` | Write findings **NDJSON** here: one finding per line, keys sorted, written as found. A frozen public contract ([`schema/findings.schema.json`](schema/findings.schema.json)). | Findings appear only in the human report. |
| `--svg` | Write the path diagram. | No SVG. (It is written only when there *is* a realized finding.) |

It reads files and writes files. It never opens a network connection, never executes a
tool, never touches your agent.

## 4. Producing the inventory — three routes, all first-class

The inventory is a JSON file listing, **per agent context**, the tools that context can
actually reach. One context per agent: your orchestrator and each sub-agent are separate
contexts, and that is precisely what lets **reachable** say *"the triage agent could not
have done this, but the assistant could."*

### (a) Local MCP servers — `trifecta-capture --config`

```
trifecta-capture --config .mcp.json --out inventory.json \
    --context assistant=github,fetch,vault \
    --context triage=github \
    --note triage="our issue-triage subagent; deliberately has no outbound tool"
```

It launches each server exactly as your host does, asks it `tools/list`, and writes the
file. **It calls no tool.**

| Flag | What it is |
|---|---|
| `--config` | The config your MCP host already loads (`.mcp.json`, `claude_desktop_config.json`). It holds only launch config — **the tool list is not in it**, which is why this step exists. |
| `--context ID=SERVER,SERVER` | Which agent sees which servers. **Declare your real contexts.** With none declared the whole config is one context — honest, but then reachable can only restate posture, and it says so. |
| `--note ID=TEXT` | What that context *is*, in **your** words. Carried into the report verbatim. Without one, the artifact records that no note was given — it will not invent a description. |
| `--delegates ID=ID,ID` | Which contexts this one can **hand data to**. Turns on the `reachable_cross_agent` tier (§7 scenario 5). It cannot be inferred — a tool list says what an agent can *reach*, never who it *talks to* — so without it that tier does not run. |
| `--from-tools-list SERVER=FILE` | See (b). |
| `--out` | Where to write it (default `inventory.json`). |

### (b) Remote or hosted MCP servers — `--from-tools-list`

`trifecta-capture` launches **stdio** servers. A hosted server has no command to launch. So
fetch its `tools/list` response however your stack allows, and hand over the JSON:

```
trifecta-capture --config .mcp.json --from-tools-list wiki=wiki-tools.json \
    --out inventory.json --context assistant=vault,wiki
```

Servers you *can* launch stay in `--config`; the two mix in one inventory. **A tool list
obtained from a real running server is a capture, whoever fetched it.** The provenance note
records which servers we launched and which you supplied, and it does not claim we launched
yours.

### (c) No MCP — write it

```json
{"contexts": [
  {"id": "researcher",
   "provenance": "transcribed by hand from our agent's tool registry (agent.py), 2026-07-13. Not an MCP capture.",
   "tools": [
     {"tool": {"name": "fetch"}},
     {"tool": {"name": "crm_lookup"}},
     {"tool": {"name": "send_email"}},
     {"tool": {"name": "list_files"}}
   ]}
]}
```

**No `server` key.** Your agent has no servers, so a tool's identity is its bare name — the
same name your trace emits. (Under MCP, identity is `server__tool`, because two servers may
each expose a `read`. Inventing a fake server for a flat agent would invent an identity your
trace does not carry, and the two files would no longer describe one system — the analyzer
checks this and will tell you. See §6, **JOIN**.)

Write the `provenance` note yourself, and say what it really is. Transcribing your own tool
registry is honest. Calling it a capture is not.

## 5. Producing the trace

Spans in the **OpenInference** semantic convention, in either envelope:

- **flat JSONL** — one span per line, attributes already flat;
- **OTLP/JSON** — real exporter output (`resourceSpans[]…`).

Six attributes are read: `openinference.span.kind` (**required**), `tool.name`,
`input.value` / `input.mime_type`, `output.value` / `output.mime_type`.

**What does not work, stated plainly:**

- **OTel GenAI (`gen_ai.*`) traces do not load.** It is a *different* semantic convention;
  the tool refuses them with an error saying so rather than half-reading them.
- **Only tool spans carry roles.** An LLM or agent span contributes ordering, never a leg.
- **RAG document content and LLM message payloads are not ingested.**
- Realized needs **payload-level** spans. Without `input.value` / `output.value` it reports
  `UNAVAILABLE` — not "clean".

---

## 6. Reading the output

The report prints, in this order:

**JOIN** *(only when something is wrong)* — do your two files describe **one system**? A run
can only call a tool its agent is exposed to, so the trace's tool names must appear in the
inventory. When they don't, the tiers are **not comparable** — a realized finding could
outrank a reachable one, which would be nonsense — so the tool says so and shows you both
name lists. It **discloses; it does not repair.** It will not guess that `fetch` and
`local__fetch` are the same tool.

**COVERAGE** — how many of your tools the catalog had an opinion about, and it **names every
one it didn't**. This bounds everything below it: a tool with no role is invisible to every
tier. Crucially, an unmatched tool is **not a safe tool** — a tool we have never heard of and
a tool we *deliberately* leave unlabeled (`list_files` returns names, not content) look
identical from here, and the report says exactly that rather than guessing. If it matched
**nothing**, a silent tier is not a clean result; it is a starved one, and it warns you.

**The three tiers**, strongest first:

| Badge | Claim | Weight |
|---|---|---|
| `[REALIZED]` | a value was **observed** reaching a sink, verbatim, in the trace | evidence |
| `[REACHABLE]` | all legs are exposed to **one** agent context — a single run *could* wire them. **None was observed doing so.** | capability |
| `[REACHABLE_CROSS_AGENT]` | no single agent could wire it, but agents you **declared** can hand data to one another pool the legs between them | weakest capability claim: it rests on **your** declaration, which nothing corroborates |
| `[POSTURE]` | the legs exist **somewhere** in the stack | weakest — overlaps ordinary static scanners |

`realized ⊆ reachable ⊆ reachable-across-a-chain ⊆ posture`, structurally. Each tier hands
the same automaton a wider bag of tools.

**Inside a finding:**

- **`exfil_trifecta`** — all three legs. **`sensitive_to_exfil_sink`** — the *lesser* two-leg
  result: sensitive data reached an outbound sink, but **no untrusted source was observed**.
  It is never headlined as a trifecta, and it names the leg it is missing.
- **`basis`** — `temporal` means the steps were observed **in this order**, and that is *not*
  a claim that one fed the other. `causal` means the trace's own parent chain links them.
  The report spells this out every time; an unlabelled arrow is read as causation, and we
  will not ship one.
- **`[catalog: <id>]`** — the entry that assigned each role. Disagree with a label? That id is
  the thing to change.
- **`Detected under:`** — the detection bounds, on every report *including empty ones*. "No
  finding" is only auditable if you know what was being looked for.

The language never escalates: *"tainted data observed reaching `<sink>`"*. It observes flow.
It does not assert that the untrusted content **drove** the action — establishing that would
mean reading intent out of a trace, and a trace does not carry intent.

---

## 7. Four scenarios

### Scenario 1 — "What could my agent do?" (no trace, 60 seconds)

*You run an MCP stack. Nothing has gone wrong. You want to know what is wired.*

```
trifecta-lens --inventory fixtures/inventory.json
```

```text
--- REACHABLE ---------------------------------------------------------

reachable is strictly tighter than posture on this stack: 1 of 2 agent contexts cannot wire this family (triage). Posture cannot see that distinction — it only asks whether the legs exist somewhere.

[REACHABLE]  exfil_trifecta  (all three legs)
  all legs of exfil_trifecta are exposed to agent context 'assistant'; a single run could wire them to notify__send
...
```

Realized says `NOT RUN`, explicitly. **That is the answer to "what could happen", and it
needed no trace at all.** Note the `triage` context *cannot* wire it — it has no outbound
leg. Posture is structurally unable to see that distinction, which is why reachable is a
tier and not a restatement.

### Scenario 2 — "Did it ever actually happen?" (add the trace)

*Same stack. Now you have an OTLP trace of a real run.*

```
trifecta-lens --trace fixtures/demo_mcp_trace.otlp.json --inventory fixtures/inventory.json \
    --findings findings.ndjson --svg path.svg
```

```text
[REALIZED]  sensitive_to_exfil_sink  (two-leg — NOT the trifecta)
  tainted data observed reaching notify__send
...
[REACHABLE]  exfil_trifecta  (all three legs)
```

**Read the two together and you have the product.** The run that *was* captured moved a
secret to an outbound sink — but no untrusted content was in that path, so it is the
**lesser two-leg family**, and the missing leg is named. Meanwhile the **full trifecta is
reachable** in that same context. *Could, but didn't.*

### Scenario 3 — "Our MCP server is hosted, not local"

*Your vault runs locally; your wiki is a hosted MCP server with no command to launch.*

```
trifecta-capture --config .mcp.json --from-tools-list wiki=wiki-tools.json \
    --out inventory.json --context assistant=vault,wiki
```

You obtained `wiki-tools.json` by asking the running server for `tools/list` — by curl, by a
client script, by whatever your stack allows. That is a capture. The two sources mix in one
inventory, and the provenance note says which was which.

### Scenario 4 — "We don't use MCP at all"

*A LangChain agent. Its tools are Python functions: `fetch`, `crm_lookup`, `send_email`,
`list_files`. You have an OpenInference trace and you wrote the inventory by hand (§4c).*

**First run — the shipped catalog:**

```
trifecta-lens --trace fixtures/usage/nonmcp_trace.jsonl --inventory fixtures/usage/nonmcp_inventory.json
```

```text
The catalog matched 2 of 4 tools in this inventory.

  matched no entry:
    crm_lookup
    list_files
...
no realized findings on this trace.
```

**Nothing.** And here is why that is *useful* rather than reassuring: the COVERAGE section
tells you the catalog has never heard of `crm_lookup`. Of course it hasn't — that is *your*
tool, and no default catalog could know what it returns. The exfil family needs a
sensitive-data leg, and without a label on `crm_lookup` there isn't one. **The silence was
our labeling, not your safety.**

**Teach it — one entry, in a data file:**

```yaml
version: 1
entries:
  - id: acme.crm.lookup
    match: {tool: "crm_lookup"}
    role: sensitive_data
    note: "returns a customer record from our CRM: name, plan, partial card, home address"
```

**Second run:**

```
trifecta-lens --trace fixtures/usage/nonmcp_trace.jsonl --inventory fixtures/usage/nonmcp_inventory.json --catalog fixtures/usage/nonmcp_catalog.yaml
```

```text
[REALIZED]  exfil_trifecta  (all three legs)
  tainted data observed reaching send_email

  path   a1 (fetch, untrusted_source) -> a2 (crm_lookup, sensitive_data) -> a3 (send_email, sink:exfil)
  basis  temporal — the steps were observed in this ORDERING; the trace carries no parent-child link between them, so this does not establish that one fed the other
  value  Alice Cu...MASKED
```

A web page came in, a customer record was read, and that record went out in an email body —
**verbatim**. The engine was not recompiled and still does not know what a CRM is. You added
a line of YAML.

`list_files` remains unlabeled, deliberately: it returns *names*, not content. Labeling it
would make every directory listing a leg of an exfil finding. **A wrong label is worse than
a missing one.**

---

### Scenario 5 — "One agent reads, another sends" (multi-agent)

*An orchestrator with two sub-agents. `reader` can browse and read secrets but has **no
outbound tool**. `sender` can email and nothing else. Neither can leak on its own — and
that is exactly why this is the case people miss.*

Declare the handoff — in the inventory (`"delegates_to": ["sender"]`) or at capture time:

```
trifecta-capture --config .mcp.json --out inventory.json \
    --context reader=web,vault --context sender=mail \
    --delegates reader=sender
```

```
trifecta-lens --trace fixtures/cross_agent_handoff.jsonl --inventory fixtures/usage/delegating_inventory.json
```

```text
--- REACHABLE ---------------------------------------------------------

no findings at this tier: the captured inventory does not carry all the legs of any family we detect.


--- REACHABLE ACROSS A DECLARED CHAIN ---------------------------------

[REACHABLE_CROSS_AGENT]  exfil_trifecta  (all three legs)
  no single agent could wire exfil_trifecta, but the DECLARED delegation chain 'reader -> sender' pools legs that reach send_email
...
```

**Reachable is silent, and correctly so** — it asks whether *one* agent holds every leg, and
here neither does. That silence is not safety. `reachable_cross_agent` is the tier that can
see it: it pools the tools of agents you told us can pass data between them.

**It is the weakest claim the tool makes, and it says so.** It rests on **your** declaration
— that these agents really can hand data to one another — which no captured artifact
corroborates. If the declared handoff is wrong, the finding is wrong. It never borrows
reachable's language, because it is not reachable: reachable did not accept here.

Without `delegates_to`, this tier simply **does not run** — which is honest. We will not
invent a handoff: an inventory records what each agent can *reach*, never who it *talks to*.

And in this run the realized tier fires too, naming the agents the flow crossed. Cross-agent
flow **within one trace** has always been detected (`SPEC.md` §8); cross-*session* — a value
stored in one run and read in the next — is a different problem and is not.

## 8. Where to go next

- Disagree with a label, or cover a server we've never heard of →
  [`CONTRIBUTING.md`](CONTRIBUTING.md). It is a data file, and that is the whole point.
- What the tool does **not** do → [`README.md`](README.md), the limits section. Read it.
- Why it is shaped this way → [`DECISIONS.md`](DECISIONS.md).
- Exact behavior → [`SPEC.md`](SPEC.md).
