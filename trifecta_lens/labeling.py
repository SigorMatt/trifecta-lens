"""The labeling function L(vertex) -> roles (DESIGN.md §2, SPEC.md §4).

Stage 1. Task 2.8 replaced the Phase-1 `# TEMP` table with the **catalog** — the
same shape and the same signature, but the coverage now lives in a data file
(`catalogs/exfil_v1.yaml`) that a user can extend or overlay. Nothing downstream
of here knows what a "vault" or a "notify__send" is; the engine sees roles only.

Labeling attaches two things to each event:

* ``roles`` — the alphabet the automaton reads.
* ``role_notes`` — role -> the catalog entry's rationale, so a finding can cite
  **why** a role was assigned without the engine ever learning a tool name
  (SPEC.md §2/§4). The engine reads this dict keyed by *role*, which is what keeps
  the stage seam intact.
"""

from dataclasses import replace

from trifecta_lens.catalog import Catalog, default_catalog
from trifecta_lens.model import Event
from trifecta_lens.roles import Role


def roles_for_tool(tool: str | None, catalog: Catalog) -> set[Role]:
    """Roles assigned to ``tool``. An unmatched tool gets none."""
    return set(catalog.label(tool))


def label_events(events: list[Event], catalog: Catalog | None = None) -> list[Event]:
    """Attach roles + their catalog rationale. Order and payloads are preserved."""
    active = default_catalog() if catalog is None else catalog
    labeled = []
    for event in events:
        notes = active.label(event.tool)
        labeled.append(replace(event, roles=set(notes), role_notes=notes))
    return labeled
