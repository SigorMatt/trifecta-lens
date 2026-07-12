"""Task 1.8 done-when: `make demo` writes the SVG for the anchor's s3 -> s4 path.

Hand-positioned; no graphviz, no layout library (DESIGN.md §8) — a layout engine
would be a system binary that breaks `uvx`-in-60s and whose output drifts between
versions, which would break determinism.

The SVG is the shareable artifact, so the honesty invariants matter MORE here,
not less: it is the thing that gets screenshotted out of context. It must carry
its family, its missing leg, and its masked value.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from trifecta_lens.engine import detect_realized
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace
from trifecta_lens.svg import render_svg

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
ANCHOR = FIXTURES / "demo_realized.jsonl"
SECRET = "sk-demo-trifecta-lens-DO-NOT-USE-0000"


def _anchor_svg() -> str:
    events = label_events(load_trace(ANCHOR))
    (finding,) = detect_realized(events)
    return render_svg(finding)


def test_svg_is_well_formed_and_renders_the_path() -> None:
    svg = _anchor_svg()
    root = ET.fromstring(svg)  # parses => well-formed
    assert root.tag.endswith("svg")

    text = " ".join(node.text or "" for node in root.iter())
    for expected in ("s3", "s4", "vault", "webhook", "sensitive_data", "sink:exfil"):
        assert expected in text, expected


def test_svg_carries_the_family_and_the_missing_leg() -> None:
    """It gets screenshotted out of context — it must not read as the trifecta."""
    svg = _anchor_svg()
    assert "sensitive_to_exfil_sink" in svg
    assert "NOT the trifecta" in svg
    assert "untrusted_source" in svg
    assert "not observed" in svg


def test_svg_masks_the_value_and_makes_no_causal_claim() -> None:
    svg = _anchor_svg()
    assert "sk-demo-...MASKED" in svg
    assert SECRET not in svg
    assert "tainted data observed reaching webhook" in svg
    for banned in ("attack", "exfiltration occurred", "caused", "exploit"):
        assert banned not in svg.lower()


def test_svg_has_the_red_edge_on_the_path() -> None:
    assert re.search(r'stroke="#[a-fA-F0-9]{6}"', _anchor_svg())
    assert "marker-end" in _anchor_svg()  # the arrowhead: direction of flow


def test_svg_is_deterministic() -> None:
    assert _anchor_svg() == _anchor_svg()
