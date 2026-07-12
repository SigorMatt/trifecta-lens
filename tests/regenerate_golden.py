"""Regenerate `fixtures/golden/` — the findings regression anchor (`make golden`).

Not a test: a maintenance script, kept beside the test that consumes its output.
Run it only when a change is *meant* to move the findings, and commit the result
in the same change so the movement lands as a reviewable diff.

Deterministic by construction — it is the same pipeline `make check` runs.
"""

from __future__ import annotations

from pathlib import Path

from trifecta_lens.engine import detect_realized
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
GOLDEN = FIXTURES / "golden"


def main() -> None:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for fixture in sorted(FIXTURES.glob("*.jsonl")):
        events = label_events(load_trace(fixture))
        lines = [finding.to_json_line() for finding in detect_realized(events)]
        out = GOLDEN / f"{fixture.stem}.findings.ndjson"
        out.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        print(f"{fixture.name}: {len(lines)} finding(s) -> {out.name}")


if __name__ == "__main__":
    main()
