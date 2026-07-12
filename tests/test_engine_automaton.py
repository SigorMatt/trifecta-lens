"""Task 2.9: the engine IS the fixed property automaton (DESIGN.md §§2-4).

Not a re-test of the realized detector (that is `test_detector.py`) — this pins the
*machine*, the thing all three tiers are projections of:

* one acceptance predicate, `satisfied_families`, shared by every tier;
* the family lattice (trifecta ⊆ two-leg) — monotone, so a finding never gets
  promoted;
* the machine is CLOSED: no v1 family accepts on an impact sink, however the
  catalog labels one.

If a change here passes, the tier-containment claim in `DESIGN.md` §3 holds by
construction rather than by the report text agreeing with itself.
"""

from __future__ import annotations

from trifecta_lens.engine import (
    FAMILIES,
    FAMILY_TRIFECTA,
    FAMILY_TWO_LEG,
    satisfied_families,
)
from trifecta_lens.roles import (
    SENSITIVE_DATA,
    SINK_EXFIL,
    SINK_IMPACT,
    UNTRUSTED_SOURCE,
)

ALL_THREE = frozenset({UNTRUSTED_SOURCE, SENSITIVE_DATA, SINK_EXFIL})
TWO_LEG = frozenset({SENSITIVE_DATA, SINK_EXFIL})


def _ids(legs: frozenset[str]) -> list[str]:
    return [f.id for f in satisfied_families(legs)]


def test_the_strongest_accepting_family_comes_first() -> None:
    """Reporting takes `[0]`, so the ordering is load-bearing, not cosmetic."""
    assert _ids(ALL_THREE)[0] == FAMILY_TRIFECTA


def test_trifecta_is_contained_in_two_leg_at_a_fixed_tier() -> None:
    """DESIGN.md §3: the families are a lattice, not two independent detectors.

    Anything that accepts the trifecta also accepts two-leg — its legs are a
    subset. This is why one flow yields ONE finding (at the strongest family) and
    not two, and why a finding can never be promoted up a family later.
    """
    assert _ids(ALL_THREE) == [FAMILY_TRIFECTA, FAMILY_TWO_LEG]
    assert _ids(TWO_LEG) == [FAMILY_TWO_LEG]

    trifecta = next(f for f in FAMILIES if f.id == FAMILY_TRIFECTA)
    two_leg = next(f for f in FAMILIES if f.id == FAMILY_TWO_LEG)
    assert two_leg.required < trifecta.required  # strict subset


def test_the_sensitive_leg_is_required_by_every_exfil_family() -> None:
    """Exfil is about SENSITIVE data leaving. No sensitive leg, no exfil finding.

    A source that reaches a sink with nothing sensitive in the path is the
    action-hijack family's territory (SPEC.md §3) — which v1 does not ship. The
    machine must be silent here, not creative.
    """
    assert _ids(frozenset({UNTRUSTED_SOURCE, SINK_EXFIL})) == []
    assert all(SENSITIVE_DATA in f.required for f in FAMILIES)


def test_no_sink_means_no_acceptance() -> None:
    """The sink terminates the path. Legs without one are exposure, not a flow."""
    assert _ids(frozenset({UNTRUSTED_SOURCE, SENSITIVE_DATA})) == []
    assert _ids(frozenset()) == []
    assert _ids(frozenset({SENSITIVE_DATA})) == []


def test_no_v1_family_accepts_on_an_impact_sink() -> None:
    """The machine is CLOSED (DESIGN.md §4). The catalog cannot open it.

    Impact sinks are catalogued today (`filesystem__write_file`) and the
    action-hijack family is fast-follow. A user could label every tool they own as
    `sink:impact` and still get no v1 finding — coverage is the tunable layer,
    acceptance is not. That is the invariant-2 boundary, checked.
    """
    assert _ids(frozenset({UNTRUSTED_SOURCE, SENSITIVE_DATA, SINK_IMPACT})) == []
    assert all(f.sink == SINK_EXFIL for f in FAMILIES)


def test_acceptance_is_monotone_in_the_legs() -> None:
    """The lattice never retreats: adding a leg never REMOVES an accepting family.

    Monotonicity is what lets the engine be an incremental fold that never retracts
    a finding (DESIGN.md §6) — the streaming-readiness premium, paid here.
    """
    for legs in (frozenset(), TWO_LEG, ALL_THREE):
        for extra in (UNTRUSTED_SOURCE, SENSITIVE_DATA, SINK_EXFIL, SINK_IMPACT):
            grown = legs | {extra}
            assert set(_ids(legs)) <= set(_ids(grown)), (
                f"adding {extra} to {sorted(legs)} removed an accepting family"
            )
