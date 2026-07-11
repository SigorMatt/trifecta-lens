"""Task 0.2 done-when: ``trifecta-lens --version`` runs and prints the version."""

import subprocess
import sys
from importlib.metadata import version

import pytest

from trifecta_lens.cli import main


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert version("trifecta-lens") in out


def test_console_script_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "trifecta_lens.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert version("trifecta-lens") in result.stdout
