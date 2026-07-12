"""Task 1.4 done-when: the demo events carry the right roles.

The labels now come from the catalog (task 2.8) rather than the slice's hardcoded
table, but what this test pins is unchanged — and deliberately so. Two things,
both load-bearing for family honesty (SPEC.md §3, CLAUDE.md invariant 3):

1. vault -> sensitive_data, webhook -> sink:exfil.
2. NO span in the anchor is labeled untrusted_source. The anchor is a
   direct-instruction run; the root s0 is the principal's OWN prompt, not
   ingested untrusted content. Labeling it (or the vault read) as a source to
   force the trifecta to accept is exactly the mislabeling this project must
   never do — and moving the labels into a data file, where they are *easier* to
   add, is precisely when that guarantee needs re-pinning.
"""

from pathlib import Path

from trifecta_lens.catalog import default_catalog
from trifecta_lens.labeling import label_events, roles_for_tool
from trifecta_lens.loader import load_trace
from trifecta_lens.roles import SENSITIVE_DATA, SINK_EXFIL, UNTRUSTED_SOURCE

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
ANCHOR = FIXTURES / "demo_realized.jsonl"


def test_anchor_events_carry_the_right_roles() -> None:
    events = label_events(load_trace(ANCHOR))
    by_id = {e.id: e for e in events}

    assert by_id["s0"].roles == set()  # the principal's prompt: NOT a source
    assert by_id["s1"].roles == {SENSITIVE_DATA}
    assert by_id["s2"].roles == {SINK_EXFIL}
    assert by_id["s3"].roles == {SENSITIVE_DATA}
    assert by_id["s4"].roles == {SINK_EXFIL}


def test_no_span_in_the_anchor_is_labeled_untrusted_source() -> None:
    events = label_events(load_trace(ANCHOR))
    assert all(UNTRUSTED_SOURCE not in e.roles for e in events)


def test_unmapped_tools_get_no_roles() -> None:
    """Labeling is a lookup, not a guess: unknown tools stay unlabeled."""
    catalog = default_catalog()
    assert roles_for_tool("acme__frobnicate", catalog) == set()
    assert roles_for_tool(None, catalog) == set()


def test_each_role_carries_the_catalog_ENTRY_that_assigned_it() -> None:
    """A finding must cite WHY and WHERE TO FIX IT (SPEC.md §4).

    The event carries both, so the engine can cite the entry without ever learning
    a tool name.
    """
    events = label_events(load_trace(ANCHOR))

    vault = next(e for e in events if e.id == "s1")
    label = vault.role_labels[SENSITIVE_DATA]
    assert label.note == "reads a credential from the secret store"
    assert label.entry == "vault.secret"  # the id the user edits to change the call

    unlabeled = next(e for e in events if e.id == "s0")
    assert unlabeled.role_labels == {}


def test_labeling_leaves_payloads_untouched() -> None:
    raw = load_trace(ANCHOR)
    labeled = label_events(raw)
    assert [e.inputs for e in labeled] == [e.inputs for e in raw]
    assert [e.outputs for e in labeled] == [e.outputs for e in raw]
    assert [e.id for e in labeled] == [e.id for e in raw]
