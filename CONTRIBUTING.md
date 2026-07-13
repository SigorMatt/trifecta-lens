# Contributing

The contribution this project wants most is **a catalog entry**.

Detection is one fixed automaton over role-labeled tools. It does not know what a
"vault" or a "Jira issue" is, and it never will. Everything it *can* find comes from
the labeling — and the labeling is a data file. So covering a new server, a new
sink, or a whole new stack is an edit to
[`trifecta_lens/catalogs/exfil_v1.yaml`](trifecta_lens/catalogs/exfil_v1.yaml), not
to any Python.

That is not a stylistic preference. It is `CLAUDE.md` invariant 2, and CI enforces
it: a gate fails the build if detection code branches on a tool name or looks one up
in a table. If your change needs an `if tool == "..."` in the engine, the change is
wrong — the coverage belongs in the catalog.

> Every YAML example below is parsed by the real catalog parser and run through the
> real labeling function in [`tests/test_contributing.py`](tests/test_contributing.py).
> If an example here stops working, CI goes red. Copy-paste is meant to work.

## Cover your own stack

Say your agent talks to two servers this project has never heard of: a CRM that reads
customer rows, and an internal wiki it can publish pages to. Under the shipped catalog
they are **invisible** — unlabeled tools get no roles, and the machine stays silent
about them, correctly.

Write an overlay:

```yaml
# my-stack.yaml — the whole contribution: data.
version: 1
entries:
  - id: acme.crm.rows                          # stable id — findings cite it
    match: {tool: "crm__read_customer_rows"}   # anchored regex over the tool name
    role: sensitive_data                       # untrusted_source | sensitive_data | sink
    note: "returns customer PII rows from our CRM"   # the rationale, shown in output

  - id: acme.wiki.publish
    match: {tool: "wiki__publish_page"}
    role: sink
    subtype: exfil                             # exfil | impact — sinks only
    note: "publishes a page to the company-wide wiki, readable by everyone"
```

Point the analyzer at it:

```
trifecta-lens --trace my-trace.jsonl --inventory my-inventory.json --catalog my-stack.yaml
```

The **unmodified** engine now detects the full trifecta on your stack. Nothing was
recompiled, no branch was added, and no one had to teach the machine what a CRM is.
Your entries are consulted *before* the defaults, so where you and we disagree about a
tool, you win.

Under MCP a tool's identity is **server-qualified** — `<server>__<tool>`, e.g.
`filesystem__read_text_file` — because two servers may each expose a `read`. That is
the name the trace carries and the name your `match.tool` regex should expect.

You do not have to touch this repo at all: ship your stack's labels with your stack.
Send them upstream only if they generalize.

## Disagreeing with a label

Every finding names the entry that assigned each role:

```
    sensitive_data    filesystem__read_text_file  reads file contents from the local filesystem
                      [catalog: mcp.filesystem.content_read]
```

That id is the thing to change. Override it in an overlay, or send a PR against the
default catalog if we got it wrong for everyone. You never have to read our source to
find out why we said what we said — that is the whole reason the citation is in the
output rather than in a design doc.

## What makes a good entry

**A wrong label is worse than a missing one.** A missing label loses a finding. A
wrong label manufactures a *confident* finding about a role nobody assigned — and the
only thing this tool sells is that it does not say what it cannot support.

So:

- **Match on semantics that are clear from the name.** `read_text_file` reads
  contents; `list_directory` returns names. The first is `sensitive_data`; the second
  is nothing, and labeling it would make every `ls` a leg of an exfil finding.
- **Prefer narrow patterns.** `(.*__)?read_secret` is good. `.*__get_.*` is not.
- **A sink is anywhere data leaves the boundary** — not just HTTP. Posting a comment
  on a public issue publishes the payload as surely as a POST does; it just does not
  look like one.
- **Write the `note` for the person who will disagree with you.** It is shown in the
  finding, and it is the whole basis on which they will decide you were wrong. It is
  also report text, so it observes the same discipline the report does: it describes
  what a tool *does*, never what someone did with it.
- **If the naming is genuinely ambiguous, don't guess.** Say so in a comment and
  leave it out. There is an example in the catalog (RAG reads) — the pattern would
  have to be `search|query|retrieve`, which collides with harmless tools, so it waits
  for a real trace instead of shipping a guess.

## Sending an entry upstream

A catalog PR is small. It is also the one kind of change that can quietly make the
tool *lie*, so it carries its own evidence:

- [ ] The entry, in `trifecta_lens/catalogs/exfil_v1.yaml`.
- [ ] **A positive fixture** — a trace (or inventory) in which your entry produces the
      finding you expect, with the expected verdict pinned in a test.
