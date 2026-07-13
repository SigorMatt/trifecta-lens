# OPEN_QUESTIONS.md — deferred spec/design decisions

> **STATUS: ALL RESOLVED (§§1–5). This file is now history.**
>
> §§1–4 were resolved in the Phase 2 planning conversation (2026-07-12); the
> decisions and their rationale live in **`DECISIONS.md`**: §1 → **D3**
> (containment), §2 → **D4** (fixed + disclosed), §3 → **D5** (`path_basis`
> required), §4 → **D6** (module-scoped gate). Implementation: `TASKS.md`
> **2.1–2.3**.
>
> **§5 (multi-format input) → D12** (2026-07-13). Its deferral condition —
> *"we need at least one real non-demo trace/format in hand before fixing the
> seam's shape"* — was satisfied by Checkpoint D, and the OTLP front-end
> (`TASKS.md` 2.7) then **proved** the seam: a whole second envelope, zero engine
> change. What §5 still owed was the rule written down, and D12 writes it: **adding
> a format is a new Stage-1 front-end, never an engine branch.**
>
> D12 also corrects an error this section did not foresee. §5 speaks of "formats"
> as one axis; there are **two**, and conflating them put a false claim in
> `SPEC.md`. An **envelope** is how spans are packaged (flat JSONL, OTLP/JSON); a
> **semantic convention** is what the keys mean (OpenInference, OTel GenAI). We
> ship **two envelopes and one convention** — and the spec had been claiming OTel
> GenAI support that the loader refuses on span one. See `SPEC.md` §7.3.
>
> This file is kept as the record of how the questions were *raised* — what the
> tension was and why each was deferred rather than guessed. Read it for the
> reasoning; read `DECISIONS.md` for the answers.

Raised at **Checkpoint C** (Phase 1 exit, tasks 1.3–1.9). Each item is a place
where the committed specs disagree with each other, or where the Phase-1 slice
made a choice that the specs do not yet sanction. None of them changes a
Phase-1 result — that is precisely why they were deferred rather than guessed.

**These must be resolved deliberately in the Phase 2 planning chat, not
silently in code.** Deciding one by writing an implementation is exactly the
failure mode this file exists to prevent: the specs are the source of truth
(`CLAUDE.md`, spec-first), and a code change that quietly picks a side leaves
the contradiction in the documents for the next reader to trip over.

For each: **(a)** the tension, **(b)** where it surfaced, **(c)** why it was
deferred, **(d)** what Phase 2 must decide.

---

## 1. "Exact" vs "substring" — three passages, three wordings

**(a) The tension.** Three committed passages describe the taint match
differently:

| Where | Says |
|---|---|
| `SPEC.md` §6 | "Match = **exact** after light normalization … Nothing more." |
| `DESIGN.md` §8 | "plain normalized **substring** match for taint at v1" |
| `SPEC.md` §5 (realized, step 3) | a tagged value **"appears in"** a sink span's `inputs` |

These are not the same rule. Exact-equality asks whether the value *is* a
payload field; containment asks whether the value *occurs inside* one.

