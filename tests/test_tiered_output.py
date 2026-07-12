"""Task 2.12: tiered output across all three tiers (report + NDJSON + SVG).

The done-when: one run over the REAL inventory + the REAL trace emits all three
tiers, each correctly badged, with tier honesty holding in the **text** and not
only in the logic (`CLAUDE.md` invariant 3).

The failure this guards against is subtle and is the one that would actually
happen: not a tier printing a false fact, but a tier printing a *true* fact in the
stronger tier's voice — a posture finding that reads like an observation, or an
empty section that reads like a clean bill of health. So the assertions here are
about VERBS and about the difference between "did not run" and "found nothing".
"""

from __future__ import annotations

import json
from pathlib import Path

from trifecta_lens.cli import main
from trifecta_lens.engine import (
    FAMILY_TRIFECTA,
    FAMILY_TWO_LEG,
    detect_posture,
    detect_reachable,
    detect_realized,
    reachable_collapse,
)
from trifecta_lens.findings import TIER_POSTURE, TIER_REACHABLE, TIER_REALIZED
from trifecta_lens.inventory import load_inventory
from trifecta_lens.labeling import label_events, label_inventory
from trifecta_lens.loader import load_otlp_trace
from trifecta_lens.report import TierResults, format_report
from trifecta_lens.svg import render_svg

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
INVENTORY = FIXTURES / "inventory.json"
OTLP_TRACE = FIXTURES / "demo_mcp_trace.otlp.json"
SECRET = "sk-demo-trifecta-lens-DO-NOT-USE-0000"


def _results() -> TierResults:
    """One run over BOTH real captured artifacts — the Phase 2 exit shape."""
    events = tuple(label_events(load_otlp_trace(OTLP_TRACE)))
    stack = label_inventory(load_inventory(INVENTORY))
    return TierResults(
        events=events,
        realized=tuple(detect_realized(events)),
        reachable=tuple(detect_reachable(stack)),
        posture=tuple(detect_posture(stack)),
        collapse=reachable_collapse(stack),
    )


# --- The done-when ----------------------------------------------------------


def test_one_run_emits_all_three_tiers_each_correctly_badged() -> None:
    text = format_report(results=_results())

    assert "[REALIZED]  sensitive_to_exfil_sink" in text
    assert "[REACHABLE]  exfil_trifecta" in text
    assert "[POSTURE]  exfil_trifecta" in text

    # Strongest first. Posture is never the headline (SPEC.md §5).
    assert text.index("--- REALIZED") < text.index("--- REACHABLE") < text.index(
        "--- POSTURE"
    )


def test_the_report_teaches_what_each_tier_MEANS() -> None:
    """A badge the reader must already understand is not a disclosure."""
    text = format_report(results=_results())
    assert "a run DID wire it" in text
    assert "COULD wire it. No run was observed doing so." in text
    assert "Weakest tier" in text


# --- Tier honesty, in the TEXT (CLAUDE.md invariant 3) -----------------------


def test_the_capability_tiers_never_borrow_the_word_observed() -> None:
    """The strongest word in this product belongs to realized alone.

    Posture and reachable read an inventory. They opened no payload and watched no
    run. Their leg lists say "legs exposed", never "legs observed" — and they say
    outright that no run was observed.
    """
    full = format_report(results=_results())
    # Only the capability SECTIONS — the legend above them necessarily explains what
    # realized's verb means, and that explanation is the disclosure, not a breach.
    capability = full[full.index("--- REACHABLE") :]

    assert "legs exposed:" in capability
    assert "legs observed:" not in capability
    assert "No run was observed doing so." in capability
    assert "capability, not observation" in capability
    # Realized's summary verb never appears in a tier that observed nothing.
    assert "observed reaching" not in capability


def test_a_capability_finding_carries_no_realized_evidence_in_the_ndjson() -> None:
    results = _results()
    for finding in [*(results.reachable or ()), *(results.posture or ())]:
        line = json.loads(finding.to_json_line())
        for forbidden in ("path", "path_basis", "path_edges", "masked_values",
                          "legs_observed", "detected_under"):
            assert forbidden not in line, f"{finding.tier} finding carries {forbidden}"


def test_the_realized_finding_still_carries_all_of_its_disclosures() -> None:
    """The other direction: 2.12 must not have thinned realized's schema."""
    finding = (_results().realized or ())[0]
    line = json.loads(finding.to_json_line())

    assert line["tier"] == TIER_REALIZED
    assert line["family"] == FAMILY_TWO_LEG
    assert line["path_basis"] == "temporal"
    assert line["path_edges"] and line["path"]
    assert line["detected_under"]["min_value_chars"] == 8
    assert line["legs_not_observed"] == ["untrusted_source"]
    assert SECRET not in json.dumps(line)


