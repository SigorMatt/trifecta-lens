"""Labeling coverage: how much of the user's stack the catalog had an opinion about.

**Why this exists.** ``SPEC.md`` §6.1 requires the detector's bounds to ride on every
report, including the empty ones, because (D4) *"an undisclosed threshold silently
bounds what the realized tier can see, which makes 'no finding' un-auditable — the same
honesty failure as an overclaim, pointed the other way."* That was written about
``min_value_chars``. It applies with far more force to the **catalog**, which is the
largest bound on what the tool can find and was the one bound never disclosed: pointed
at a stack it had no entries for, trifecta-lens printed "no findings at this tier" and a
reader took it for a clean bill of health.

**What we may and may not say about an unmatched tool.** A tool that matches no catalog
entry carries no role, and a tool with no role is invisible to every tier. But "matched
nothing" has *two* causes and we cannot tell them apart:

* the catalog has never heard of it (``postgres__query`` — a real gap), and
* the catalog knows it and deliberately assigns it no role
  (``filesystem__list_directory`` returns *names*, not content; ``SPEC.md`` §4 says
  labeling it "would make every ``ls`` a leg of an exfil finding").

Both look identical here, and a real stack is *full* of the second kind. So this module
counts and names; it does **not** classify. Calling an unmatched tool "uncovered" would
overclaim a gap, and calling it "safe" would overclaim a clearance. We report the fact
we have — *these matched no entry, here they are, read the list* — which is
flow-not-causation (invariant 4) applied to labeling.

Pure, and seam-safe: it reads only *whether* a vertex's ``roles`` are empty, plus names
for display. No tool-name branching (``DESIGN.md`` §5, D6).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from trifecta_lens.model import Event, LabeledStack


@dataclass(frozen=True)
class Coverage:
    """Which tools the catalog had an opinion about, and which it did not.

    Over **distinct tools**, not occurrences: a tool exposed to three contexts, or
    called five times, is one tool the catalog did or did not recognise. Coverage is
    deliberately *not* per-context — an unmatched tool is one we have no opinion about
    **anywhere**, so slicing it by context would repeat the same names without adding a
    fact (real stacks share servers across contexts).
    """

    matched: tuple[str, ...]
    unmatched: tuple[str, ...]

    @property
    def total(self) -> int:
        return len(self.matched) + len(self.unmatched)

    @property
    def nothing_matched(self) -> bool:
        """No tool in the whole input carried a role.

        The dangerous case, and qualitatively different from partial coverage: every
        tier is silent because the catalog recognised **nothing** — not because the
        stack is clean. Such a tier has not run; it has been starved.
        """
        return self.total > 0 and not self.matched

    @property
    def complete(self) -> bool:
        """Every tool matched an entry — the only case where silence is a result."""
        return self.total > 0 and not self.unmatched


def _coverage(labeled: Iterable[tuple[str, bool]]) -> Coverage:
    """Distinct tool names, split by whether the catalog gave them a role.

    The catalog is deterministic (``SPEC.md`` §4: first match wins, in file order), so
    every occurrence of a name is labeled identically and deduplicating is lossless.
    """
    by_name = dict(labeled)
    return Coverage(
        matched=tuple(sorted(n for n, has_role in by_name.items() if has_role)),
        unmatched=tuple(sorted(n for n, has_role in by_name.items() if not has_role)),
    )


def inventory_coverage(stack: LabeledStack) -> Coverage:
    """Which of the stack's exposed tools the catalog had an opinion about."""
    return _coverage(
        (tool.name, bool(tool.roles))
        for context in stack.contexts
        for tool in context.tools
    )


def trace_coverage(events: Sequence[Event]) -> Coverage:
    """Which of the tools the trace actually *called* the catalog had an opinion about.

    Spans naming no tool are skipped, not counted as unmatched: an LLM or agent span is
    not a tool we failed to recognise, it is a span carrying no tool identity at all.
    (That such spans contribute no roles *at all* is a separate and larger limit —
    ``SPEC.md`` §7.3.)
    """
    return _coverage(
        (event.tool, bool(event.roles))
        for event in events
        if event.tool is not None
    )
