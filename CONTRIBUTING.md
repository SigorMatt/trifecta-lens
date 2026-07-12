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

## The line that never moves

**Never fabricate a captured artifact.** Traces and tool inventories in `fixtures/`
are *recordings*. Running a real capture is encouraged; authoring one and calling it
captured destroys the only thing this project has. Hand-authored fixtures are welcome
and several exist — they say so, in a provenance note, every time.