def test_did_not_run_is_never_rendered_as_found_nothing() -> None:
    """The quiet, dangerous failure: an empty section read as a clean result."""
    trace_only = format_report(results=TierResults(events=(), realized=()))
    assert "posture and reachable: NOT RUN" in trace_only

    inventory_only = format_report(
        results=TierResults(posture=(), reachable=(), collapse=None)
    )
    assert "realized: NOT RUN" in inventory_only
    assert "not a clean result" in inventory_only


# --- The findings NDJSON, all tiers ------------------------------------------


def test_ndjson_carries_every_tier_strongest_first(tmp_path: Path) -> None:
    out = tmp_path / "findings.ndjson"
    rc = main(
        [
            "--trace", str(OTLP_TRACE),
            "--inventory", str(INVENTORY),
            "--findings", str(out),
        ]
    )
    assert rc == 0

    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert [x["tier"] for x in lines] == [TIER_REALIZED, TIER_REACHABLE, TIER_POSTURE]

    # Every line is a complete, self-describing finding: tier + family + the
    # caveat that bounds it. A consumer reading ONE line must not be misled.
    for line in lines:
        assert line["tier"] and line["family"]
        assert line["scope"] and line["note"]
        assert SECRET not in json.dumps(line)

    realized, reachable, posture = lines
    assert realized["family"] == FAMILY_TWO_LEG
    assert reachable["family"] == FAMILY_TRIFECTA  # could, but didn't
    assert posture["family"] == FAMILY_TRIFECTA
    assert "strictly tighter than posture" in reachable["disclosure"]


def test_the_cli_runs_a_tier_only_when_given_its_input(tmp_path: Path) -> None:
    out = tmp_path / "f.ndjson"
    main(["--inventory", str(INVENTORY), "--findings", str(out)])
    tiers = {json.loads(x)["tier"] for x in out.read_text().splitlines()}
    assert tiers == {TIER_REACHABLE, TIER_POSTURE}  # no trace -> no realized


# --- The SVG (the artifact that travels without its report) ------------------


def test_the_svg_shows_the_reachable_gap_as_NOT_observed() -> None:
    """The money shot, and the place it would be easiest to overclaim.

    The captured run realized only the two-leg family. The same agent context is
    also exposed to `fetch__fetch`, so the FULL trifecta was reachable and no run
    was seen wiring it. That gap is the most interesting thing on the picture — and
    it must be rendered as capability, in grey, below the path. Never on the red
    edge, which means "observed".
    """
    results = _results()
    svg = render_svg((results.realized or ())[0], reachable=results.reachable or ())

    assert "[REACHABLE, NOT OBSERVED]" in svg
    assert FAMILY_TRIFECTA in svg
    assert "No run was observed doing so." in svg
    assert "Capability, not observation." in svg

    # The red edge belongs to the observed flow alone. The escalation text must not
    # be drawn in it.
    edge_colour = "#d1242f"
    escalation_line = next(
        line for line in svg.splitlines() if "REACHABLE, NOT OBSERVED" in line
    )
    assert edge_colour not in escalation_line

    assert SECRET not in svg


def test_the_svg_omits_the_gap_when_there_is_none() -> None:
    """No stronger family reachable -> no block. It never invents an escalation."""
    results = _results()
    svg = render_svg((results.realized or ())[0], reachable=())
    assert "[REACHABLE, NOT OBSERVED]" not in svg


def test_nothing_in_the_svg_is_clipped_by_the_canvas() -> None:
    """The disclaimers are the FIRST thing a too-small canvas would cut off.

    The escalation block grows the picture, and the honesty text sits at the very
    bottom — so an off-by-one in the height silently truncates exactly the lines
    that stop a screenshot reading as a causal claim. There is no rasterizer in CI,
    so check the geometry arithmetically: every element must sit inside the canvas.
    """
    import re

    results = _results()
    for reachable in ((), results.reachable or ()):
        svg = render_svg((results.realized or ())[0], reachable=reachable)

        width = int(re.search(r'width="(\d+)"', svg).group(1))  # type: ignore[union-attr]
        height = int(re.search(r'height="(\d+)"', svg).group(1))  # type: ignore[union-attr]

        elements = re.findall(
            r'<text x="(\d+)" y="(\d+)"[^>]*font-size="(\d+)"[^>]*>([^<]*)</text>', svg
        )
        assert elements
        for x, y, size, content in elements:
            assert int(y) < height, f"text at y={y} falls off a {height}px canvas"
            # ~0.6em per glyph is the monospace advance; enough to catch a real overrun.
            end = int(x) + len(content) * int(size) * 0.6
            assert end <= width, f"{content[:40]!r} overruns the {width}px canvas"


def test_tiered_output_is_deterministic() -> None:
    assert format_report(results=_results()) == format_report(results=_results())
