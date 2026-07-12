"""Task 3.1: the launch README is held to the same honesty gates as the output.

The README is the artifact most people will ever see of this project, and it is
the one no test used to touch. That is backwards: every honesty invariant we
enforce in the report exists because a *reader* could otherwise be misled, and far
more readers will read the README than will run the tool.

So the 0.8 gate is extended to it, three ways:

1. **Banned causal/attack language** (invariant 4) — the same scanner that guards
   the rendered report.
2. **No overclaiming** (invariant 5) — a launch page is where a tool starts
   promising to *prevent* things. This one observes and reports; it sits nowhere
   near the request path.
3. **Every line of output shown is real.** The console block and the findings JSON
   in the README are regenerated here from the committed artifacts and compared.
   "Never fabricate a captured artifact" has to cover the place the artifact is
   *shown*, or it protects the fixtures and not the reader. A prettied-up sample
   output is exactly the kind of small lie that would be discovered by the first
   person who ran it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.test_gates import banned_tokens_in
from trifecta_lens.engine import (
    detect_posture,
    detect_reachable,
    detect_realized,
    reachable_collapse,
)
from trifecta_lens.inventory import load_inventory
from trifecta_lens.labeling import label_events, label_inventory
from trifecta_lens.loader import load_otlp_trace
from trifecta_lens.report import TierResults, format_report

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"

#: Claims a read-only analyzer cannot make. It is not in the request path: it can
#: neither prevent nor stop anything, and "proves" is the causal overreach of
#: invariant 4 wearing a marketing hat. (Note the scan is over the README's prose;
#: naming these words HERE is what keeps them out of THERE.)
OVERCLAIM_PATTERNS = (
    r"\bprevent(s|ed|ing)?\b",
    r"\bblock(s|ed|ing)\b",
    r"\bstops\b",
    r"\bprotect(s|ed|ing|ion)\b",
    r"\bguarantee(s|d)?\b",
    r"\bprove(s|d|n)\b",
    r"\bcomplete coverage\b",
    r"\bfully automatic\b",
    r"\breal[- ]time\b",
)


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _fenced() -> list[tuple[str, str]]:
    """Every fenced block as ``(language, body)``.

    Walked line by line rather than matched with a regex: a naive
    ``^```(lang)\\n(.*?)^```" happily treats a CLOSING fence as an opening one and
    captures the *prose between two blocks* as if it were code. (It did, and the
    install-command test below duly failed on an English sentence.)
    """
    blocks: list[tuple[str, str]] = []
    lang: str | None = None
    body: list[str] = []
    for line in _readme().splitlines():
        if line.startswith("```"):
            if lang is None:
                lang, body = line[3:].strip(), []
            else:
                blocks.append((lang, "\n".join(body)))
                lang = None
        elif lang is not None:
            body.append(line)
    return blocks


def _blocks(lang: str) -> list[str]:
    return [body for language, body in _fenced() if language == lang]


def _real_report() -> str:
    """Render the report from the REAL captured artifacts — the README's subject."""
    events = tuple(
        label_events(load_otlp_trace(REPO / "fixtures" / "demo_mcp_trace.otlp.json"))
    )
    stack = label_inventory(load_inventory(REPO / "fixtures" / "inventory.json"))
    return format_report(
        results=TierResults(
            events=events,
            realized=tuple(detect_realized(events)),
            reachable=tuple(detect_reachable(stack)),
            posture=tuple(detect_posture(stack)),
            collapse=reachable_collapse(stack),
        )
    )


def test_the_readme_carries_no_causal_or_attack_language() -> None:
    """Invariant 4, applied to the front page."""
    assert not banned_tokens_in(_readme())


def test_the_readme_makes_no_claim_a_read_only_analyzer_cannot_make() -> None:
    """Invariant 5. It reports; it does not stand in the way of anything."""
    text = _readme()
    offenders = [
        m.group(0)
        for p in OVERCLAIM_PATTERNS
        for m in re.finditer(p, text, flags=re.IGNORECASE)
    ]
    assert not offenders, f"overclaiming language in README: {offenders}"


def test_every_line_of_output_shown_in_the_readme_is_real_output() -> None:
    """The README's console block must be lines the tool actually printed.

    This is "never fabricate a captured artifact" pointed at the README. The block
    may ELIDE (a line of `...`) — leaving things out is honest — but it may not
    contain a line the real run did not produce. If someone tunes the report
    wording and the README drifts, the drift fails here rather than in front of the
    first person who runs it.
    """
    report = _real_report()
    real_lines = {line.rstrip() for line in report.splitlines()}

    shown = [b for b in _blocks("text") if "[REALIZED]" in b or "[REACHABLE" in b]
    assert shown, "the README shows no analyzer output — the hero claim is unshown"

    for block in shown:
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "..." or stripped.startswith("$ "):
                continue  # elision and the command line itself
            assert line.rstrip() in real_lines, (
                f"README shows a line the tool does not print:\n  {line!r}\n"
                "Every line of output in the README must come from a real run."
            )


