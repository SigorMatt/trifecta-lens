"""The path SVG — the shareable artifact (SPEC.md §7, DESIGN.md §8).

Hand-positioned. No graphviz, no layout library: a system binary breaks
`uvx`-in-60s, and layout output drifts between versions, which would break the
determinism invariant. The paths are short linear chains — a row of boxes and an
arrow is the whole geometry, and arithmetic is enough.

This is the artifact most likely to be seen OUT of context — screenshotted,
pasted into a thread, stripped of the report around it. So it carries its own
honesty: the family, the legs that were NOT observed, the masked value, and the
same flow-not-causation summary. It must not be possible to mistake a two-leg
finding for a trifecta by looking at the picture.
"""

from collections.abc import Sequence
from typing import Final
from xml.sax.saxutils import escape

from trifecta_lens.engine import FAMILIES, FAMILY_TRIFECTA
from trifecta_lens.findings import BASIS_TEMPORAL, CapabilityFinding, Finding
from trifecta_lens.roles import SENSITIVE_DATA, SINK_EXFIL

# Geometry (px). Everything below is derived from these.
_MARGIN: Final[int] = 32
_NODE_W: Final[int] = 190
_NODE_H: Final[int] = 68
_GAP: Final[int] = 96
_NODE_Y: Final[int] = 132
_MIN_W: Final[int] = 720
_HEIGHT: Final[int] = 320
#: Extra height for the "also reachable" block, when there is one.
_ESCALATION_H: Final[int] = 74

_INK: Final[str] = "#1b1f24"
_MUTED: Final[str] = "#6a737d"
_EDGE: Final[str] = "#d1242f"  # the red edge: the observed flow
_PAPER: Final[str] = "#ffffff"

# Node fill by role. A muted default keeps an unlabeled node from shouting.
_FILL: Final[dict[str, str]] = {
    SENSITIVE_DATA: "#fff3cd",
    SINK_EXFIL: "#ffdce0",
}
_STROKE: Final[dict[str, str]] = {
    SENSITIVE_DATA: "#bf8700",
    SINK_EXFIL: "#d1242f",
}
_DEFAULT_FILL: Final[str] = "#eef1f4"
_DEFAULT_STROKE: Final[str] = "#8c959f"


def _text(
    x: int,
    y: int,
    content: str,
    size: int,
    fill: str,
    weight: str = "",
    anchor: str = "",
) -> str:
    bold = f' font-weight="{weight}"' if weight else ""
    align = f' text-anchor="{anchor}"' if anchor else ""
    return (
        f'<text x="{x}" y="{y}" font-family="ui-monospace,SFMono-Regular,Menlo,'
        f'monospace" font-size="{size}" fill="{fill}"{bold}{align}>'
        f"{escape(content)}</text>"
    )


def _node(x: int, event: str, tool: str | None, role: str) -> str:
    fill = _FILL.get(role, _DEFAULT_FILL)
    stroke = _STROKE.get(role, _DEFAULT_STROKE)
    return "".join(
        [
            f'<rect x="{x}" y="{_NODE_Y}" width="{_NODE_W}" height="{_NODE_H}" rx="8" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>',
            _text(x + 14, _NODE_Y + 26, f"{event}  {tool or '-'}", 15, _INK, "600"),
            _text(x + 14, _NODE_Y + 48, role, 12, _MUTED),
        ]
    )


def _family_rank(family: str) -> int:
    """Index in FAMILIES — lower is stronger. Unknown families rank weakest."""
    for i, candidate in enumerate(FAMILIES):
        if candidate.id == family:
            return i
    return len(FAMILIES)


def _stronger_reachable(
    finding: Finding, reachable: Sequence[CapabilityFinding]
) -> CapabilityFinding | None:
    """A reachable finding at a STRICTLY stronger family than what was realized.

    This is the gap that makes the tiers worth having, and the one thing a viewer of
    the picture alone would otherwise never learn: the run we captured wired the
    lesser family, but the very same agent context is exposed to everything the
    stronger one needs. Showing it is honest; showing it *as a red arrow* would not
    be, since nothing was observed. It goes in grey, below the path, labelled as
    not observed.
    """
    realized_rank = _family_rank(finding.family)
    stronger = [
        candidate
        for candidate in reachable
        if _family_rank(candidate.family) < realized_rank
        and candidate.sink_tool == finding.sink_tool
    ]
    # Deterministic pick: strongest family, then context id.
    stronger.sort(key=lambda c: (_family_rank(c.family), c.context))
    return stronger[0] if stronger else None