**(b) Where it surfaced.** `trifecta_lens/taint.py`, `value_in_payload()`.
Phase 1 implemented **containment of the untransformed value**: "verbatim"
constrains transformation *of the value* (no base64, no splitting, no
paraphrase — `SPEC.md` §6's actual subject), not the surrounding request body.
A secret pasted into a larger JSON body has still reached the sink verbatim.

**(c) Why deferred.** On every committed fixture the two readings are
**indistinguishable** — the anchor's `s4` body *is* exactly the secret, so
equality and containment both fire, and both stay silent on `s2` and on the
benign fixtures. Nothing in Phase 1 turns on the choice. On a real-world trace
they diverge immediately (`{"body": "key=<secret>"}` fires under containment,
not under equality), so this is a latent behavioral fork, not a cosmetic one.

**(d) Phase 2 must decide.** Pick one rule and **reconcile all three passages to
one wording**. Note the asymmetry in the failure modes: containment is more
sensitive (it is the one that catches a secret embedded in a body) and cannot
overclaim — it still requires the value to appear untransformed — while
equality risks silently missing real flows and would make the realized tier
much weaker than a reader of `SPEC.md` §5 would expect.

---

## 2. `MIN_VALUE_CHARS = 8` — an extraction parameter that is not disclosed

**(a) The tension.** `DESIGN.md` §4 names extraction parameters ("what counts as
a secret-like token, normalization rules") as a **possible later, cautiously
exposed third layer — Phase 2+, each knob disclosed in findings output
("detected under config X")**. Phase 1 introduced such a knob and did **not**
disclose it per-finding.

**(b) Where it surfaced.** `trifecta_lens/taint.py`, `MIN_VALUE_CHARS = 8`.
Values shorter than 8 characters are not tracked at all — a 3-character string
would collide with ordinary payload text and produce noise, not evidence. The
constant is documented in the module and referenced from `extract_values()` and
`value_in_payload()`, but a finding's `scope` field states only the
verbatim-only limit; it does not say "values under 8 characters were not
tracked."

**(c) Why deferred.** It is invisible on the committed fixtures (every tracked
value is far longer than 8 characters), and inventing a disclosure format for a
one-knob layer ahead of the catalog work would be pulling Phase 2 breadth
forward.

**(d) Phase 2 must decide.** Either **disclose it per-finding** (the
`DESIGN.md` §4 "detected under config X" note), or **promote it into the
exposed extraction-parameter layer** properly, alongside whatever other knobs
the catalog work introduces. What it must not remain is an undisclosed
threshold that silently bounds what the realized tier can see: an undisclosed
knob makes "no finding" un-auditable, which is the same honesty failure as an
overclaim, pointed the other way.

---

## 3. The reported path is **temporal**, not causal

**(a) The tension.** `DESIGN.md` §1 defines the trace event graph's edges as
"causal ancestry (`parent_id`) **plus temporal order**." In the realized anchor,
**every tool span is a sibling under the root `s0`** — so `parent_id`
contributes *nothing* to the ordering, and the reported path `s3 → s4` rests on
**temporal order alone**. We observed the vault read happen before the webhook
post. We did not observe that the vault read *fed* the webhook post.

**(b) Where it surfaced.** `trifecta_lens/engine.py` (the fold treats everything
already consumed as the current event's ancestry) and, most visibly,
`trifecta_lens/svg.py` — the shareable artifact draws `s3 → s4` as **an arrow**.

**(c) Why deferred.** This is *consistent* with `CLAUDE.md` invariant 4 as
implemented: the finding's text says only "tainted data observed reaching
webhook", the value genuinely did appear at the sink verbatim, and no causal
claim is made in any string we emit. So nothing is currently false. But an arrow
is a strong visual claim, and the artifact is designed to travel out of context;
a reader may well read it as "this caused that."

**(d) Phase 2 must decide** the deliberate framing — and this is a **halt-level
honesty question, not a rendering nit**. Options include: annotating the edge as
temporal-adjacency rather than causation, exploiting real `parent_id` chains
where an instrumentor actually provides them (many will), or distinguishing
"causally linked" from "temporally ordered" paths in the finding schema. Decide
it in the planning chat; do not let it be settled by whatever the SVG happens to
draw.

---

## 4. The 0.8 architecture gate has a blind spot

**(a) The tension.** The gate (`tests/test_gates.py`,
`per_tool_branches_in()`) enforces `CLAUDE.md` invariant 2 by failing on any
**comparison** of a tool-ish expression against a string literal — `if tool ==
"webhook"`, `if event.tool in ("fetch", "vault")`. It cannot see a per-tool
**dict table**. A future contributor could put `{"webhook": ..., "vault": ...}`
directly inside the engine and the gate would stay green, even though that is
exactly the "per-path code" the invariant forbids.

**(b) Where it surfaced.** Writing `trifecta_lens/labeling.py`, whose
`_SLICE_LABELS` **is** a per-tool dict table. That placement is correct and
intended — labeling is the tunable layer, and the table is the Phase-1 stand-in
for the catalog (`# TEMP: catalog in P2`). The point is that the gate cannot
distinguish the legitimate table in `labeling.py` from an illegitimate one in
`engine.py`; it passes both.

**(c) Why deferred.** No violation exists today: the engine sees roles only and
never learns a tool name, which was verified by reading it, not merely by the
gate passing. Hardening the gate is a change to the gate's semantics, and doing
it while the catalog module does not yet exist would mean guessing at the
boundary it needs to police.

**(d) Phase 2 must decide** how to harden it once the catalog lands — the
natural rule being **module-scoped**: tool-name-keyed data is legal in the
catalog/labeling front-end (Stage 1) and illegal in the engine (Stage 2),
which is just `DESIGN.md` §5's two-stage seam expressed as a gate. Until then,
the invariant is upheld by review, and this file is the record that we know the
gate alone does not uphold it.

## 5. Multi-format input support — where format-specific handling lives  *(RESOLVED → D12)*

**Tension:** Different agents/tools produce different output shapes. Two distinct
layers are involved and must not be conflated: the *telemetry envelope* (span
structure / attribute keys — standardized on OTel/OpenInference) and the *payload
contents* inside input.value/output.value (JSON vs HTML vs base64 vs nested
objects), which genuinely diverge per tool. v1 consumes exactly one envelope
dialect (the flat OpenInference JSONL the demo harness emits).

**Where it surfaces:** Stage 1 (construction) — the loader and value extraction
(SPEC §6). The engine (Stage 2) is format-blind and must stay so.

**Why deferred:** Building a general pluggable-format abstraction against a single
known format produces a speculative design the second real format will break
(same lesson as capturing vs hand-authoring the trace). We need at least one real
non-demo trace/format in hand before fixing the seam's shape. This is the same
decision as the Event-shape open question, viewed from the format angle — resolve
them together.

**What Phase 2 must decide:**
- Confirm the split: envelope adapters (framework/dialect → Event) and payload
  value-extractors (varied cargo → taint values) BOTH live in Stage 1; the
  automaton never learns what any framework is.
- "Add support for an agent" = add a Stage-1 adapter/extractor (bounded mapping +
  data), never a new engine branch — extend "catalog, not per-path code" to the
  format layer.
- Ship one format now (flat OpenInference). Name the nested-OTLP exporter adapter
  as the first Phase 2+ addition (per FIXTURES.md), but do NOT generalize the
  adapter layer until a real second format forces its shape.
- Decide how much the Event model must change to accommodate non-demo traces
  (this gates the Stage-1 seam and is coupled to the Event-shape question).
