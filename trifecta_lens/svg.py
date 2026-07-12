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

from typing import Final
from xml.sax.saxutils import escape

from trifecta_lens.engine import FAMILY_TRIFECTA
from trifecta_lens.findings import Finding
from trifecta_lens.roles import SENSITIVE_DATA, SINK_EXFIL

# Geometry (px). Everything below is derived from these.
_MARGIN: Final[int] = 32
_NODE_W: Final[int] = 190
_NODE_H: Final[int] = 68
_GAP: Final[int] = 96
_NODE_Y: Final[int] = 132
_MIN_W: Final[int] = 720
_HEIGHT: Final[int] = 300

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


def render_svg(finding: Finding) -> str:
    """Render one finding's path as a standalone SVG. Deterministic."""
    legs = finding.legs
    count = len(legs)
    width = max(_MIN_W, 2 * _MARGIN + count * _NODE_W + (count - 1) * _GAP)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{_HEIGHT}" viewBox="0 0 {width} {_HEIGHT}" '
        f'role="img" aria-label="{escape(finding.summary)}">',
        f'<rect width="{width}" height="{_HEIGHT}" fill="{_PAPER}"/>',
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
    for x in xs[:-1]:
        start, end = x + _NODE_W, x + _NODE_W + _GAP
        parts.append(
            f'<line x1="{start}" y1="{edge_y}" x2="{end}" y2="{edge_y}" '
            f'stroke="{_EDGE}" stroke-width="3" marker-end="url(#arrow)"/>'
        )
        # Centred in the gap so it never overruns the node it points at.
        mid = (start + end) // 2
        parts.append(_text(mid, edge_y - 12, "verbatim", 11, _EDGE, anchor="middle"))

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
    disclaimer = "verbatim taint only; flow observed, not causation"
    parts.append(_text(_MARGIN, footer_y + 44, disclaimer, 11, _MUTED))

    parts.append("</svg>")
    return "\n".join(parts) + "\n"
