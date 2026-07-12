"""Task 2.2: the path's basis is causal or temporal, and we say which (D5).

The realized finding reports a path and the SVG draws it as an **arrow**. But in
the realized anchor every tool span is a *sibling* under the root: `parent_id`
links each tool to the agent, never to the previous tool. So `s3 → s4` rests on
**temporal order alone** — we observed the vault read happen *before* the webhook
post, and we observed the value at the sink. We did **not** observe that the read
*fed* the post.

Nothing we emit is false today. But an unlabelled arrow, in an artifact built to
be screenshotted out of context, is read as causation — and that is the single
largest overclaim risk in the product (CLAUDE.md invariant 4).

So: every edge carries its basis, every finding carries `path_basis`, and the SVG
says which it drew. Where instrumentation *does* give a real parent chain, we get
to report the STRONGER claim honestly — labelling is not only a hedge, it unlocks
something.
"""

import json
from pathlib import Path

from trifecta_lens.engine import detect_realized
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace
from trifecta_lens.report import format_report
from trifecta_lens.svg import render_svg

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
ANCHOR = FIXTURES / "demo_realized.jsonl"
CAUSAL = FIXTURES / "causal_chain.jsonl"


def _finding(path: Path) -> dict[str, object]:
    (finding,) = detect_realized(label_events(load_trace(path)))
    return finding.to_dict()


# --- the anchor: temporal, and it says so ------------------------------------


def test_anchor_path_basis_is_temporal() -> None:
    """The honest reading of a trace whose tool spans are all siblings."""
    finding = _finding(ANCHOR)
    assert finding["path_basis"] == "temporal"


def test_anchor_edges_each_carry_their_basis() -> None:
    finding = _finding(ANCHOR)
    assert finding["path_edges"] == [
        {"basis": "temporal", "from": "s3", "to": "s4"},
    ]


def test_anchor_report_does_not_present_the_path_as_causation() -> None:
    events = label_events(load_trace(ANCHOR))
    text = format_report(list(detect_realized(events)), events)
    assert "temporal" in text.lower()
    # The report must say what temporal MEANS, not just print the word.
    assert "observed before" in text.lower() or "ordering" in text.lower()


def test_anchor_svg_labels_the_edge_as_temporal() -> None:
    (finding,) = detect_realized(label_events(load_trace(ANCHOR)))
    svg = render_svg(finding)
    assert "temporal" in svg
    # The artifact travels alone: it must not imply causation on its own.
    for banned in ("attack", "caused", "exploit"):
        assert banned not in svg.lower()


# --- a real parent chain: causal, and we get to say the stronger thing --------


def test_causal_chain_is_reported_as_causal() -> None:
    """When the instrumentor gives real ancestry, we report the stronger path.

    causal_chain.jsonl threads parent_id THROUGH the tools (webhook's parent is
    the vault span, not the agent root), which is what a framework emitting true
    tool-to-tool ancestry looks like.
    """
    finding = _finding(CAUSAL)
    assert finding["path_basis"] == "causal"
    assert finding["path_edges"] == [
        {"basis": "causal", "from": "s1", "to": "s2"},
    ]


def test_causal_finding_still_makes_no_causal_CLAIM() -> None:
    """`path_basis: causal` describes the TRACE's ancestry, not our verdict.

    It says the spans are causally linked in the instrumentation. It does NOT
    say the untrusted content caused the action — invariant 4 is untouched.
    """
    finding = _finding(CAUSAL)
    assert finding["summary"] == "tainted data observed reaching webhook"
    blob = json.dumps(finding).lower()
    for banned in ("attack", "caused", "exfiltration occurred", "exploit"):
        assert banned not in blob


# --- the field is required, not optional -------------------------------------


def test_path_basis_is_present_on_every_finding() -> None:
    for name in ("demo_realized.jsonl", "worked_example.jsonl", "causal_chain.jsonl"):
        finding = _finding(FIXTURES / name)
        assert finding["path_basis"] in {"causal", "temporal", "mixed"}
        assert finding["path_edges"]
