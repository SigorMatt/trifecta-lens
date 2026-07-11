# trifecta-lens

A **read-only** analyzer that detects lethal-trifecta / data-exfil exposure in
MCP-based agent systems. It consumes a captured execution **trace**
(OTel / OpenInference spans) and the agent's **MCP manifest**, and reports
findings across three honesty tiers — **realized** / **reachable** /
**posture**.

It is not a firewall, not an enforcement layer, and not a runtime — it never
sits in the request path, never executes a tool, and never opens a network
connection. Findings are written to stdout/files only.

## Status

Early development (Phase 0 — skeleton & contract). Not yet usable.

## Scope honesty

v1 realized detection covers **verbatim** taint only (exact match after light
normalization). Transformed taint (base64, splitting, paraphrase), cross-agent
multi-hop, and memory-poisoning are explicitly out of scope.

## Development

```
uv sync --extra dev
uv run ruff check .
uv run mypy trifecta_lens
uv run pytest
```

See `SPEC.md` (behavior), `CLAUDE.md` (invariants), `DESIGN.md` (engine
architecture), `TASKS.md` (checklist).
