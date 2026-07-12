"""The role catalog: the labeling function, as data (SPEC.md §4, DESIGN.md §4).

Stage 1. This module and the YAML it reads are **the only tunable layer of
detection**. The automaton (Stage 2) is fixed and closed; a user extends coverage
to their own stack by adding a catalog entry — never by editing the engine
(``CLAUDE.md`` invariant 2, enforced by the stage-seam gate in ``tests/test_gates.py``).

Matching is a fully-anchored regex against the event's tool name. Under MCP that
name is server-qualified (``<server>__<tool>``, SPEC.md §2), which is what lets one
catalog cover both the flat Phase 1 fixtures and a real MCP trace. A tool matching
several entries takes the **union** of their roles; the note cited for a role is
the first matching entry's, in file order — so labeling is deterministic.

Reads a local file only, never a network connection (``CLAUDE.md`` invariant 1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, Final

import yaml

from trifecta_lens.model import RoleLabel
from trifecta_lens.roles import Role, role_symbol

#: The shipped default catalog (SPEC.md §4).
DEFAULT_CATALOG: Final[str] = "exfil_v1.yaml"


class InvalidCatalogError(ValueError):
    """The catalog file violates the contract — fail loudly, don't guess.

    A mislabeled stack is worse than an unlabeled one: it produces confident
    findings about roles nobody assigned. So a malformed entry is an error, never
    a silently-skipped line.
    """


@dataclass(frozen=True)
class CatalogEntry:
    """One labeling rule: *this* pattern of tool carries *that* role, because…"""

    id: str
    #: Fully-anchored regex over the tool name (``re.fullmatch``).
    pattern: str
    #: The resolved role symbol the automaton reads (e.g. ``sink:exfil``).
    role: Role
    #: The human rationale, cited in every finding that uses this entry.
    note: str

    def matches(self, tool: str) -> bool:
        return re.fullmatch(self.pattern, tool) is not None


@dataclass(frozen=True)
class Catalog:
    """An ordered set of entries. Order decides which note a role cites."""

    entries: tuple[CatalogEntry, ...]

    def label(self, tool: str | None) -> dict[Role, RoleLabel]:
        """Roles for ``tool``, each mapped to the entry that assigned it.

        The union over matching entries; first match wins the citation. An unmatched
        tool gets nothing — silence, not a guess.
        """
        if tool is None:
            return {}
        labels: dict[Role, RoleLabel] = {}
        for entry in self.entries:
            if entry.matches(tool) and entry.role not in labels:
                labels[entry.role] = RoleLabel(entry=entry.id, note=entry.note)
        return labels

    def overlaid_with(self, overlay: Catalog) -> Catalog:
        """A user overlay, consulted **before** these entries (SPEC.md §4).

        The overlay can add roles the defaults miss and win the note for a role it
        shares. It cannot remove a default entry in v1 — an overlay that silently
        deleted coverage would be a way to make a finding disappear without saying
        so.
        """
        return Catalog(entries=overlay.entries + self.entries)


def _entry(raw: Any, index: int, source: str) -> CatalogEntry:
    where = f"{source}: entry {index}"
    if not isinstance(raw, dict):
        raise InvalidCatalogError(f"{where} is not a mapping")

    entry_id = raw.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        raise InvalidCatalogError(f"{where} is missing a string 'id'")

    match = raw.get("match")
    if not isinstance(match, dict):
        raise InvalidCatalogError(f"{where} ({entry_id}) is missing a 'match' mapping")
    if "tag" in match:
        raise InvalidCatalogError(
            f"{where} ({entry_id}) uses 'tag' matching, which is NOT implemented "
            "in v1 — the captured inventory carries no tags (SPEC.md §4). Match on "
            "'tool' instead."
        )
    pattern = match.get("tool")
    if not isinstance(pattern, str) or not pattern:
        raise InvalidCatalogError(f"{where} ({entry_id}) needs a string 'match.tool'")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise InvalidCatalogError(
            f"{where} ({entry_id}): 'match.tool' is not a valid regex: {exc}"
        ) from exc

    note = raw.get("note")
    if not isinstance(note, str) or not note:
        raise InvalidCatalogError(
            f"{where} ({entry_id}) is missing a 'note' — the human rationale is "
            "not optional: every finding cites it so a user can correct the call."
        )

    role = raw.get("role")
    subtype = raw.get("subtype")
    if not isinstance(role, str):
        raise InvalidCatalogError(f"{where} ({entry_id}) is missing a string 'role'")
    if subtype is not None and not isinstance(subtype, str):
        raise InvalidCatalogError(f"{where} ({entry_id}): 'subtype' must be a string")
    try:
        symbol = role_symbol(role, subtype)
    except ValueError as exc:
        raise InvalidCatalogError(f"{where} ({entry_id}): {exc}") from exc

    return CatalogEntry(id=entry_id, pattern=pattern, role=symbol, note=note)


def parse_catalog(text: str, source: str) -> Catalog:
    """Parse catalog YAML. Pure — takes text, not a path."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InvalidCatalogError(f"{source}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise InvalidCatalogError(f"{source}: must be a mapping with an 'entries' list")

    entries = tuple(
        _entry(raw, i, source) for i, raw in enumerate(data["entries"])
    )
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            raise InvalidCatalogError(f"{source}: duplicate entry id {entry.id!r}")
        seen.add(entry.id)
    return Catalog(entries=entries)


def load_catalog(path: str | Path) -> Catalog:
    """Load a catalog YAML file (a user overlay, or the default by path)."""
    p = Path(path)
    return parse_catalog(p.read_text(encoding="utf-8"), source=str(p))


def default_catalog() -> Catalog:
    """The shipped v1 exfil catalog, loaded from package data."""
    resource = files("trifecta_lens.catalogs").joinpath(DEFAULT_CATALOG)
    with as_file(resource) as p:
        return load_catalog(p)
