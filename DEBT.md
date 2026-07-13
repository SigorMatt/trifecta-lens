# DEBT.md — what we owe, and what we have chosen not to do

**Why this file exists.** `OPEN_QUESTIONS.md` used to be the register of deferred
decisions, and it did a real job: it forced a question into the *planning* conversation
instead of letting it get settled silently by whoever wrote the code next. On 2026-07-13
its last item was resolved (§5 → D12) and it became history — and the **same session**
generated a pile of new deferred items and scattered them through `DECISIONS.md` prose as
*"deliberately not done"* and *"binding on Phase 4"*, findable only by someone who already
knew to look. Two more were written down nowhere at all.

A project whose whole discipline is *"say what you cannot do"* had deleted its only record
of what it had not done. That is the same defect as every other one that session turned up
— a **silence** — so it gets the same treatment: written down, in one place, where the
next person will meet it.

**The rule.** If work is deferred, it lands here **in the same PR that defers it**. An
item leaves this file only by being done, or by a decision in `DECISIONS.md` that says it
never will be.

---

## Blocked on a real capture (D9's rule: no front-end for a format we have never seen)

These are **not** "coming soon". They are unsupported, they say so in the output, and they
land only when a real artifact exists to build them against. Building against an imagined
format is how the "manifest contains tools" error (F1) happened.

- **OTel GenAI (`gen_ai.*`) traces.** A second *semantic convention*, and a real one — we
  read only OpenInference. A GenAI trace is **refused**, with an error that says so rather
  than half-reading it (`SPEC.md` §7.3, D12). Needs: one real GenAI-instrumented capture.
- **RAG ingest** (`retrieval.documents.*`) **and LLM message payloads.** No captured trace
  we hold carries these keys. Until then, only **tool spans carry roles** — an LLM or agent
  span contributes ordering, never a leg, and that is the single largest bound on what the
  realized tier can see (`SPEC.md` §7.3).
- **A realized lethal trifecta in the wild.** Never captured. The realized *trifecta* is
  exercised only by `fixtures/worked_example.jsonl`, which is **hand-authored** and says so
  every time it is named. This is D10, and it is why the README claims the tier *gap* and
  not a catch.

## Chosen, not forgotten — the ones with a decision behind them

- **Catalog breadth.** 16 entries. A stranger running Postgres, Slack, Notion, Linear or
  Snowflake gets **silence** — and since D13 the report *says* so, naming every tool it had
  no opinion about. Disclosure was the honesty fix; **breadth is the usefulness fix and is
  still owed.** Each entry needs a positive *and* a benign fixture (`CONTRIBUTING.md`), so
  this is real work, not a list. It is the highest-leverage thing available: the engine
  needs no change, and it converts silence into findings for every stack it covers.
- **Action-hijack (`sink:impact`).** The catalog already ships three impact entries
  (shell/exec, destructive writes, PR merge) and **no v1 family accepts on them** — they are
  inert today. Phase 4. Adding the family is adding a row to `FAMILIES`; the automaton does
  not move.
- **Remote-MCP transports in `trifecta-capture`.** Rejected in D11 on cost, *not* on
  principle: `trifecta_capture` sits outside core, so network there breaks no invariant. The
  escape hatch (`--from-tools-list`) covers every transport at a fraction of the surface. **If
  users tell you the manual step is what stops them, this is revisitable without touching a
  single rule.**

## Binding constraints on work not yet started

- **Phase 4 / SARIF: coverage must ride into it** (D13). A CI job consuming an empty
  `findings.ndjson` would otherwise report "clean" on a stack the tool never recognised — the
  D13 bug with a worse blast radius and **no human reading a report to catch it**. Do not ship
  a CI surface that can be silently starved.
- **Action-hijack realized is a halt-and-ask**, not a default. It is blocked on "no defensible
  causation signal", and `path_basis` (D5) is the *beginning* of a vocabulary for one — not
  yet an answer.

## Permanently out (do not re-litigate)

- **Outbound delivery of findings from core** — no webhooks, no emitters, ever
  (`DESIGN.md` §7). Findings go to stdout/files; the `curl` lives in the user's shell.
- **Transformed taint** (base64, splitting, paraphrase), **memory-poisoning**, and anything
  crossing **sessions** (a value stored in one run, read in the next). `SPEC.md` §8.
  *Cross-agent flow **within one trace** is detected* (D15) — do not confuse the two.

## Process debt

- **Release PRs #2 / #3.** PyPI is deferred indefinitely by the operator. The PRs keep, but
  **#3's rebase has grown**: it was staged against the 3.1 README, and `main` has since moved
  (new README sections; findings schema `1.0 → 1.2`). Its substance is unchanged and still
  correct — it flips the README install line *and* the test that guards it, in one commit.
- **`demo/capture_inventory.py`** is superseded by `trifecta-capture` but is still correctly
  cited by the fixtures' provenance — it produced the committed capture. It is history, not
  dead code. Leave it.

---

*Related: `DECISIONS.md` (why things are the way they are), `ROADMAP.md` (what comes next),
`OPEN_QUESTIONS.md` (how the Phase-1/2 questions were raised, and how they were closed).*
