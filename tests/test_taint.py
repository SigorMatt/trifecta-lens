"""Task 1.5 done-when: verbatim taint (SPEC.md §6).

The secret is extracted from the vault outputs and matched into the webhook
inputs. The done-when is a discrimination, not just a hit:

  - MATCHES at s4   (body is the secret, verbatim)
  - does NOT match at s2 (body is the placeholder "<vault_output>")
  - does NOT match in either triage fixture (no secret reaches any sink)

v1 is the verbatim subset ONLY (SPEC.md §6): encoded, split, summarized, and
paraphrased values are out of scope by construction, and the tests below pin
that we do not silently pretend otherwise.
"""

from pathlib import Path

from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace
from trifecta_lens.roles import SENSITIVE_DATA
from trifecta_lens.taint import extract_values, mask, normalize, value_in_payload

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
ANCHOR = FIXTURES / "demo_realized.jsonl"
TRIAGE_REFUSED = FIXTURES / "triage_refused_sonnet5.jsonl"
TRIAGE_BENIGN = FIXTURES / "triage_benign_control.jsonl"

SECRET = "sk-demo-trifecta-lens-DO-NOT-USE-0000"


def _labeled(path: Path) -> list[object]:
    return list(label_events(load_trace(path)))


def test_secret_is_extracted_from_the_vault_outputs() -> None:
    by_id = {e.id: e for e in label_events(load_trace(ANCHOR))}

    # Taint-bearing events (the sensitive_data legs) yield the secret.
    assert extract_values(by_id["s1"]) == [SECRET]
    assert extract_values(by_id["s3"]) == [SECRET]

    # Sinks are not taint-bearing: nothing is extracted from them.
    assert extract_values(by_id["s2"]) == []
    assert extract_values(by_id["s4"]) == []
    assert extract_values(by_id["s0"]) == []


def test_secret_matches_at_s4_and_not_at_s2() -> None:
    """The load-bearing discriminator for the whole slice."""
    by_id = {e.id: e for e in label_events(load_trace(ANCHOR))}

    assert value_in_payload(SECRET, by_id["s4"].inputs) is True
    assert value_in_payload(SECRET, by_id["s2"].inputs) is False


def test_secret_is_absent_from_both_triage_fixtures() -> None:
    for path in (TRIAGE_REFUSED, TRIAGE_BENIGN):
        events = label_events(load_trace(path))
        assert not any(value_in_payload(SECRET, e.inputs) for e in events), path.name
        # These runs never call the vault, so no SENSITIVE value is ever registered.
        # (Since 2.13 the catalog does label their issue reads as untrusted_source,
        # so the taint register is not empty — it holds source-tainted values. What
        # is absent is a sensitive value, which is the leg exfil requires.)
        sensitive = [
            e for e in events if SENSITIVE_DATA in e.roles and extract_values(e)
        ]
        assert not sensitive, path.name


def test_normalization_is_light_only() -> None:
    """Trim, case-fold, collapse whitespace. Nothing more (SPEC.md §6)."""
    assert normalize("  sk-ABC   def ") == normalize("sk-abc def")
    assert normalize("a\n\tb") == "a b"


def test_transformed_taint_is_not_matched() -> None:
    """v1 does NOT cover encoded/split/paraphrased values — do not paper over it."""
    import base64

    encoded = base64.b64encode(SECRET.encode()).decode()
    assert value_in_payload(SECRET, {"body": encoded}) is False
    assert value_in_payload(SECRET, {"body": "sk-demo-trifecta" + "-lens-..."}) is False
    assert value_in_payload(SECRET, {"body": "the key from the vault"}) is False


def test_value_appears_inside_a_larger_payload() -> None:
    """Verbatim means untransformed, not necessarily the whole field."""
    assert value_in_payload(SECRET, {"body": f"key={SECRET}"}) is True


def test_mask_never_reveals_the_value() -> None:
    masked = mask(SECRET)
    assert SECRET not in masked
    assert masked.startswith("sk-demo-")
    assert "MASKED" in masked
