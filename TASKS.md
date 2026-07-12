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

- [ ] **2.1 Containment + disclosed extraction config** (D3 + D4; resolves
  `OPEN_QUESTIONS.md` §§1–2). **Spec-first:** reconcile `SPEC.md` §6 ("Match =
  exact"), `SPEC.md` §5 step 3 ("appears in") and `DESIGN.md` §8 ("substring") to
  **one** wording — containment of the untransformed value. Promote
  `MIN_VALUE_CHARS` into a declared extraction config, disclosed per-finding as
  `detected_under` and in the report footer. Fixed, **not** user-tunable (invariant
  2: the catalog stays the only knob). *Done when: the three passages agree; every
  finding carries `detected_under`; and the constant ships with a **measured**
  false-positive justification against the benign corpus — a number, not an
  assertion.*
- [ ] **2.2 `path_basis` labelling** (D5; resolves `OPEN_QUESTIONS.md` §3).
  **Spec-first:** `SPEC.md` §5, `DESIGN.md` §1. Each path edge carries its basis
  (`causal` from real `parent_id` ancestry, `temporal` from ordering alone); the
  finding carries a **required** `path_basis` field (`causal`|`temporal`|`mixed`);
  the SVG annotates the edge. *Done when: the anchor's finding reads
  `path_basis: temporal` (correctly — its tool spans are siblings under the root);
  a fixture with a real parent chain reads `causal`; and the SVG edge is labelled.
  **Blocks any public artifact.***
- [ ] **2.3 Harden the architecture gate to the stage seam** (D6; resolves
  `OPEN_QUESTIONS.md` §4). The 0.8 gate learns `DESIGN.md` §5: tool-name-keyed data
  is legal in **Stage 1** (loader, inventory front-end, catalog/labeling), illegal
  in **Stage 2** (engine, findings, report, svg). *Done when the gate fails on a
  per-tool dict table planted in `engine.py` and passes on the same table in
  `labeling.py`.*

### Track B — the real-MCP capture *(the root dependency)*

- [ ] **2.4 Rebuild the demo as a real MCP client** (D8). MCP SDK over stdio
  against **real reference servers**, with real OpenInference instrumentation and
  OTLP export. Lives in `demo/`, outside core, so its transport/exec use never
  trips the 0.4 gate. **Bounded to minimum-viable:** the smallest real setup that
  can yield a multi-context inventory and a namespace-matching trace; servers
  chosen for **realness + ease, not scenario drama**; **inert fail-closed sink, no
  real credentials**; direct-instruction is fine (no live exploit required —
  Checkpoint B precedent). *Done when a live run against real MCP servers emits
  payload-level OTLP spans.*
- [ ] **2.5 Inventory capture script** (D2). Outside core (`contrib/` or `demo/`).
  Speaks `tools/list` to each configured server and writes the inventory JSON:
  `contexts[]`, each with an id, its **effective** tool set, and a **human-written**
  provenance note. *Done when it produces a well-formed inventory from a running
  server set.*
- [ ] 🛑 **CHECKPOINT D — human capture (halt).** A human runs 2.4 + 2.5 and
  commits: the **inventory fixture** (≥2 contexts), the **real OTLP trace fixture**,
  and provenance for both. **The build agent must never fabricate either artifact**
  — same line as Checkpoint B. *Exit: both fixtures committed, with provenance
  stating exactly what was captured and what it may be used to claim.*
- [ ] **2.6 Inventory loader + the composability join** (D2, D8). Stage 1
  front-end: inventory JSON → labeled topology values. **Spec-first:** correct
  `SPEC.md` §7 — the manifest does **not** contain tools (D2/F1). *Done when the
  captured inventory loads, **and** a fixture assertion proves the trace's tool
  names match the inventory's tool names — the join that makes "the three tiers
  describe one system" checkable rather than hoped-for.*
- [ ] **2.7 Real OTLP / OpenInference front-end** (D9). A new Stage 1 adapter —
  never an engine change (`FIXTURES.md`). Built against the **real captured trace**,
  not an imagined one. Handles nested OTLP attribute arrays, MCP tool
  **namespacing** (server-qualified tool identity — an `Event` shape change, so:
  spec-first on `SPEC.md` §2), and the richer keys real traces carry
  (`retrieval.documents.*` → RAG reads as `untrusted_source`; LLM message
  payloads). *Done when the real captured trace loads to the expected Event stream
  and the existing realized detector runs on it unchanged.*

### Track C — the engine and the two new tiers *(gated on Checkpoint D)*

- [ ] **2.8 Extract the catalog** (`SPEC.md` §4). The 1.4 `# TEMP` table becomes a
  data file (`match → role + subtype + note`) plus a `--catalog` overlay. The
  catalog is the labeling function and **the only tunable layer** (`DESIGN.md` §4).
  *Done when the Phase-1 fixtures produce byte-identical findings with the labels
  served from the catalog instead of the hardcoded table.*
- [ ] **2.9 Extract the engine** as the fixed property automaton over labeled
  graphs (`DESIGN.md` §§2–3, 5). Two-stage seam enforced: the engine sees labeled
  graphs only — never JSONL, OpenInference keys, or the inventory format. **Binding:**
  incremental fold; NDJSON append-stream (`DESIGN.md` §6). *Done when all Phase-1
  findings are unchanged and the engine module imports no front-end.*
- [ ] **2.10 Posture tier** (D1). Roles present in the **union** of the inventory's
  contexts; no edges, no guard. *Done when the captured inventory yields posture
  findings, and `realized ⊆ posture` is an executable property test.*
- [ ] **2.11 Reachable tier + collapse disclosure + non-vacuity** (D1, D7).
  Reachable = all legs co-exposed in **one context**; the same machine with edges on
  and the guard off. **Must detect and disclose the collapse case**
  (`reachable == posture` ⇒ say "reachable adds no information on this stack: all
  legs share one context"). *Done when: the real captured inventory demonstrates
  `reachable ⊊ posture` (**non-vacuity**); a single-context inventory triggers the
  collapse disclosure; and `realized ⊆ reachable ⊆ posture` is an executable
  property test.* **🛑 If non-vacuity fails on the real inventory, HALT** — do not
  weaken the tier to make it pass; take D7's constructed fallback, which is itself
  held to "instantiates a **documented in-the-wild topology**", not "discriminates".
- [ ] **2.12 Tiered output across all three tiers.** Report, SVG and findings NDJSON
  carry tier + family + `path_basis` + `detected_under`. Tier honesty holds in the
  **text**, not just the logic (`CLAUDE.md` 3). *Done when a single run over
  inventory + trace emits all three tiers, each correctly badged, and the honesty
  gate scans the rendered output for all of them.*
- [ ] **2.13 Default v1 exfil catalog + docs.** Catalog entries for the servers the
  capture actually used, plus the source/sink lists in `SPEC.md` §4.
  `CONTRIBUTING.md` frames "add a catalog entry" as the contribution path.
  *Done when a stranger's server can be covered by editing data, not code.*

**Exit:** a real MCP stack's inventory + a real trace → all three tiers, honestly
tiered and disclosed; "point it at your own agent" is **true**, not aspirational.

**Honest fallback (D9), retained:** if 2.7 overruns, reword the exit and defer the
OTLP adapter to Phase 3. What we do *not* do is claim "point it at your own agent"
while only our own hand-shaped JSONL loads.

## Phase 3 — Harden for public  *(provisional)*

- README with the documented-incident citations + the honesty/limitations
  section; `CONTRIBUTING.md` framing a catalog entry as the contribution path.
- Swappable-payload docs; `pipx`/`uvx` install; **freeze the findings NDJSON
  schema** as a public contract; benign-fixture suite proving low FP noise.
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
