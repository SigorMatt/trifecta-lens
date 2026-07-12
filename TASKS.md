# TASKS.md — phase task breakdown (living doc)

Companion to `ROADMAP.md` (sequencing), `SPEC.md` (behavior), `CLAUDE.md`
(process), `DESIGN.md` (engine architecture). This file is the working
checklist Claude Code executes against.

**How to use this file**
- **Resolution rule.** The current + next phase are specified at PR granularity.
  Later phases are intentionally coarse and *provisional*. Sharpen a phase to
  PR-level only when the prior phase's exit criterion is met — over-specifying
  speculative work now is pulling breadth forward, which `CLAUDE.md` forbids.
- **One task = one reviewable PR.** Keep diffs small.
- **Done means done.** A task is complete only when its fixture(s) + test exist
  *and* the honesty invariants (`CLAUDE.md` 3–5) hold in the output **text**,
  not just the logic.
- Update this file in the same PR whenever scope changes. Check boxes as you go.

---

## Phase 0 — Skeleton & contract

- [x] **0.1 Repo scaffold.** `pyproject.toml` (Python 3.11+, ruff/mypy/pytest),
  package layout `trifecta_lens/` (core) + `trifecta_lens/cli.py`, `LICENSE`,
  `.gitignore`, README stub. *Done when `uv sync --extra dev` succeeds and
  `uv run python -c "import trifecta_lens"` exits 0.*
- [x] **0.2 CLI entrypoint.** `console_scripts` → `trifecta-lens`; `--version`
  prints the version. *Done when `trifecta-lens --version` runs.*
- [x] **0.3 CI.** GitHub Actions: ruff + mypy + pytest on push/PR.
  *Done when CI is green on a trivial test.*
- [x] **0.4 "No network in core" guard.** A test (import/AST scan) that fails if
  `requests`/`httpx`/`socket`/`urllib.request` appear under the core package.
  Encodes `CLAUDE.md` invariant 1. *Done when it fails on a deliberately-added
  `import requests` and passes otherwise.*
- [x] **0.5 Event model.** Typed `Event` per `SPEC.md` §2, pure (no I/O).
  *Done when it round-trips a hand-written event.*
- [x] **0.6 Trace-fixture format + loader.** Define the JSONL span schema (the
  OTel/OpenInference subset in `SPEC.md` §7) and a loader that parses one
  fixture into `Event[]`. *Done when one committed fixture loads and parses.*
- [x] **0.7 Acceptance harness (`make check`).** The phase done-whens as runnable
  checks, not prose: `trifecta-lens --version` exits 0; the worked fixture loads
  to the expected `Event` count. (Extended in Phase 1: positive fixture → exactly
  one realized finding with the path; benign → none; re-run byte-identical.)
  Wired into CI. *Done when `make check` passes on the Phase 0 deliverables.*
- [x] **0.8 Honesty + architecture gates (CI).** A test that fails if report text
  contains banned causal/attack tokens (`attack`, `exfiltration occurred`,
  `caused`, …); an import/AST check that fails if detection core contains a
  per-tool branch (`if tool ==` / `== "<name>"`). Encodes `CLAUDE.md` invariants
  2 and 4. *Done when each gate fails on a deliberately-planted violation and
  passes otherwise.*
  **(Phase 0 exit.)**

---

## Phase 1 — Vertical slice (the demo)

Build the whole pipeline (ingest → label → detect → report → render) for the
**one** hardcoded path. Realized-only. **No catalog yet** — extract it in Phase 2.

- [x] **1.1 Demo agent harness (`make demo-live`).** Three stub MCP tools —
  `fetch` (returns the fixture poisoned page), `vault` (returns `secret.txt`),
  `webhook` (POSTs + logs) — wired to a stock tool-calling host with
  OpenInference instrumentation emitting payload-level spans to JSONL. Keep the
  agent boring (`CLAUDE.md`: not a strawman). **Lives in `demo/`, outside the
  core package**, so its network/exec use never trips the 0.4 guard.
  *Done when a live run emits a payload-level span file.*
- [x] **1.2 Record + freeze the demo trace (`make demo`).** Capture one real run
  from 1.1; commit the spans as the frozen anchor. This one file is the
  deterministic showcase **and** the realized test anchor **and** the first
  shareable. *Done when `make demo` replays it with no model call.*
  **As captured:** the committed anchor is `fixtures/demo_realized.jsonl` (not
  the provisionally-named `demo_exfil.jsonl`) — a real **direct-instruction,
  non-injection** run on Llama-3.3-70B in which the secret reaches the webhook
  sink verbatim. It carries the vault→webhook flow twice (`s2` posts a
  placeholder, `s4` posts the secret), and it has **no untrusted-source span**.
  See `fixtures/demo_realized.provenance.md` and `demo/CAPTURE_LOG.md`: no
  captured run exists in which an untrusted-source leg and a verbatim secret at
  a sink co-occur. This is why the anchor supports the two-leg family, not the
  trifecta (`SPEC.md` §3).
- [x] **1.3 Ingest.** Extend the 0.6 loader to full payload-level extraction
  (inputs/outputs) per `SPEC.md` §2. *Done when the demo fixture yields the
  expected Event stream.* — The 0.6 loader already extracted both payloads
  (both mime types, absent-vs-empty distinguished), so no loader change was
  needed; 1.3 is the anchoring test `tests/test_ingest.py`: all 5 spans, vault
  outputs on s1/s3, webhook inputs on s2/s4, ancestry from `parent_id`, sorted
  by `start_time`.
