"""Tests for the replay-only ``make demo`` entry (:mod:`demo.replay`).

The replay loads the committed realized-positive fixture through the *core*
loader and prints the observed vault -> webhook flow — no model, no network, no
provider/SDK. These assertions pin the task 1.2 done-whens: it names the flow,
masks the secret, claims no verdict, and is deterministic.
"""

from __future__ import annotations

import pytest

from demo import replay

FIXTURE = "fixtures/demo_realized.jsonl"

# The raw token committed in demo/secret.txt and captured verbatim in the trace.
# It must never appear in the replay output (masking).
RAW_SECRET = "sk-demo-trifecta-lens-DO-NOT-USE-0000"

# Verdict/causation language the honesty gate bans; a replay states none of it.
BANNED_TOKENS = ("attack", "exfiltration occurred", "caused", "detected")


def _run(capsys: pytest.CaptureFixture[str]) -> str:
    rc = replay.main([FIXTURE])
    assert rc == 0
    return capsys.readouterr().out


def test_replay_names_the_vault_webhook_flow(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _run(capsys)
    assert out.strip()  # non-empty
    assert "vault" in out
    assert "webhook" in out
    # It states the observed flow and that no finding is emitted (verdict pending).
    assert "vault -> webhook" in out
    assert "no finding emitted" in out


def test_replay_masks_the_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _run(capsys)
    # The raw token is present verbatim in the fixture's webhook body; the replay
    # must not echo it in the clear.
    assert RAW_SECRET not in out
    # ...but the masked stand-in is shown, so the flow is still visible.
    assert "sk-demo-...MASKED" in out


def test_replay_makes_no_verdict_claim(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _run(capsys).lower()
    for token in BANNED_TOKENS:
        assert token not in out


def test_replay_is_deterministic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = _run(capsys)
    second = _run(capsys)
    assert first == second
