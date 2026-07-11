"""Task 0.7: Phase 0 done-whens as runnable checks, not prose.

- ``trifecta-lens --version`` exits 0.
- The worked fixture loads to the expected Event count.

Extended in Phase 1: positive fixture -> exactly one realized finding with the
path; benign -> none; re-run byte-identical.
"""

import subprocess
import sys
from pathlib import Path

from trifecta_lens.loader import load_trace

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKED_EXAMPLE = REPO_ROOT / "fixtures" / "worked_example.jsonl"
WORKED_EXAMPLE_EVENT_COUNT = 4


def test_version_exits_zero() -> None:
    console_script = Path(sys.executable).parent / "trifecta-lens"
    result = subprocess.run(
        [str(console_script), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_worked_fixture_loads_to_expected_event_count() -> None:
    events = load_trace(WORKED_EXAMPLE)
    assert len(events) == WORKED_EXAMPLE_EVENT_COUNT