- [x] **1.4 Hardcoded labeling (slice-only).** Assign source / sensitive /
  exfil roles to the demo tools directly. Tag `# TEMP: catalog in P2`.
  *Done when the demo events carry the right roles.* — `trifecta_lens/roles.py`
  (the role alphabet) + `trifecta_lens/labeling.py` (a slice-local **data
  table**, not code paths: `vault`→`sensitive_data`, `webhook`→`sink:exfil`).
  **No span is labeled `untrusted_source`** — the anchor has none, and inventing
  one to make the trifecta accept is the mislabeling this project must not do.
- [x] **1.5 Value extraction + verbatim taint** (`SPEC.md` §6). Extract the
  secret from the vault span; normalized-exact match into the webhook span
  inputs. *Done when the secret is detected crossing vault→webhook and is NOT
  detected in the benign fixture.* — `trifecta_lens/taint.py`. Matches at `s4`,
  does **not** match at `s2` (placeholder), and does not match in either triage
  fixture. Tests pin that transformed taint (base64 / split / paraphrase) does
  **not** match — the v1 limit, stated, not papered over.
- [x] **1.6 Realized detector + the two-leg family (approved spec change).** Emit
  a finding when a tainted value reaches the sink, with the ordered path and
  masked value. Findings serialize as NDJSON — one finding per line,
  `sort_keys=True`, written as found (`DESIGN.md` §6). Output text is *"tainted
  data observed reaching <sink>"* — no causal/attack language (`CLAUDE.md` 4).
  *Done when the positive fixture yields one realized finding with the path and
  the benign yields none.*
  **Spec-first:** `SPEC.md` §3/§3.1/§5 and `DESIGN.md` §2/§3 now define
  `sensitive_to_exfil_sink` — a **relaxation of the same exfil automaton**
  (drop the `untrusted_source` conjunct, keep the guard), reported as the lesser
  family that always names the source leg as not-observed. The trifecta stays
  defined and *exercised* (`worked_example.jsonl`, which has a real `fetch`
  source leg, yields `exfil_trifecta`). Code: `trifecta_lens/engine.py` (the fold)
  + `trifecta_lens/findings.py` (the NDJSON append-stream).
  **Acceptance verified:** anchor → exactly one `sensitive_to_exfil_sink`
  finding, sink `s4`, path `s3 → s4`, value masked; nothing on `s2`; no trifecta
  finding on the anchor; zero on both triage fixtures.
- [x] **1.7 Tiered human report** (realized only for the slice) with a tier
  badge. *Done when it prints the masked verdict.* — `trifecta_lens/report.py`,
  reachable via `trifecta-lens --trace <file>`. Prints `[REALIZED]
  sensitive_to_exfil_sink (two-leg — NOT the trifecta)`, the path, the masked
  value, and the legs observed / **not** observed. States that posture and
  reachable did not run, and that no finding is not evidence of no flow.
  Degrades honestly: a payload-less trace reports realized `UNAVAILABLE`, not
  "no findings". The 0.8 honesty gate now scans the **rendered** report and
  findings NDJSON for every shipped fixture, as its docstring promised.
- [x] **1.8 SVG renderer.** The red-edge path artifact (the screenshot).
  Hand-positioned layout; no graphviz (`DESIGN.md` §8).
  *Done when `make demo` writes the SVG.* — `trifecta_lens/svg.py`; `make demo`
  writes `out/demo_realized.svg` (+ `out/demo_realized.findings.ndjson`).
  Renders `s3 (vault, sensitive_data) → s4 (webhook, sink:exfil)` on a red edge.
  Because the SVG is the thing that gets screenshotted **out of context**, it
  carries its own honesty: the `[REALIZED] sensitive_to_exfil_sink` badge,
  "(two-leg — NOT the trifecta)", `not observed: untrusted_source`, the masked
  value, and "flow observed, not causation".
- [x] **1.9 Benign fixture + tests + determinism.** A clean run that produces
  NO realized finding; pytest anchoring positive→realized and benign→none;
  re-run gives byte-identical findings. *Done when all green.*
  Added `fixtures/benign_no_flow.jsonl` (hand-authored): it calls **both**
  labeled tools — `vault` *and* `webhook` — but never posts the secret. Its
  silence therefore cannot come from the labeling, only from the verbatim guard
  failing. The two captured triage fixtures are silent for a *different* reason
  (they never call a labeled tool at all), and `tests/test_determinism.py` names
  both reasons rather than lumping them together. 0.7's acceptance harness now
  carries the Phase-1 done-whens, as it always said it would.
  **(Phase 1 exit.)**

---

## Phase 2 — Generalize to the engine

