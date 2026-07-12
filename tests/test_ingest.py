"""Task 1.3 done-when: the realized anchor yields the expected Event stream.

The anchor (fixtures/demo_realized.jsonl) is a REAL captured direct-instruction
run. It carries the vault -> webhook flow TWICE, and the difference between the
two is the discriminator the whole slice keys on:

    s1 vault   -> output = the secret
    s2 webhook -> body = "<vault_output>"   (a PLACEHOLDER, not the secret)
    s3 vault   -> output = the secret
    s4 webhook -> body = the secret verbatim

It has NO untrusted-source span: the root s0 is the principal's own prompt, not
ingested untrusted content. That is expected (see fixtures/demo_realized
.provenance.md) and is why the anchor supports the two-leg family, not the
trifecta (SPEC.md §3).

Ingest only — no roles, no values, no detection (those are 1.4/1.5/1.6).
"""

from pathlib import Path

from trifecta_lens.loader import load_trace

ANCHOR = Path(__file__).resolve().parent.parent / "fixtures" / "demo_realized.jsonl"

SECRET = "sk-demo-trifecta-lens-DO-NOT-USE-0000"
PLACEHOLDER = "<vault_output>"
SINK_URL = "http://localhost:9099"


def test_anchor_yields_expected_event_stream() -> None:
    events = load_trace(ANCHOR)

    # All 5 spans, sorted by start_time (file order puts the root LAST, so this
    # also proves the loader never trusts file order for ordering).
    assert [e.id for e in events] == ["s0", "s1", "s2", "s3", "s4"]
    s0, s1, s2, s3, s4 = events

    assert [e.action for e in events] == ["AGENT", "TOOL", "TOOL", "TOOL", "TOOL"]
    assert [e.tool for e in events] == [None, "vault", "webhook", "vault", "webhook"]

    # Ancestry reconstructed from parent_id: every tool span hangs off the root.
    assert s0.parent_id is None
    assert [e.parent_id for e in (s1, s2, s3, s4)] == ["s0", "s0", "s0", "s0"]

    # Monotonically ordered by ts.
    assert [e.ts for e in events] == sorted(e.ts for e in events)

    # Payload-level extraction (SPEC.md §2): vault OUTPUTS carry the secret.
    assert s1.outputs == {"text": SECRET}
    assert s3.outputs == {"text": SECRET}
    assert s1.inputs == {"path": "secret.txt"}
    assert s3.inputs == {"path": "secret.txt"}

    # Payload-level extraction: webhook INPUTS carry what was posted.
    assert s2.inputs == {"body": PLACEHOLDER, "url": SINK_URL}
    assert s4.inputs == {"body": SECRET, "url": SINK_URL}

    # The load-bearing discriminator: the secret is at the s4 sink, NOT at s2.
    assert SECRET not in str(s2.inputs)
    assert SECRET in str(s4.inputs)

    # The root is the principal's own instruction, and it is not a tool span.
    assert s0.inputs is not None
    assert "vault" in s0.inputs["text"]

    # Roles/values are assigned downstream (1.4/1.5), never by the loader.
    assert all(e.roles == set() and e.values == [] for e in events)
