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

#: The catalog writes ``role: sink`` + ``subtype: exfil|impact`` (SPEC.md §4); the
#: automaton reads the combined symbol. This is the one place the two spellings
#: meet.
_SINK: Final[str] = "sink"
_SINK_SUBTYPES: Final[dict[str, Role]] = {"exfil": SINK_EXFIL, "impact": SINK_IMPACT}
_PLAIN_ROLES: Final[frozenset[str]] = frozenset({UNTRUSTED_SOURCE, SENSITIVE_DATA})


def role_symbol(role: str, subtype: str | None) -> Role:
    """Resolve a catalog ``(role, subtype)`` pair to the symbol the automaton reads.

    Raises ``ValueError`` on anything outside the alphabet: an unknown role must
    never be silently dropped, because a dropped role is a missing leg, and a
    missing leg is a finding that quietly does not happen.
    """
    if role == _SINK:
        if subtype not in _SINK_SUBTYPES:
            raise ValueError(
                f"role 'sink' needs subtype {sorted(_SINK_SUBTYPES)}, got {subtype!r}"
            )
        return _SINK_SUBTYPES[subtype]
    if role in _PLAIN_ROLES:
        if subtype is not None:
            raise ValueError(f"role {role!r} takes no subtype, got {subtype!r}")
        return role
    raise ValueError(
        f"unknown role {role!r}: the alphabet is "
        f"{sorted(_PLAIN_ROLES)} + 'sink' (with a subtype)"
    )
