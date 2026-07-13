"""Task 3.13: USAGE.md is EXECUTED, not merely written.

A usage guide is the most dangerous document this project ships. `README.md` argues;
`SPEC.md` specifies; **`USAGE.md` is nothing but commands and outputs, and it is the
first thing a newcomer copies.** A doc that drifts from the code turns the one
advertised path into a failure on first contact, for the one person willing to walk it.

`tests/test_contributing.py` already runs every YAML example in `CONTRIBUTING.md`
through the real parser; `tests/test_readme.py` regenerates every line of output the
README shows. This file does both for the manual, and adds the pin those two do not
need: **every flag the parsers accept is documented, and every flag documented exists**
— both directions, so the manual cannot drift from `argparse` in either.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from tests.test_gates import banned_tokens_in
from trifecta_capture.cli import _build_parser as capture_parser
from trifecta_lens.cli import _build_parser as lens_parser

REPO = Path(__file__).resolve().parent.parent
USAGE = REPO / "USAGE.md"


def _text() -> str:
    return USAGE.read_text(encoding="utf-8")


def _fenced() -> list[tuple[str, str]]:
    """Every fenced block as ``(language, body)``.

    Walked line by line, not regex-matched: a naive pattern happily treats a CLOSING
    fence as an opening one and captures the prose between two blocks as code. (That bug
    is recorded in `test_readme.py`, where it actually bit.)
    """
    blocks: list[tuple[str, str]] = []
    lang: str | None = None
    body: list[str] = []
    for line in _text().splitlines():
        if line.startswith("```"):
            if lang is None:
                lang, body = line[3:].strip(), []
            else:
                blocks.append((lang, "\n".join(body)))
                lang = None
        elif lang is not None:
            body.append(line)
    return blocks


def _commands() -> list[str]:
    """Every runnable `trifecta-lens ...` invocation shown, joined across backslashes.

    A **synopsis** (`--trace <spans.jsonl>`) is skipped: angle brackets mean "your file
    goes here", and a synopsis is not something anyone pastes. Every command that names
    a REAL path is run.
    """
    out: list[str] = []
    for lang, body in _fenced():
        if lang not in {"", "sh", "bash", "console"}:
            continue
        joined = body.replace("\\\n", " ")
        for line in joined.splitlines():
            line = line.strip()
            if line.startswith("trifecta-lens ") and "<" not in line:
                out.append(line)
    return out


# --- (1) every command shown actually runs ----------------------------------


def test_every_trifecta_lens_command_in_the_manual_runs() -> None:
    """Copy-paste is meant to work. These run against the committed fixtures."""
    commands = _commands()
    assert commands, "the manual shows no runnable trifecta-lens command"

    for command in commands:
        args = command.split()[1:]
        result = subprocess.run(
            [sys.executable, "-m", "trifecta_lens.cli", *args],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        assert result.returncode == 0, (
            f"a command in USAGE.md fails:\n  {command}\n{result.stderr}"
        )


# --- (2) every line of output shown is a line the tool really printed -------


def _real_output(command: str) -> str:
    args = command.split()[1:]
    return subprocess.run(
        [sys.executable, "-m", "trifecta_lens.cli", *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    ).stdout


def test_every_line_of_output_shown_is_real_output() -> None:
    """"Never fabricate" applies to where output is SHOWN, or it protects nothing.

    A prettied-up sample is exactly the kind of small lie the first person to run the
    tool would catch. Blocks may ELIDE (a line of `...`) — leaving things out is honest
    — but they may not contain a line no run produced.
    """
    printed: set[str] = set()
    for command in _commands():
        printed |= {line.rstrip() for line in _real_output(command).splitlines()}

    shown = [body for lang, body in _fenced() if lang == "text"]
    assert shown, "the manual shows no output — every claim in it is unbacked"

    for block in shown:
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "...":
                continue
            assert line.rstrip() in printed, (
                f"USAGE.md shows a line the tool never printed:\n  {line!r}\n"
                "Every line of output in the manual must come from a real run."
            )


# --- (3) the manual and argparse cannot drift apart -------------------------


def _documented_flags() -> set[str]:
    """Every `--flag` the manual mentions, wherever it mentions it."""
    return set(re.findall(r"(--[a-z][a-z-]+)", _text()))


def _real_flags(parser: object) -> set[str]:
    return {
        option
        for action in parser._actions  # type: ignore[attr-defined]
        for option in action.option_strings
        if option.startswith("--") and option not in {"--help", "--version"}
    }


def test_every_flag_the_tools_accept_is_documented() -> None:
    """An undocumented flag is a feature nobody can find."""
    real = _real_flags(lens_parser()) | _real_flags(capture_parser())
    undocumented = real - _documented_flags()
    assert not undocumented, (
        f"USAGE.md documents neither of these flags, which the CLIs accept: "
        f"{sorted(undocumented)}"
    )


def test_every_flag_the_manual_documents_exists() -> None:
    """And the converse — a documented flag that does not exist is worse than silence.

    It sends the one reader who trusted the manual straight into an argparse error.
    """
    real = _real_flags(lens_parser()) | _real_flags(capture_parser())
    # Flags named in the manual that belong to neither parser. `--context`/`--note` etc.
    # are trifecta-capture's; `--trace` etc. are trifecta-lens's; the union covers both.
    invented = {f for f in _documented_flags() if f not in real}
    assert not invented, (
        f"USAGE.md documents flag(s) that do not exist: {sorted(invented)}"
    )


# --- (4) the honesty gates apply to the manual like any other doc -----------


def test_the_manual_carries_no_causal_or_attack_language() -> None:
    """Invariant 4. The manual is where a tool starts narrating attacks."""
    assert not banned_tokens_in(_text())


def test_the_manual_does_not_claim_the_analyzer_prevents_anything() -> None:
    """Invariant 5. It reads two files and writes a report."""
    offenders = [
        m.group(0)
        for pattern in (
            r"\bprevent(s|ed|ing)?\b",
            r"\bblock(s|ed|ing)\b",
            r"\bprotect(s|ed|ing|ion)\b",
            r"\bguarantee(s|d)\b",
        )
        for m in re.finditer(pattern, _text(), flags=re.IGNORECASE)
    ]
    assert not offenders, f"overclaiming language in USAGE.md: {offenders}"


def test_the_manual_tells_a_non_mcp_reader_they_are_supported() -> None:
    """The reason this document exists (D14).

    The README said "for MCP-based agent systems" and documented only the MCP path,
    while the engine served a LangChain agent perfectly well. A reader who bounces off
    the docs is as lost as one the tool cannot help — and this one it can.
    """
    text = _text()
    assert "You do not need MCP" in text
    assert "schema/inventory.schema.json" in text, (
        "the manual does not tell a non-MCP reader that the inventory is a documented "
        "file they can write themselves"
    )
    # And the trap that makes a hand-written inventory work: no fake server.
    assert "No `server` key" in text or "Omit `server`" in text
