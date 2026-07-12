"""The labeling function L(vertex) -> roles (DESIGN.md §2, SPEC.md §4).

# TEMP: catalog in P2. This module is the Phase-1 slice's stand-in for the role
# catalog. It is a DATA MAPPING, deliberately: coverage lives in the table, not
# in code paths. Phase 2 replaces the table with a catalog file (and a
# ``--catalog`` overlay) and this module keeps the same shape and signature —
# the detector never learns a tool name either way (CLAUDE.md invariant 2).

Nothing downstream of here knows what a "vault" or a "webhook" is; the engine
sees roles only.
"""

from dataclasses import replace

from trifecta_lens.model import Event
from trifecta_lens.roles import SENSITIVE_DATA, SINK_EXFIL, Role

# TEMP: catalog in P2 — the slice's labeling table.
#
# Only the two tools the realized anchor actually exercises are mapped. Note
# what is NOT here: nothing in the anchor is an untrusted_source. The anchor is
# a direct-instruction run — the root span is the principal's own prompt, and a
# principal's instruction is not ingested untrusted content. Labeling it (or the
# vault's own secret read) as a source purely to make the trifecta accept would
# destroy family honesty (SPEC.md §3) and make every secret read
# trifecta-positive.
_SLICE_LABELS: dict[str, frozenset[Role]] = {
    "vault": frozenset({SENSITIVE_DATA}),
    "webhook": frozenset({SINK_EXFIL}),
}

#: Human rationale for each assignment, cited in findings so a user can see and
#: correct the labeling (SPEC.md §4). Phase 2: this becomes the catalog entry's
#: ``note`` field.
_SLICE_NOTES: dict[Role, str] = {
    SENSITIVE_DATA: "reads a credential from the secret store",
    SINK_EXFIL: "sends a payload to an outbound HTTP endpoint",
}


def roles_for_tool(tool: str | None) -> set[Role]:
    """Roles assigned to ``tool``. A lookup — an unmapped tool gets none."""
    if tool is None:
        return set()
    return set(_SLICE_LABELS.get(tool, frozenset()))


def note_for_role(role: Role) -> str:
    """The human rationale cited in a finding for why ``role`` was assigned."""
    return _SLICE_NOTES.get(role, "")


def label_events(events: list[Event]) -> list[Event]:
    """Attach roles to each event. Order and payloads are preserved exactly."""
    return [replace(event, roles=roles_for_tool(event.tool)) for event in events]