> **Read `DECISIONS.md` first** — the nine decisions (D1–D9) taken in the Phase 2
> planning conversation, including the two research findings that proved
> `SPEC.md` §7 (the "manifest") and `DESIGN.md` §1 (reachable-as-type-compat)
> **wrong**. `OPEN_QUESTIONS.md` §§1–4 are resolved there as D3–D6.
>
> **`OPEN_QUESTIONS.md` §5 (multi-format input) is still OPEN**, and 2.7 is where
> it gets answered — its deferral condition ("a real non-demo format in hand
> before fixing the seam's shape") is satisfied by Checkpoint D. Do not
> generalize the adapter layer ahead of that real format.

**Shape of the phase.** One human capture (**Checkpoint D**) is the root
dependency: it yields *both* the tool inventory and the real OTLP trace. Track A
is independent of it and starts immediately; Track C is gated on it.

**Standing rules** (unchanged from Phase 0/1): one task = one PR; spec-first
(update `SPEC.md`/`DESIGN.md` in the same PR); write the fixture/test and its
expected output **before** the implementation; each commit leaves `make check`
green; check the box in the same commit.

**Halt-and-ask points in this phase:** Checkpoint D itself; any change to the
automaton's *structure* (states/transitions/acceptance — `DESIGN.md` §4); and
**2.11's non-vacuity result** — if `reachable ⊊ posture` does not hold on the real
captured inventory, STOP and decide (D7's constructed fallback), do not proceed by
weakening the tier.

---

### Track A — the existing realized tier *(independent of Checkpoint D; start now)*

- [x] **2.1 Containment + disclosed extraction config** (D3 + D4; resolves
  `OPEN_QUESTIONS.md` §§1–2). **Spec-first:** reconcile `SPEC.md` §6 ("Match =
  exact"), `SPEC.md` §5 step 3 ("appears in") and `DESIGN.md` §8 ("substring") to
  **one** wording — containment of the untransformed value. Promote
  `MIN_VALUE_CHARS` into a declared extraction config, disclosed per-finding as
  `detected_under` and in the report footer. Fixed, **not** user-tunable (invariant
  2: the catalog stays the only knob). *Done when: the three passages agree; every
  finding carries `detected_under`; and the constant ships with a **measured**
  false-positive justification against the benign corpus — a number, not an
  assertion.* — `trifecta_lens/extraction.py`; `detected_under` on every finding
  and in every report (**including silent ones** — "no finding" is only auditable
  if you know the bounds). **The first measurement refuted the claim:** the benign
  corpus gave zero false positives at *every* threshold, even 1, so `8` was
  justified by nothing. Added `fixtures/benign_short_value_collision.jsonl` (a
  4-char vault value colliding with a record count at the sink), which makes the
  curve real: FP at ≤4, silent at ≥5, true positives survive to 16 — so the
  shipped 8 sits **in the middle of the safe window**, with margin on both sides.
- [x] **2.2 `path_basis` labelling** (D5; resolves `OPEN_QUESTIONS.md` §3).
  **Spec-first:** `SPEC.md` §5, `DESIGN.md` §1. Each path edge carries its basis
  (`causal` from real `parent_id` ancestry, `temporal` from ordering alone); the
  finding carries a **required** `path_basis` field (`causal`|`temporal`|`mixed`);
  the SVG annotates the edge. *Done when: the anchor's finding reads
  `path_basis: temporal` (correctly — its tool spans are siblings under the root);
  a fixture with a real parent chain reads `causal`; and the SVG edge is labelled.
  **Blocks any public artifact.***
- [x] **2.3 Harden the architecture gate to the stage seam** (D6; resolves
  `OPEN_QUESTIONS.md` §4). The 0.8 gate learns `DESIGN.md` §5: tool-name-keyed data
  is legal in **Stage 1** (loader, inventory front-end, catalog/labeling), illegal
  in **Stage 2** (engine, taint, findings, report, svg). *Done when the gate fails
  on a per-tool dict table planted in `engine.py` and passes on the same table in
  `labeling.py`.* — Verified by **planting the real violation in `engine.py`** and
  watching the gate fire, not only by unit-testing synthetic AST. The gate flags
  the **lookup**, not the table: a tool-keyed table is the labeling function's
  whole job, and a table nobody consults is harmless — what must never happen is
  the *engine* looking a tool up in one. A coverage test also fails if a new core
  module is added without being assigned to a stage.

### Track B — the real-MCP capture *(the root dependency)*

> **▶ NEXT SESSION STARTS HERE.** Track A (2.1–2.3) is merged; `main` is green
> (114 tests). Begin at **2.4**, then 2.5 → Checkpoint D → 2.6 → 2.7.
>
> **Use `HF_TOKEN`, not ollama.** The machine has ~4 GiB RAM free and no GPU, so
> the local 7–8B models do not fit — and `demo/CAPTURE_LOG.md` already records
> that they *fail this task* (qwen2.5 paraphrased the secret; llama3.1 sent an
> empty body). Neither threads a value **verbatim**, which is the one step the
> detector keys on. `demo/providers.py` already reads `HF_TOKEN`, and
> `CAPTURE_LOG.md` records `Llama-3.3-70B` via HF→Groq **succeeding** at exactly
> this. An Anthropic key can be exported if 70B proves insufficient — ask first.
>
> **One capture, two artifacts.** The **inventory** half (`tools/list` over stdio)
> needs **no model at all** — build and run it first, it is free. Only the
> **trace** half needs the model, and it is a single short run.
>
> **The acceptance is the composability join:** the trace's tool names must match
> the inventory's tool names. That is what makes "the three tiers describe one
> system" a checkable property instead of a hope — and it is why the trace must
> come from an agent that really drives the MCP servers, not from local Python
> functions (`DECISIONS.md` D8).

- [x] **2.4 Rebuild the demo as a real MCP client** (D8). MCP SDK over stdio
  against **real reference servers**, with real OpenInference instrumentation and
  OTLP export. Lives in `demo/`, outside core, so its transport/exec use never
  trips the 0.4 gate. **Bounded to minimum-viable:** the smallest real setup that
  can yield a multi-context inventory and a namespace-matching trace; servers
  chosen for **realness + ease, not scenario drama**; **inert fail-closed sink, no
  real credentials**; direct-instruction is fine (no live exploit required —
  Checkpoint B precedent). *Done when a live run against real MCP servers emits
  payload-level OTLP spans.* — New Phase 2 harness under `demo/`: `mcp_config.py`
  (topology as data + `<server>__<tool>` namespacing), `sink_server.py` (the
  **inert, fail-closed** `notify` MCP server), `mcp_client.py` (async
  tools/list + tools/call loop), `otel_export.py` (real OTel tracer → official
  OTLP encoder → OTLP/JSON), `run_mcp.py`. Servers: `fetch` (uvx
  mcp-server-fetch) + `filesystem` (npx server-filesystem, scoped to
  `demo/vault`) + our `notify` sink. **Pipeline proven end-to-end** by a scripted
  provider (no model, no credits): real stdio to all three servers, real
  `tools/call`, namespaced routing, OTLP spans with the OpenInference keys the
  core loader keys on — the fake secret reaches the sink verbatim in
  `input.value`. The **model-driven** capture is Checkpoint D. The Phase 1 flat
  harness is retained only for the anchor replay (`make demo`). Heavy SDKs
  imported lazily, so `make check` (dev-only) stays green.
- [x] **2.5 Inventory capture script** (D2). Outside core (`contrib/` or `demo/`).
  Speaks `tools/list` to each configured server and writes the inventory JSON:
  `contexts[]`, each with an id, its **effective** tool set, and a **human-written**
  provenance note. *Done when it produces a well-formed inventory from a running
  server set.* — `demo/capture_inventory.py`: launches each context's servers over
  stdio, records the verbatim `tools/list` entries (each tagged with its server so
  the loader can form the `<server>__<tool>` name the trace uses), and writes
  `{contexts: [{id, provenance, servers, tools}]}`. Provenance is human-written
  prose per context (intent + capture method), and the `triage` note states in
  prose *why* it is a subset (no outbound sink) — the non-vacuity auditability D7
  wants. Needs **no model**. The actual captured inventory artifact lands at
  Checkpoint D.
- [x] 🛑 **CHECKPOINT D — human capture (halt).** A human runs 2.4 + 2.5 and
  commits: the **inventory fixture** (≥2 contexts), the **real OTLP trace fixture**,
  and provenance for both. **The build agent must never fabricate either artifact**
  — same line as Checkpoint B. *Exit: both fixtures committed, with provenance
  stating exactly what was captured and what it may be used to claim.* — Run in
  this session under the operator's direction with the operator-provided
  `HF_TOKEN` (real captures, never authored). Committed:
  `fixtures/inventory.json` (2 contexts; triage ⊊ assistant by exactly the
  `notify__send` sink ⇒ reachable ⊊ posture on a REAL inventory, D1 non-vacuity
  met, D7 fallback not needed) and `fixtures/demo_mcp_trace.otlp.json` (real
  OTLP/JSON; Llama-3.3-70B direct-instruction; secret reaches `notify__send`
  VERBATIM), each with a `.provenance.md`; capture recorded in
  `demo/CAPTURE_LOG.md`. The first trace attempt placeholdered the body — the
  direct instruction was sharpened to require the literal value (disclosed in
  provenance), and the sharpened-prompt run was committed as-is. Composability
  join (trace tool names ⊆ inventory tool names) holds; it becomes an executable
  assertion in 2.6.
- [x] **2.6 Inventory loader + the composability join** (D2, D8). Stage 1
  front-end: inventory JSON → labeled topology values. **Spec-first:** correct
  `SPEC.md` §7 — the manifest does **not** contain tools (D2/F1). *Done when the
  captured inventory loads, **and** a fixture assertion proves the trace's tool
  names match the inventory's tool names — the join that makes "the three tiers
  describe one system" checkable rather than hoped-for.* — `trifecta_lens/inventory.py`
  loads the captured `contexts[]` into `Inventory`/`Context`/`ToolRef` values with
  server-qualified (`<server>__<tool>`) identity and a `posture_tools()` union; no
  role labeling yet (that is the catalog, 2.8). `tests/test_inventory.py` loads the
  **real** Checkpoint D inventory and asserts (a) `triage ⊊ posture`, differing by
  exactly `notify__send` (non-vacuity, read off the artifact), and (b) the
  **composability join** — the real trace's tool names ⊆ the inventory's. SPEC §7
  updated with the qualified-identity join; the D6 stage-seam gate now classifies
  `inventory.py` as Stage 1.
- [x] **2.7 Real OTLP / OpenInference front-end** (D9). A new Stage 1 adapter —
  never an engine change (`FIXTURES.md`). Built against the **real captured trace**,
  not an imagined one. Handles nested OTLP attribute arrays, MCP tool
  **namespacing** (server-qualified tool identity — an `Event` shape change, so:
  spec-first on `SPEC.md` §2), and the richer keys real traces carry
  (`retrieval.documents.*` → RAG reads as `untrusted_source`; LLM message
  payloads). *Done when the real captured trace loads to the expected Event stream
  and the existing realized detector runs on it unchanged.* — `load_otlp_trace` in
  `trifecta_lens/loader.py`: decodes the OTLP/JSON envelope
  (`resourceSpans[].scopeSpans[].spans[]`, base64 span ids → hex, nanos → seconds,
  `{key, value:{stringValue}}` attribute arrays) into the **same intermediate span
  shape** the flat loader consumes, then reuses `_event_from_span` — one
  attribute→Event mapping, not two. `tests/test_otlp_loader.py` proves the **real**
  Checkpoint D trace loads to the expected 3-Event stream (agent root + two tool
  children, ancestry preserved) and that the **unmodified** `detect_realized` fires
  exactly one `sensitive_to_exfil_sink` finding (temporal basis, secret masked)
  once the events are labeled. Spec-first: `SPEC.md` §2 (server-qualified tool
  identity) + `FIXTURES.md` (OTLP front-end landed). **Scope, stated honestly:**
  the adapter handles the keys the real trace actually carries (TOOL/AGENT spans
  with the flat OI payload keys). RAG `retrieval.documents.*` and LLM-message
  payload ingestion are **not** built — no captured fixture carries them yet, and
  building an ingest path no real trace exercises is the speculative breadth
  `CLAUDE.md` forbids (the same "a real format in hand first" rule the phase header
  applies to `OPEN_QUESTIONS.md` §5). Non-TOOL spans already load harmlessly
  (tool=None); RAG/LLM ingestion lands when a real trace carries them.

### Track C — the engine and the two new tiers *(gated on Checkpoint D)*

- [x] **2.8 Extract the catalog** (`SPEC.md` §4). The 1.4 `# TEMP` table becomes a
  data file (`match → role + subtype + note`) plus a `--catalog` overlay. The
  catalog is the labeling function and **the only tunable layer** (`DESIGN.md` §4).
  *Done when the Phase-1 fixtures produce byte-identical findings with the labels
  served from the catalog instead of the hardcoded table.* — `trifecta_lens/catalog.py`
  (Stage 1) + `catalogs/exfil_v1.yaml`. `match.tool` is a fully-anchored regex, so
  one catalog covers **both** name spaces: the flat fixtures' bare names and a real
  MCP stack's server-qualified `<server>__<tool>` (SPEC.md §2). Byte-identity is
  **proven, not asserted**: `fixtures/golden/` holds the findings the *pre-catalog*
  table emitted (generated before the swap), and `tests/test_catalog.py` asserts the
  live pipeline reproduces them character-for-character; `make golden` regenerates
  them when a change is *meant* to move the output. Notes now travel on
  `Event.role_notes` (SPEC.md §2), so a finding cites the entry that assigned each
  role while the engine stays tool-blind — it reads the note **by role**, never by
  tool, and the D6 stage-seam gate still holds. **The carry-over is met:** the real
  Checkpoint D OTLP trace now fires through the CLI (`--trace demo_mcp_trace.otlp.json`,
  format auto-detected) with the **unmodified** engine — one `sensitive_to_exfil_sink`
  at `notify__send`. Impact-sink entries (`filesystem__write_file`) ship in the
  catalog and change no v1 finding: coverage is data, acceptance is the fixed
  machine.
- [x] **2.9 Extract the engine** as the fixed property automaton over labeled
  graphs (`DESIGN.md` §§2–3, 5). Two-stage seam enforced: the engine sees labeled
  graphs only — never JSONL, OpenInference keys, or the inventory format. **Binding:**
  incremental fold; NDJSON append-stream (`DESIGN.md` §6). *Done when all Phase-1
  findings are unchanged and the engine module imports no front-end.* — The
  acceptance predicate is now **one function**, `engine.satisfied_families(legs)`,
  and `FAMILIES` (strongest-first) is the whole of the machine's acceptance
  condition. All three tiers call it: realized hands it a trace path's ancestry,
  reachable one context's exposed roles, posture the union — so
  `realized ⊆ reachable ⊆ posture` becomes structural (the tiers differ *only* in
  the leg set they pass), rather than resting on the report text agreeing with
  itself. The seam grew its second half: `model.LabeledTool/LabeledContext/LabeledStack`
  (SPEC.md §2.1), built by `labeling.label_inventory` from the captured inventory
  with **the same catalog** that labels the trace — which is precisely why a
  realized finding at a sink is guaranteed a reachable/posture counterpart at that
  sink. `posture_context()` collapses the stack to one bag of tools so posture and
  reachable are the *same code path* over a weaker input, not two detectors kept in
  agreement by hand. The done-when is enforced, not promised: a new gate
  (`test_stage_2_imports_no_front_end`) fails if any Stage-2 module imports a Stage-1
  one — **verified by planting `from trifecta_lens.loader import load_trace` in
  `engine.py` and watching it fire**. Findings byte-identical (`fixtures/golden/`).
- [x] **2.10 Posture tier** (D1). Roles present in the **union** of the inventory's
  contexts; no edges, no guard. *Done when the captured inventory yields posture
  findings, and `realized ⊆ posture` is an executable property test.* —
  `engine.detect_posture` is `detect_capability(stack.posture_context(), TIER_POSTURE)`:
  the **same** `satisfied_families` predicate, over the union of the stack instead of
  a path's ancestry. The real Checkpoint D inventory yields one posture finding —
  `exfil_trifecta` at `notify__send`, all three legs present in the union — and
  `test_realized_is_contained_in_posture_on_the_real_capture` proves `realized ⊆ posture`
  over the **real trace + real inventory**, compared at the *acceptance predicate*
  (not the reported family, which is only ever the strongest — comparing those would
  compare two projections and prove nothing). **Tier honesty is structural, not
  editorial:** `CapabilityFinding` is a different type with **no** `path`,
  `path_basis`, `masked_values` or `legs_observed` field — posture observed nothing,
  so there is nowhere to put the stronger claim, and a test asserts those keys are
  absent from the serialized line. Posture's union context announces itself as
  synthetic (`*posture-union*`) so it can never be misread as a real agent context
  (i.e. as reachable). Gate fix: type annotations are exempt from the tool-lookup
  scan — `tools: tuple[ToolCitation, ...]` is a declaration, not a lookup — with a
  test pinning that the carve-out is not a loophole.
- [x] **2.11 Reachable tier + collapse disclosure + non-vacuity** (D1, D7).
  Reachable = all legs co-exposed in **one context**; the same machine with edges on
  and the guard off. **Must detect and disclose the collapse case**
  (`reachable == posture` ⇒ say "reachable adds no information on this stack: all
  legs share one context"). *Done when: the real captured inventory demonstrates
  `reachable ⊊ posture` (**non-vacuity**); a single-context inventory triggers the
  collapse disclosure; and `realized ⊆ reachable ⊆ posture` is an executable
  property test.* **🛑 If non-vacuity fails on the real inventory, HALT** — do not
  weaken the tier to make it pass; take D7's constructed fallback, which is itself
  held to "instantiates a **documented in-the-wild topology**", not "discriminates".
  — **🛑 The halt condition did NOT fire: non-vacuity holds on the real capture,
  checked rather than trusted.** `reachable_collapse` reports
  `collapsed=False, narrowed=('triage',)`: the real `triage` context carries the
  source and sensitive legs but **no outbound sink**, so it cannot wire the family
  posture finds — a distinction posture is structurally unable to see. D7's
  constructed fallback was therefore never needed. `detect_reachable` is the same
  `detect_capability` call as posture, run per real context. **The collapse
  disclosure ships anyway** (D1 binds it regardless of the capture): a stack where
  every context accepts what the union accepts is detected and disclosed *in the
  finding itself* (a `disclosure` field), not merely in the report — an NDJSON
  consumer must not have to trust that someone printed the caveat elsewhere. It is
  exercised by slicing the real inventory to one captured context (a projection of a
  real capture, never an invention). `realized ⊆ reachable ⊆ posture` is executable
  on the real trace + real inventory, compared at the acceptance predicate. **And the
  gap between the tiers is real, and is the product:** the captured run realized only
  the **two-leg** family, while the same `assistant` context is *also* exposed to
  `fetch__fetch` — so the full trifecta is **reachable but was not realized**.
  "Could, but didn't" is exactly what this tier exists to say. **Determinism bug
  caught and fixed:** leg order was read off `family.required`, a **frozenset**,
  whose iteration order is randomized per process — findings were byte-identical
  within a run and differed *between* runs, the one way a same-process test can never
  see. Fixed to the fixed reporting order;
  `test_capability_findings_are_deterministic_ACROSS_PROCESSES` now runs the pipeline
  under four `PYTHONHASHSEED`s and demands identical bytes (verified by reintroducing
  the bug and watching it fail).
- [x] **2.12 Tiered output across all three tiers.** Report, SVG and findings NDJSON
  carry tier + family + `path_basis` + `detected_under`. Tier honesty holds in the
  **text**, not just the logic (`CLAUDE.md` 3). *Done when a single run over
  inventory + trace emits all three tiers, each correctly badged, and the honesty
  gate scans the rendered output for all of them.* — `trifecta-lens --trace ... --inventory ...`
  (see `make demo-mcp`) emits all three tiers over the two **real** Checkpoint D
  artifacts. `report.TierResults` makes the load-bearing distinction explicit:
  `None` = **the tier did not run**, `()` = the tier ran and found nothing. They are
  rendered differently, because an empty posture section that a reader takes for a
  clean bill of health is exactly the quiet failure this project cannot afford.
  Tiers print strongest-first, so posture is never the headline. **The capability
  tiers never borrow realized's verb:** they print `legs exposed:`, never
  `legs observed:`, and say "no run was observed doing so" outright — pinned by a
  test that scans the capability sections for realized's language. NDJSON carries
  every tier, strongest-first, each line self-describing. The **SVG** now shows the
  tier gap — `[REACHABLE, NOT OBSERVED] exfil_trifecta` — in grey, below the path,
  never on the red edge (red means *observed*); it is the most interesting fact on
  the artifact and the easiest place to overclaim. Geometry is checked
  arithmetically (no rasterizer in CI) because the honesty disclaimers sit at the
  bottom and are the first thing a too-small canvas would silently truncate. The
  0.8 honesty gate now renders and scans **all three tiers plus the SVG**.
- [x] **2.13 Default v1 exfil catalog + docs.** Catalog entries for the servers the
  capture actually used, plus the source/sink lists in `SPEC.md` §4.
  `CONTRIBUTING.md` frames "add a catalog entry" as the contribution path.
  *Done when a stranger's server can be covered by editing data, not code.* —
  The default catalog now carries `SPEC.md` §4's source/sink lists: issue/PR/comment
  text and inbound mail (untrusted_source), secret and memory reads (sensitive_data),
  outbound HTTP, message send and **writes to a shared/public location**
  (sink:exfil — a comment on a public issue publishes the payload as surely as a POST
  does), plus shell/merge impact sinks that **no v1 family accepts on**.
  **Done-when, executable:** `test_A_STRANGERS_SERVER_IS_COVERED_BY_EDITING_DATA_NOT_CODE`
  takes a stack the project has never heard of (`crm__read_customer_rows`,
  `wiki__publish_page`), shows it is invisible under the shipped catalog, and makes
  the **unmodified** engine detect the full trifecta on it with one overlay file —
  verified by hand through the real CLI too. **SPEC §4 was overclaiming** and is
  corrected to what actually ships, including what is deliberately *absent*: RAG reads
  (real tools spell them `search`/`query`/`retrieve`, names shared with harmless
  tools — no captured trace carries one, and a pattern invented for one is a guess)
  and directory listings (they return *names*; labeling them would make every `ls` a
  leg). A test holds the docs and the catalog together. **SPEC §4's citation
  requirement is now real:** every finding names the **catalog entry id** that
  assigned each role (`Event.role_labels`, `Leg.catalog_entry`,
  `ToolCitation.catalog_entry`), so a user who disagrees knows what to edit rather
  than having to read our source — goldens regenerated, the diff showing exactly the
  one added field. **The benign corpus got stronger, not weaker:** the triage fixtures
  now carry `untrusted_source` + `sink:exfil` and are *still* silent, so their silence
  is load-bearing — it can only come from the machine requiring a sensitive leg
  (SPEC.md §3), where before it merely meant "no labeled tool was called".
  **(Phase 2 exit.)**

**Exit:** a real MCP stack's inventory + a real trace → all three tiers, honestly
tiered and disclosed; "point it at your own agent" is **true**, not aspirational.

**Honest fallback (D9), retained:** if 2.7 overruns, reword the exit and defer the
OTLP adapter to Phase 3. What we do *not* do is claim "point it at your own agent"
while only our own hand-shaped JSONL loads.

## Phase 3 — Harden for public launch

> Sharpened to PR granularity in the Phase 3 planning conversation (2026-07-13),
> once Phase 2's exit was met. **The launch-claim fork is resolved: framing C —
> the tier-gap ("could, but didn't") is the hero; realized-trifecta-in-the-wild
> is NOT claimed; no injection-capture attempt** (operator decision; the honest
> weaker claim, chosen deliberately). Recorded as **D10** in `DECISIONS.md`,
> landing in the 3.1 PR. Plan: `~/.claude/plans/sorted-knitting-corbato.md`.

**Fork-gated (framing C):**

- [ ] **3.1 README + honesty/limitations section.** Rewrite the Phase-0 stub to
  the launch README under framing C: headline the reachable-vs-realized "could,
  but didn't" gap on real artifacts; realized-trifecta-in-the-wild not claimed.
  Carry the three-tier defs, the four honest gaps (`ROADMAP.md`: RAG/LLM ingest
  not built, realized anchor is direct-instruction not injection, action-hijack
  catalogued but unaccepted, verbatim-only), and `worked_example` labeled
  hand-authored. Append D10 to `DECISIONS.md`. *Done when the honesty gate scans
  the rendered README and the banned-token / no-overclaim checks pass on it.*
- [ ] **3.2 — DROPPED.** No injection-capture attempt (operator declined the
  spend). Recorded so the decision is legible, not silently skipped.

**Fork-independent:**

- [x] **3.3 Freeze the findings NDJSON schema as a public contract.** Document the
  realized and capability line shapes as a **versioned** schema; a test fails if a
  field is added/removed/renamed without a version bump. **Spec-first:** SPEC.md
  §7.1. — `SCHEMA_VERSION = "1.0"` rides **in-band** on every line (the
  append-stream has no header, so a consumer parsing one line must know its
  contract). `schema/findings.schema.json` is the machine-readable contract;
  `tests/test_findings_schema.py` pins three things together — the emitted keys
  (frozen key sets), the schema file (must declare exactly those keys), and every
  golden line (validated against the published schema by a zero-dependency stdlib
  checker, so no `jsonschema` dep is added and the one-screen dep tree stays a
  feature). Compatibility policy documented: additive ⇒ minor bump + ignore
  unknown fields; removal/rename/retype ⇒ major bump. Goldens regenerated (the
  one added `schema_version` field, visible in the diff).
- [x] **3.4 Primary-source-verify the documented-incident citations.** No
  citations existed in the repo, so this **establishes** the verified set. —
  `INCIDENTS.md` holds two A-tier, primary-source-verified incidents plus the
  concept source, deliberately small (honesty over volume): **EchoLeak**
  (CVE-2025-32711; Aim Labs research + the NVD CVE record) and the **GitHub MCP**
  private-repo exfiltration (Invariant Labs). Each was checked against its
  **primary** source (not a news summary), carries a `Verified: 2026-07-13` date,
  and states in its own words **what trifecta-lens would and would not see** — the
  scope caveat travels *with* the motivation. The GitHub MCP case is the closest
  public analogue to our target (a real MCP agent; PR-to-public-repo is a
  `sink:exfil` write in the default catalog), while EchoLeak's exfil rode a
  **rendered** channel that v1's verbatim realized tier does not detect — stated,
  not buried. `tests/test_incidents.py` makes "every incident cites a primary
  source + a verification date" executable, so no motivating incident can be added
  without the verification. Consumed by 3.1. `make check` green (231 tests).
- [x] **3.5 `CONTRIBUTING.md` — the catalog-entry flywheel.** Frame "add a catalog
  entry" as the contribution path (2.13 proved a stranger's server is covered by
  editing data, not code). — The guide now walks the path end to end: an unknown
  stack (a CRM + an internal wiki) is invisible under the defaults, one **complete,
  copy-pasteable overlay file** makes the *unmodified* engine detect the trifecta on
  it, and the finding cites the entry id so a reader who disagrees knows what to
  edit. Plus an upstream-PR checklist whose load-bearing item is the **benign**
  fixture ("the more valuable of the two: it is what proves the entry is not simply
  louder than the truth") and a provenance note stating captured vs hand-authored.
  **The doc is executed, not merely written:** `tests/test_contributing.py` parses
  every YAML block in it with the **real** `parse_catalog`, runs the documented
  overlay through the **real** labeling function (unknown stack → silent; + overlay →
  `sensitive_data` + `sink:exfil`, contributor's note winning the citation), asserts
  the `[catalog: …]` id it shows is a real shipped entry **rendered in that exact
  shape** by the real report, checks every repo path it links to exists, and runs the
  0.8 banned-token gate over the prose — because a contribution guide teaches every
  future entry's `note`, and a `note` **is** report text. A doc that fails on a
  stranger's first copy-paste is worse than no doc; now it cannot rot without CI
  going red.
- [x] **3.6 `pipx` / `uvx` install path.** Package so a stranger runs it on their
  own agent in ~60s (the exit). *Done when the console-script installs and runs
  from a clean environment.* — **The blocker was not packaging, it was the missing
  input.** `demo/capture_inventory.py` is hard-wired to *our* three reference
  servers: right for the fixture's provenance, useless to a stranger, so "point it
  at your own agent" was still half aspirational. Added **`trifecta-capture`** — a
  second console script in its own top-level package (`trifecta_capture/`, shipped
  under the `capture` extra), which reads the user's **own** MCP host config
  (`.mcp.json` / `claude_desktop_config.json` — launch config, the only thing that
  file holds, D2/F1), launches each server over stdio, records `tools/list`
  verbatim and writes the inventory. It lives outside `trifecta_lens/` **by design**:
  it must speak a transport, which core may never do, and the gates scan core — so
  invariant 1 stays structural, exactly as `demo/` established. The analyzer keeps
  its one runtime dependency; the SDK rides only on the extra, imported lazily, and
  the script installs either way and prints how to get it. **Provenance is not
  fabricated:** the operator's `--note` is carried in their voice, and with no note
  the artifact *says a note is missing* rather than describing a context the machine
  cannot know. With no `--context` declared, the whole config is one context — honest,
  and the collapse case, which the CLI warns about and the finding discloses (D1).
  **Done-when, executable:** `make install-check` builds the wheel, installs it into
  a **clean venv with no dev deps**, and runs it from **outside the repo** — `uv run`
  has the source tree on the path and can never catch a packaging break. It does not
  stop at `--version`: the catalog is package **data**, so a wheel that imports and
  versions perfectly can still ship blind. The check demands a real finding *with its
  catalog citation* out of the installed package — verified by deleting the catalog
  from the installed venv and watching the run fail. Wired into CI. `tests/test_capture.py`
  pins the pure half (config → contexts → inventory) and round-trips the artifact
  **through the analyzer's own loader**, so the two packages cannot drift apart on the
  file format. That round-trip also caught a real one: a "read-only" triage context
  holding the GitHub server is **not** sink-free — `create_comment` is a `sink:exfil`
  (the `INCIDENTS.md` GitHub-MCP shape), and the tier said so.
- [x] **3.7 Benign-fixture suite — low-false-positive evidence.** Extend the
  benign corpus so "low FP noise" is a **measured** claim (extends 2.1's threshold
  curve and the load-bearing-silence triage fixtures), not an assertion. — Added
  four hand-authored benign fixtures, each silent for a **distinct, named,
  load-bearing** reason: `benign_redacted_secret` (redaction != verbatim),
  `benign_secret_to_nonsink` (the value flows verbatim to a tool that carries no
  sink role — proves the *sink label* is load-bearing, not just the match),
  `benign_lookalike_not_the_secret` (a different high-entropy token at the sink),
  `benign_source_echo_no_secret` (source→sink with no sensitive leg — the family
  boundary, stated honestly). `tests/test_benign_corpus.py` makes the claim a
  number — **8 benign traces, 0 realized false positives at the shipped config** —
  and per-mechanism tests assert the legs that *would* fire are present, so each
  silence can only come from the guard it exercises. Provenance added; goldens
  regenerated (all empty). This complements 2.1's "why the threshold is 8" with
  "how broadly the detector stays quiet." `make check` green (227 tests).

**Suggested order:** 3.3 (done), 3.4 + 3.7 (evidence, longest lead), then
3.5 / 3.6 (packaging), then 3.1 (README) last so it can cite the frozen schema
and verified citations.

- **Exit:** a stranger installs and runs it on their own agent in ~60s. Launch.

## Phase 4 — Fast-follow: action hijack + CI  *(provisional)*

- Action-hijack family (`sink:impact`), **posture + reachable only**; realized
  held back with an explicit "causation not established" note.
- SARIF output + a GitHub Action so findings land in code-scanning.
- **Exit:** action-hijack posture/reachable findings + SARIF in a CI run.

## North star — parked

Not tasks. Transformed taint, cross-agent multi-hop, memory-poisoning,
cross-session state; streaming/live mode and action-hook consumers (see
`ROADMAP.md` north star — outbound calls from core are permanently forbidden).
Direction only; never represented as shipped (`SPEC.md` §8).