def render_svg(
    finding: Finding, reachable: Sequence[CapabilityFinding] = ()
) -> str:
    """Render one finding's path as a standalone SVG. Deterministic."""
    legs = finding.legs
    count = len(legs)
    width = max(_MIN_W, 2 * _MARGIN + count * _NODE_W + (count - 1) * _GAP)

    escalation = _stronger_reachable(finding, reachable)
    height = _HEIGHT + (_ESCALATION_H if escalation else 0)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(finding.summary)}">',
        f'<rect width="{width}" height="{height}" fill="{_PAPER}"/>',
        # The arrowhead marker: the edge has a direction — data moved this way.
        f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{_EDGE}"/></marker></defs>',
    ]

    # Header: tier badge, family, and — for the two-leg family — what it is NOT.
    badge = (
        "all three legs observed"
        if finding.family == FAMILY_TRIFECTA
        else "two-leg — NOT the trifecta"
    )
    title = f"[{finding.tier.upper()}]  {finding.family}"
    parts += [
        _text(_MARGIN, 44, title, 17, _INK, "700"),
        _text(_MARGIN, 68, f"({badge})", 13, _MUTED),
        _text(_MARGIN, 100, finding.summary, 15, _EDGE, "600"),
    ]

    # The path: one node per leg, a red edge between consecutive nodes.
    xs = [_MARGIN + i * (_NODE_W + _GAP) for i in range(count)]
    for x, leg in zip(xs, legs, strict=True):
        parts.append(_node(x, leg.event, leg.tool, leg.role))

    edge_y = _NODE_Y + _NODE_H // 2
    for i, x in enumerate(xs[:-1]):
        start, end = x + _NODE_W, x + _NODE_W + _GAP
        parts.append(
            f'<line x1="{start}" y1="{edge_y}" x2="{end}" y2="{edge_y}" '
            f'stroke="{_EDGE}" stroke-width="3" marker-end="url(#arrow)"/>'
        )
        # Centred in the gap so it never overruns the node it points at.
        mid = (start + end) // 2
        parts.append(_text(mid, edge_y - 26, "verbatim", 11, _EDGE, anchor="middle"))
        # The arrow's BASIS, on the arrow itself. An unlabelled arrow between two
        # boxes is read as causation, and this artifact travels without its
        # report (DECISIONS.md D5).
        basis = finding.path_edges[i].basis if i < len(finding.path_edges) else ""
        parts.append(_text(mid, edge_y - 12, basis, 11, _MUTED, anchor="middle"))

    # Footer: the masked value, and the legs that were NOT observed.
    footer_y = _NODE_Y + _NODE_H + 44
    parts.append(
        _text(_MARGIN, footer_y, f"value: {', '.join(finding.masked_values)}", 13, _INK)
    )
    if finding.legs_not_observed:
        missing = ", ".join(finding.legs_not_observed)
        parts.append(
            _text(_MARGIN, footer_y + 22, f"not observed: {missing}", 13, _MUTED)
        )
    # The disclaimer is the LAST thing that may ever be truncated: it is what
    # stops a screenshot of this arrow from reading as a causal claim. Wrapped
    # onto explicit lines rather than trusted to fit.
    if finding.path_basis == BASIS_TEMPORAL:
        disclaimer = (
            "verbatim taint; the steps were observed in this ORDER — the trace",
            "does not link them as parent/child. Flow observed, not causation.",
        )
    else:
        disclaimer = (
            "verbatim taint; the trace's own ancestry links these spans.",
            "Flow observed, not causation.",
        )
    for i, line in enumerate(disclaimer):
        parts.append(_text(_MARGIN, footer_y + 44 + i * 15, line, 11, _MUTED))

    # The tier gap, in grey and below the path — never on the red edge. The red
    # edge means "observed"; this was not observed, and the picture must not blur
    # the two even when the stronger claim is the more interesting one.
    if escalation is not None:
        y = footer_y + 88
        parts += [
            f'<line x1="{_MARGIN}" y1="{y - 14}" x2="{width - _MARGIN}" '
            f'y2="{y - 14}" stroke="{_DEFAULT_STROKE}" stroke-width="1" '
            f'stroke-dasharray="4 4"/>',
            _text(
                _MARGIN,
                y + 8,
                f"[REACHABLE, NOT OBSERVED]  {escalation.family}",
                13,
                _MUTED,
                "700",
            ),
            _text(
                _MARGIN,
                y + 28,
                f"agent context {escalation.context!r} is also exposed to the "
                "remaining leg, so a single run could",
                11,
                _MUTED,
            ),
            _text(
                _MARGIN,
                y + 43,
                "wire the stronger family. No run was observed doing so. "
                "Capability, not observation.",
                11,
                _MUTED,
            ),
        ]

    parts.append("</svg>")
    return "\n".join(parts) + "\n"
