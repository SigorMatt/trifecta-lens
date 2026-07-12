"""Value extraction and verbatim taint matching (SPEC.md §6).

Pure and deterministic: same payloads in, same values out, in the same order.

**Scope, stated plainly.** v1 matches VERBATIM taint only. A value matches when
the value itself — untransformed — occurs in the sink's payload, after light
normalization (trim, case-fold, collapse whitespace). Encoded (base64/hex),
split/concatenated, summarized, and paraphrased values DO NOT match, by
construction. Realized therefore covers the verbatim subset only; this is a
known, stated limit, never papered over (CLAUDE.md invariant 5).
"""

from typing import Any, Final

from trifecta_lens.model import Event, Value
from trifecta_lens.roles import TAINT_BEARING

#: Extraction parameter (DESIGN.md §4): values shorter than this are not tracked
#: — a 3-character string would collide with ordinary payload text and produce
#: noise, not evidence. Disclosed in the finding's ``scope`` note so a reader
#: knows what was and was not tracked.
MIN_VALUE_CHARS: Final[int] = 8

_MASK_PREFIX_CHARS: Final[int] = 8


def normalize(text: str) -> str:
    """Light normalization only: trim, case-fold, collapse whitespace."""
    return " ".join(text.split()).casefold()


def _string_leaves(payload: dict[str, Any] | None) -> list[str]:
    """Every string in a payload, in deterministic (sorted-key) order.

    Payloads are shallow (a parsed tool-call argument dict, or ``{"text": ...}``
    for text/plain), but nested containers are walked so a nested tool argument
    is never silently skipped.
    """
    if payload is None:
        return []

    leaves: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            leaves.append(node)
        elif isinstance(node, dict):
            for key in sorted(node, key=str):
                walk(node[key])
        elif isinstance(node, list | tuple):
            for item in node:
                walk(item)

    walk(payload)
    return leaves


def extract_values(event: Event) -> list[Value]:
    """The taint-bearing values an event puts into the register (DESIGN.md §2).

    Values are extracted from the OUTPUTS of events labeled ``untrusted_source``
    or ``sensitive_data`` — that is the data the tool handed back to the agent.
    An event with neither role contributes nothing, so a sink never taints
    itself. v1 takes whole payload strings (SPEC.md §6: "whole tool outputs").

    Duplicates are collapsed, first occurrence wins, so the order is stable.
    """
    if not (event.roles & TAINT_BEARING):
        return []

    values: list[Value] = []
    for leaf in _string_leaves(event.outputs):
        if len(leaf.strip()) < MIN_VALUE_CHARS:
            continue
        if leaf not in values:
            values.append(leaf)
    return values


def value_in_payload(value: Value, payload: dict[str, Any] | None) -> bool:
    """Whether ``value`` occurs VERBATIM in ``payload`` (SPEC.md §5 step 3).

    Containment, not whole-field equality: a secret pasted into a larger request
    body has still reached the sink verbatim. What "verbatim" excludes is
    *transformation* of the value (SPEC.md §6) — never the surrounding text.
    """
    needle = normalize(value)
    if len(needle) < MIN_VALUE_CHARS:
        return False
    return any(needle in normalize(leaf) for leaf in _string_leaves(payload))


def mask(value: Value) -> str:
    """A masked stand-in: a short prefix only, never the value itself.

    Findings and reports carry this, never the raw value — the analyzer must not
    become the thing that prints your secret to a terminal.
    """
    return f"{value[:_MASK_PREFIX_CHARS]}...MASKED"