- [ ] **A benign fixture** — one where the tool is present and the finding must *not*
      fire. This is the more valuable of the two: it is what proves the entry is not
      simply louder than the truth.
- [ ] A provenance note in [`fixtures/FIXTURES_PROVENANCE.md`](fixtures/FIXTURES_PROVENANCE.md)
      saying whether the fixture was **captured** or **hand-authored**. Both are
      welcome. Only one of them may be called a recording.
- [ ] `make check` green. If the change is *meant* to move the findings output, run
      `make golden` and commit the regenerated bytes, so the change lands as a
      reviewable diff instead of silent drift.

## Changing anything else

- **`SPEC.md` leads, the code follows.** If a change isn't described there, update it
  in the same PR.
- **Fixtures are the executable spec.** Every detector behavior is anchored by a
  trace/inventory fixture plus its expected verdict. Write the fixture first.
- **The findings NDJSON is a public contract.** Its shape is frozen and versioned in
  [`schema/findings.schema.json`](schema/findings.schema.json); adding, removing or
  renaming a field without the version bump fails CI. Consumers parse those lines.
- **The automaton's structure is closed.** States, transitions and acceptance
  (`DESIGN.md` §4) are the honesty contract. Changing them is a spec decision, not an
  implementation one — open an issue first.

## The line that never moves: never manufacture a result

This project sells exactly one thing — that **it does not say what it cannot support**.
Every tier, every disclosure, every refusal exists to protect that. A contribution that
fabricates a result destroys it, and no amount of coverage, breadth or polish buys it
back. This is the one rule with no engineering trade-off behind it.

**It applies to all four surfaces, not just the obvious one.** Faking a fixture is easy
to spot; the other three are where it actually happens.

**1. Artifacts.** Never fabricate a **captured** artifact. Traces and tool inventories in
`fixtures/` that claim to be *recordings* must be recordings. Hand-authored fixtures are
welcome and several exist — they say so, in a `FIXTURES_PROVENANCE.md` note, every time.
The line this project holds is **captured vs. fabricated, never automated vs. manual**: a
`tools/list` response you fetched from a real running server by hand *is* a capture (D11).
Authoring one and calling it captured is not.

**2. Tests.** Never manufacture a **green build**. A test exists to be capable of failing;
anything that removes that capability while leaving the green tick is a lie told to every
future reader. Concretely, none of the following, ever:

- `skip` / `xfail` / a commented-out assertion used to get past a failure you did not fix;
- weakening an assertion until it passes (`>= 0`, `assert True`, dropping the arm that
  broke) instead of fixing the code or changing the spec;
- pasting the **current** output into the expected value when the current output is what
  is in question — a golden regenerated to bless a regression is not a golden;
- a benign fixture that is silent because it never had the legs. Its silence must be
  **load-bearing** — see `tests/test_benign_corpus.py`, where every silence names the
  guard it exercises and asserts that the legs which *would* fire are present.

If a test cannot pass, that is a **finding**. Say so in the PR. A red test with an honest
explanation is worth more here than a green one that means nothing.

**3. Documentation.** Never show output the tool did not produce. Every console block,
every findings line, every number in this repo is regenerated from a real run and compared
in CI (`tests/test_readme.py`, `tests/test_usage.py` — the manual is *executed*, not
proofread). Do not prettify a report, trim an inconvenient disclosure out of a pasted
block, or quote a coverage/benchmark figure you did not measure. If you cannot run it,
do not show it.

**4. Code.** Never make the detector **recognise its own test input**. No branch on a
tool name, a fixture name, a trace id or a span id to produce an expected verdict — CI
fails the build for per-tool branches in core (`tests/test_gates.py`), but the rule is
wider than the gate: any code path that behaves differently *because it is being tested*
is a forged result. Coverage lives in the catalog, acceptance lives in the fixed machine.
If a real input does not produce the finding you want, the honest options are a **catalog
entry** or a **spec change** — never a special case.

### And the other direction, which is the one we keep getting wrong

**Do not fake a limitation either.** Every defect this project has found in itself was a
**silence** or an **under-claim** — never a false statement — because the gates only ever
hunted false statements. `SPEC.md` §8 once denied cross-agent flow while the engine
detected it (D15). A tool that detects a thing and says it does not is as untrustworthy as
one that claims what it cannot do.

**Say what the code does. Both directions.** If your change makes the tool *more* capable
than the docs admit, the docs are now wrong and fixing them is part of your PR
(`tests/test_scope_claims.py` will fail the build if you forget).

### If you are stuck

Say so. Open an issue, or land the honest partial and put the rest in
[`DEBT.md`](DEBT.md) — that register exists precisely so that "not done" has somewhere to
live that is not a fabricated result. Deferring work is normal here and costs you nothing.
Pretending it is done costs the project the only thing it has.
