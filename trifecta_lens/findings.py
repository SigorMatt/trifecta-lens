"""The findings output contract (SPEC.md §7, DESIGN.md §6).

Findings are an **append-stream**: NDJSON, one finding object per line, keys
sorted, written the moment each one is found — never a monolithic end-of-run
document. That is what keeps a future streaming front-end additive rather than a
redesign, and it is why :func:`write_ndjson` takes an *iterator* and flushes per
line instead of taking a list.

Emission goes to a text stream — stdout or a file. Core never delivers a finding
over the network (`DESIGN.md` §7): that is permanently out, not merely parked.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Final, TextIO

from trifecta_lens.roles import Role

#: The only tier this slice emits. Kept explicit so a lower tier can never
#: silently inherit realized's language or weight (CLAUDE.md invariant 3).
TIER_REALIZED: Final[str] = "realized"


@dataclass(frozen=True)
class Leg:
    """One observed leg of a path, citing what assigned the role (SPEC.md §4)."""

    role: Role
    event: str
    tool: str | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "note": self.note,
            "role": self.role,
            "tool": self.tool,
        }


@dataclass(frozen=True)
class Finding:
    """One finding. Serializes to exactly one NDJSON line."""

    family: str
    tier: str
    summary: str
    sink_event: str
    sink_tool: str | None
    path: tuple[str, ...]
    legs: tuple[Leg, ...]
    legs_observed: tuple[Role, ...]
    legs_not_observed: tuple[Role, ...]
    masked_values: tuple[str, ...]
    note: str
    scope: str
    #: The declared extraction parameters that bounded this search (SPEC.md
    #: §6.1). Present on every finding so "what could this even have seen?" is
    #: answerable from the finding alone.
    detected_under: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected_under": dict(self.detected_under),
            "family": self.family,
            "legs": [leg.to_dict() for leg in self.legs],
            "legs_not_observed": list(self.legs_not_observed),
            "legs_observed": list(self.legs_observed),
            "masked_values": list(self.masked_values),
            "note": self.note,
            "path": list(self.path),
            "scope": self.scope,
            "sink": {"event": self.sink_event, "tool": self.sink_tool},
            "summary": self.summary,
            "tier": self.tier,
        }

    def to_json_line(self) -> str:
        """One NDJSON line. ``sort_keys=True`` is the determinism contract."""
        return json.dumps(self.to_dict(), sort_keys=True)


def write_ndjson(findings: Iterable[Finding], stream: TextIO) -> int:
    """Write findings as they are found. Returns how many were written.

    Consumes the iterator lazily and flushes each line, so a consumer piping the
    stream sees a finding at the moment the engine derives it.
    """
    written = 0
    iterator: Iterator[Finding] = iter(findings)
    for finding in iterator:
        stream.write(finding.to_json_line() + "\n")
        stream.flush()
        written += 1
    return written
