"""The composability join: do the trace and the inventory describe ONE system?

``realized ⊆ reachable ⊆ posture`` is the guarantee the whole tier design rests on
(``SPEC.md`` §5, ``DESIGN.md`` §3: *"tier honesty becomes a structural property of the
machine, not editorial discipline"*). It holds **by construction** — but only for two
artifacts that share a tool name space. The tiers do not know that: realized labels the
events of the trace, the capability tiers label the tools of the inventory, and the two
never meet. Hand the tool a trace and an inventory that name the same tools differently
and each tier is *individually* correct while the report as a whole is nonsense.

**And it did exactly that.** A non-MCP agent whose trace carries bare names (``fetch``)
and whose hand-written inventory carries qualified ones (``local__fetch``) produced:

    [REALIZED]   exfil_trifecta            (all three legs)
    [REACHABLE]  sensitive_to_exfil_sink   (two-leg — NOT the trifecta)

A realized trifecta that the reachable tier says cannot be wired. Containment violated,
silently, in the one place the project claims it is structural.

``DECISIONS.md`` D8 calls the join *"a fixture assertion — an executable test, not a
hope"*, and it is: ``tests/test_inventory.py`` pins it for **our** artifacts. Nothing
pinned it for the **user's**. So this module computes it at runtime and the report
discloses it, because a guarantee that holds only for inputs we happened to author is
not a guarantee — it is a coincidence.

We **disclose**; we do not repair. Renaming a user's tools to force a join would be us
inventing a topology (D2's line: we record the effective set, never the cause of it),
and guessing that ``fetch`` and ``local__fetch`` are the same tool is exactly the kind
of helpful guess that puts a tool in a finding that no artifact named.

Pure, Stage 2: it compares identities for equality and never parses one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from trifecta_lens.model import Event, LabeledStack


@dataclass(frozen=True)
class Join:
    """How the trace's tool names line up with the inventory's.

    D8: the trace's tool names must be a **subset** of the inventory's — a run can only
    call a tool the agent is exposed to. When they are not, one of two things is true
    and we cannot tell which: the inventory is incomplete, or the two artifacts are
    written in different name spaces. Either way the tiers are no longer talking about
    one system.
    """

    called: tuple[str, ...]
    exposed: tuple[str, ...]
    #: Tools the trace called that the inventory does not list. Empty ⇒ the join holds.
    unlisted: tuple[str, ...]

    @property
    def applicable(self) -> bool:
        """Both artifacts were given, and the trace actually called something."""
        return bool(self.called) and bool(self.exposed)

    @property
    def holds(self) -> bool:
        """Trace ⊆ inventory: the two artifacts describe one system (D8)."""
        return self.applicable and not self.unlisted

    @property
    def disjoint(self) -> bool:
        """They share NO tool identity at all — the loudest possible signal.

        Almost always a name-space mismatch rather than two unrelated systems: a bare
        ``fetch`` in the trace against a qualified ``local__fetch`` in the inventory. It
        is still fatal to the comparison, and it is the case a non-MCP user hits first.
        """
        return self.applicable and not (set(self.called) & set(self.exposed))


def composability_join(events: Sequence[Event], stack: LabeledStack) -> Join:
    """Compare the tools the trace CALLED with the tools the inventory EXPOSES."""
    called = {event.tool for event in events if event.tool is not None}
    exposed = {tool.name for context in stack.contexts for tool in context.tools}
    return Join(
        called=tuple(sorted(called)),
        exposed=tuple(sorted(exposed)),
        unlisted=tuple(sorted(called - exposed)),
    )
