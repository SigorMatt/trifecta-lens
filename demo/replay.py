"""demo/replay.py — replay the frozen realized-positive trace (task 1.2 done-when).

Loads a committed trace fixture through the *core* loader
(:func:`trifecta_lens.loader.load_trace`) and prints the observed tool flow.
Replay-only: NO model call, NO network, NO provider/SDK import — the single
import from the analyzer is the loader, which reads local files only (CLAUDE.md
invariant 1). Output is deterministic: the same input file yields byte-identical
stdout every run (events are printed in the loader's sorted order; no clocks, no
timestamps in the output).

It prints the OBSERVED flow — what the loaded spans literally contain — with the
secret masked so the raw token never reaches stdout. It emits no finding and
claims no verdict of its own: the realized detector is what does that, and
`make demo` runs it immediately afterwards. This shows flow; it does not assert
a cause or a detection (CLAUDE.md invariants 3-5).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from trifecta_lens.loader import load_trace
from trifecta_lens.model import Event

DEFAULT_TRACE = "fixtures/demo_realized.jsonl"

_KIND_TOOL = "TOOL"
_VAULT = "vault"
_WEBHOOK = "webhook"


def _secret_values(events: list[Event]) -> list[str]:
    """The values to mask: the text output of every vault TOOL event.

    Derived from the trace itself — whatever the vault tool returned is treated
    as sensitive and masked wherever it later appears in a printed payload.
    """
    secrets: list[str] = []
    for event in events:
        if event.tool == _VAULT and event.outputs is not None:
            text = event.outputs.get("text")
            if isinstance(text, str) and text and text not in secrets:
                secrets.append(text)
    return secrets


def _mask_token(secret: str) -> str:
    """A masked stand-in revealing only a short prefix, never the full value."""
    return f"{secret[:8]}...MASKED"


def _mask(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, _mask_token(secret))
    return text


def _render_payload(payload: dict[str, Any] | None) -> str:
    """Render a loaded payload deterministically (sorted keys), before masking."""
    if payload is None:
        return "(none)"
    if set(payload.keys()) == {"text"}:
        return str(payload["text"])
    return json.dumps(payload, sort_keys=True)


def _secret_reaches_sink(events: list[Event], secrets: list[str]) -> bool:
    """Whether a vault value appears verbatim in a webhook input (observed).

    This reports what is literally present in the loaded spans — it is not a
    detector verdict and makes no causal claim.
    """
    for event in events:
        if event.tool == _WEBHOOK and event.inputs is not None:
            rendered = json.dumps(event.inputs, sort_keys=True)
            if any(secret in rendered for secret in secrets):
                return True
    return False


def format_replay(events: list[Event]) -> str:
    """Build the deterministic replay report for an ordered Event list."""
    secrets = _secret_values(events)
    lines: list[str] = [
        "demo replay — frozen realized-positive trace (no model call, no network)",
        "",
    ]
    for event in events:
        if event.action == _KIND_TOOL:
            lines.append(f"event {event.id}  TOOL  {event.tool or '?'}")
            lines.append(
                f"    input:  {_mask(_render_payload(event.inputs), secrets)}"
            )
            lines.append(
                f"    output: {_mask(_render_payload(event.outputs), secrets)}"
            )
        else:
            # Non-tool span (e.g. the AGENT root): name it for context only.
            lines.append(f"event {event.id}  {event.action}  {event.actor}")
    lines.append("")

    if _secret_reaches_sink(events, secrets):
        lines.append(
            "flow observed in trace: vault -> webhook "
            "(secret value present at sink, masked);"
        )
    else:
        lines.append(
            "flow observed in trace: no vault value observed at a sink;"
        )
    lines.append(
        "this replay prints only what the spans literally contain. The realized "
        "detector runs next (see the report below) — it, not this replay, is what "
        "emits a finding."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    trace_path = args[0] if args else DEFAULT_TRACE
    events = load_trace(trace_path)
    print(format_replay(events))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
