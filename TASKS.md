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
- [ ] **1.6 Realized detector.** Emit a finding when a tainted value reaches the
  sink, with the ordered path and masked value. Findings serialize as NDJSON —
  one finding per line, `sort_keys=True`, written as found (`DESIGN.md` §6).
  Output text is *"tainted data observed reaching <sink>"* — no causal/attack
  language (`CLAUDE.md` 4).
  *Done when the positive fixture yields one realized finding with the path and
  the benign yields none.*
- [ ] **1.7 Tiered human report** (realized only for the slice) with a tier
  badge. *Done when it prints the masked verdict.*
- [ ] **1.8 SVG renderer.** The red-edge path artifact (the screenshot).
  Hand-positioned layout; no graphviz (`DESIGN.md` §8).
  *Done when `make demo` writes the SVG.*
- [ ] **1.9 Benign fixture + tests + determinism.** A clean run that produces
  NO realized finding; pytest anchoring positive→realized and benign→none;
  re-run gives byte-identical findings. *Done when all green.*
  **(Phase 1 exit + first shareable: post the red-edge SVG + the
  `RECEIVED API_KEY=…` line.)**

---

## Phase 2 — Generalize to the engine  *(provisional — sharpen after 1.9)*

- Extract the role **catalog** (data file: `match → role + subtype + note`,
  `SPEC.md` §4); replace the 1.4 hardcoded labels with catalog lookup. The
  catalog is the engine's labeling function — the only tunable layer
  (`DESIGN.md` §4).
- Extract the **path engine** from the slice **as the fixed property automaton
  over labeled graphs** (`DESIGN.md` §§2–3, 5): leg-set lattice + register +
  guard; one engine, both families. Two-stage seam: construction (front-end)
  vs. engine; the engine never sees raw formats. **Binding constraints:** the
  engine consumes events as an incremental fold (never requires the complete
  trace); findings emit as an NDJSON append-stream (`DESIGN.md` §6).
- Implement **reachable** (tool I/O type-compat graph) and **posture** (roles
  present in manifest) as the guard-off / edges-off relaxations of the same
  machine, per `SPEC.md` §5.
- Ship the default v1 exfil catalog (common MCP servers + the source/sink lists
  in `SPEC.md` §4); support `--catalog` overlay.
- **Exit:** arbitrary manifest + trace → tiered findings; "point it at your own
  agent" works end-to-end.
- **Resolve from the slice first:** where tool I/O *schemas* live in a real MCP
  manifest (drives reachable); how much the Event shape must change for
  non-demo traces. Don't write 2.x PR tasks until these are known.

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
