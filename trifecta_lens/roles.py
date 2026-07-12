"""The role alphabet the labeling function emits (SPEC.md §4, DESIGN.md §2).

These are the only symbols the automaton reads. Vertices that carry no role
emit nothing and are absorbed by the machine's self-loops. A vertex may carry
several roles.

The automaton is fixed and closed; the *assignment* of these roles is the only
tunable layer (DESIGN.md §4) — hardcoded for the slice (see ``labeling.py``),
catalog-driven from Phase 2.
"""

from typing import Final, TypeAlias

Role: TypeAlias = str

UNTRUSTED_SOURCE: Final[Role] = "untrusted_source"
SENSITIVE_DATA: Final[Role] = "sensitive_data"
SINK_EXFIL: Final[Role] = "sink:exfil"
SINK_IMPACT: Final[Role] = "sink:impact"

#: Roles that put a value into the taint register (DESIGN.md §2: the register is
#: populated by extracting values at SRC- and SEN-labeled events).
TAINT_BEARING: Final[frozenset[Role]] = frozenset({UNTRUSTED_SOURCE, SENSITIVE_DATA})