def test_the_findings_json_in_the_readme_is_the_real_finding() -> None:
    """The JSON shown is the real realized finding, parsed and compared — not a sample.

    Compared as data, not as text, so formatting is free; but every key and every
    value must be what the analyzer actually emitted for the committed capture.
    """
    events = tuple(
        label_events(load_otlp_trace(REPO / "fixtures" / "demo_mcp_trace.otlp.json"))
    )
    realized = tuple(detect_realized(events))
    assert len(realized) == 1
    real = json.loads(realized[0].to_json_line())

    shown = [b for b in _blocks("json") if '"family"' in b]
    assert shown, "the README shows no findings JSON — the public contract is unshown"
    for block in shown:
        assert json.loads(block) == real, (
            "the findings JSON in the README is not what the analyzer emits"
        )


def test_the_readme_does_not_tell_a_stranger_to_install_something_that_isnt_there() -> (
    None
):
    """The quickstart has to WORK on first contact. Today that means: not PyPI.

    The first draft of this README opened with `pipx install "trifecta-lens[capture]"`,
    which reads perfectly and fails for every human who runs it: the package is not
    published. A launch page whose very first command 404s has spent the credibility
    the rest of the page is asking for.

    So the install line points at the repo, and this test pins that. **When
    trifecta-lens is published to PyPI, flip both** — the README line and this test,
    together, in the same change. That is the point: the claim cannot become true
    quietly, and it cannot become false quietly either.
    """
    text = _readme()
    assert "Not on PyPI yet" in text, (
        "the README must say the package is unpublished for as long as it is"
    )
    # Only COMMANDS — the lines a reader will paste into a shell. Prose may discuss
    # the PyPI command that does not exist yet (the paragraph above does exactly
    # that); what must never happen is one sitting in a code block, ready to run.
    commands = "\n".join(
        body for lang, body in _fenced() if lang in {"", "console", "sh", "bash"}
    )
    install_lines = [
        line
        for line in commands.splitlines()
        if ("pipx install" in line or "uvx" in line)
        and not line.lstrip().startswith("#")
    ]
    assert install_lines, "the README shows no install command"
    for line in install_lines:
        assert "git+https://" in line, (
            f"install command does not resolve to anything installable today: {line}"
        )


def test_the_readme_states_the_four_honest_gaps() -> None:
    """ROADMAP's four gaps travel WITH the claim, not in a footnote nobody opens.

    Each of these is a thing a reader would otherwise reasonably assume we do.
    """
    text = _readme().lower()
    gaps = {
        "verbatim-only taint": "verbatim",
        "RAG/LLM-message ingest not built": "rag",
        "the realized anchor is a direct instruction, not an injection": (
            "direct instruction"
        ),
        "action-hijack is catalogued but not accepted by any v1 family": (
            "action-hijack"
        ),
    }
    missing = [name for name, needle in gaps.items() if needle not in text]
    assert not missing, f"README does not state these honest gaps: {missing}"


def test_the_readme_never_claims_a_realized_trifecta_in_the_wild() -> None:
    """The launch claim (D10), enforced.

    The realized *trifecta* is exercised only by a hand-authored fixture. The
    captured runs realized the lesser two-leg family. If a README ever mentions the
    worked example without disclosing that it was hand-authored, that is the
    overclaim this project cannot survive — so it fails the build.
    """
    text = _readme()
    assert "worked_example" in text, "the hand-authored fixture must be disclosed"

    # The disclosure must live in the SAME paragraph as the mention. A neighbouring
    # paragraph is not a disclosure: a reader takes the claim from the sentence they
    # are reading. (A first cut of this test allowed a 400-character window, and a
    # planted violation walked straight through it because the next paragraph
    # happened to say "hand-authored" about something else.)
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if "worked_example" in p]
    assert paragraphs
    for paragraph in paragraphs:
        assert "hand-authored" in paragraph.lower(), (
            "worked_example is mentioned in a paragraph that does not call it "
            "hand-authored. That fixture is the ONLY thing exercising the realized "
            f"trifecta, and it is not a capture:\n{paragraph}"
        )
    assert "not claim" in text.lower() or "do not claim" in text.lower()
