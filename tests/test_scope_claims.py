"""The gate for the OTHER direction: a doc that denies a capability we ship.

Every honesty gate in this repo hunts a false *statement* — banned causal language,
a tier borrowing a stronger tier's words, an install command that 404s. That is one
half of `CLAUDE.md` invariant 5, and for a long time it was the only half anyone
enforced. The result was predictable in hindsight: D15 found the engine detecting
cross-agent flow while `SPEC.md` §8 listed it as an explicit non-goal, and the fix
to §8 then **failed to propagate** — `README.md` went on saying "four tiers" and
"out of scope: cross-agent multi-hop" two lines apart, one of those four tiers being
the cross-agent tier. Four documents denied a capability the tool demonstrably has,
and not one test noticed, because no test was looking that way.

So: **derive the shipped capabilities from the code, and fail the build if a doc
parks one.** A tool whose moat is saying what it cannot do has to be held to saying
what it *can*, or the moat is just a mood.

The scan is deliberately conservative about *history*. A doc is allowed — encouraged —
to narrate that something *used to* be a non-goal (that is what `DECISIONS.md` is for).
What it may not do is state, in the present tense, that a shipped capability is out of
scope. The correction markers below are what separate the two, and
`test_the_gate_bites` proves the separation is real by feeding it the exact pre-fix
line from `README.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

from trifecta_lens.engine import detect_reachable_cross_agent
from trifecta_lens.findings import TIER_REACHABLE_CROSS, TIERS, Finding

REPO = Path(__file__).resolve().parent.parent

#: Docs that make scope claims a reader will act on. `DECISIONS.md` and `DEBT.md` are
#: narrative — they exist to record how we got here, including what we once believed —
#: so they are scanned too, but the history markers below carry most of the weight
#: there.
DOCS: tuple[str, ...] = (
    "README.md",
    "AGENT.md",
    "CLAUDE.md",
    "SPEC.md",
    "ROADMAP.md",
    "TASKS.md",
    "DEBT.md",
    "DECISIONS.md",
    "USAGE.md",
    "CONTRIBUTING.md",
)

#: Phrases that put whatever they touch OUTSIDE what the tool does.
DENIAL = re.compile(
    r"out of scope|non-goal|not supported|unsupported|parked|not promised"
    r"|never represented as shipped|do not (?:imply|claim)|not tasks",
    re.IGNORECASE,
)

#: Phrases making the sentence a *history* or a *correction* rather than a live denial.
#:
#: **Every marker here must speak about the capability's own status.** The first draft
#: of this gate also exempted any line mentioning `cross-session`, on the theory that
#: naming the genuinely-parked neighbour showed the author knew the difference. Running
#: the gate against the pre-fix docs proved that reasoning backwards: `ROADMAP.md:276`
#: read *"Transformed taint, cross-agent multi-hop, memory-poisoning, cross-session
#: state"* — parking BOTH on one line — and the exemption waved the whole line through.
#: A line's correct treatment of a neighbour cannot excuse its incorrect treatment of
#: the capability we are checking. That miss is the reason this list is what it is.
CORRECTION = re.compile(
    r"within one trace|is detected|IS detected|shipped|used to|listed"
    r"|no longer|left this list|not on this list|do not confuse|D15"
    # `DECISIONS.md` records each decision by quoting the question that prompted it
    # ("in answer to '...why is X a non-goal...'"). That is a citation of the framing,
    # not an assertion of scope — and a ledger that could not quote the question it
    # answered would be a worse ledger.
    r"|in answer to",
    re.IGNORECASE,
)


def _shipped_capabilities() -> dict[str, re.Pattern[str]]:
    """The capabilities the CODE has, and the words a doc would deny them with.

    Keyed off real symbols, not a hand-kept list: if a future change removed the
    cross-agent tier, this gate would relax on its own rather than lying in the
    other direction.
    """
    shipped: dict[str, re.Pattern[str]] = {}

    if (
        TIER_REACHABLE_CROSS in TIERS
        and hasattr(Finding, "crosses_agents")
        and callable(detect_reachable_cross_agent)
    ):
        shipped["cross-agent flow within one trace"] = re.compile(
            r"cross-agent|cross agent", re.IGNORECASE
        )

    return shipped


def scan(text: str, mention: re.Pattern[str]) -> list[tuple[int, str]]:
    """Lines in ``text`` where ``mention`` sits in a live denial context.

    **A denial is not always on the line that does the denying.** The first draft of
    this checked each line in isolation and so missed `ROADMAP.md:276` — a bare list,
    *"Transformed taint, cross-agent multi-hop, memory-poisoning, cross-session
    state"*, carrying no denial word at all. What parked it was the **heading**:
    `## North star (parked — not promised)`. A gate blind to section context is blind
    to the commonest shape a non-goals list takes, so the heading governs its section.

    The one exception is a **blockquote**, which is this repo's established way of
    writing a *correction inside* a scope section — `SPEC.md` §8 does exactly that,
    parking cross-session in the list and then correcting the cross-agent record in a
    `>` note directly beneath. Exempting blockquotes from the *heading* rule costs
    nothing: a blockquote that states a live denial still carries a denial word, and
    the line-level check catches it regardless.

    Split out from the file walk so the bite-checks below can run against the **real
    pre-fix text**, permanently and in CI, instead of depending on someone remembering
    to stash the fix and eyeball a red run.
    """
    hits: list[tuple[int, str]] = []
    heading = ""
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            heading = line
            continue

        quoted = line.lstrip().startswith(">")
        denied = bool(DENIAL.search(line)) or (
            bool(DENIAL.search(heading)) and not quoted
        )
        if mention.search(line) and denied and not CORRECTION.search(line):
            hits.append((lineno, line.strip()))
    return hits


def _violations() -> list[tuple[str, int, str, str]]:
    found: list[tuple[str, int, str, str]] = []
    for capability, mention in _shipped_capabilities().items():
        for doc in DOCS:
            path = REPO / doc
            if not path.exists():
                continue
            for lineno, line in scan(path.read_text(), mention):
                found.append((doc, lineno, capability, line))
    return found


def test_no_doc_parks_a_capability_the_code_ships() -> None:
    """The gate itself. This is what four documents failed for two commits."""
    violations = _violations()
    assert not violations, "docs deny a capability the code ships:\n" + "\n".join(
        f"  {doc}:{lineno}  ({capability})\n    {line}"
        for doc, lineno, capability, line in violations
    )


def test_the_shipped_capability_is_affirmatively_stated() -> None:
    """Not parking it is not enough — the reader-facing docs must SAY we do it.

    Silence is how this defect got in. A README that merely stopped denying
    cross-agent flow, without stating it, would pass the scan above and still leave
    every reader believing the old thing.
    """
    for doc in ("README.md", "AGENT.md", "SPEC.md"):
        text = (REPO / doc).read_text().lower()
        assert "cross-agent" in text or "cross agent" in text, (
            f"{doc} never mentions cross-agent flow at all — the tier ships, "
            "and the docs a reader actually reads must say so"
        )
        assert "within one trace" in text, (
            f"{doc} mentions cross-agent flow but not the boundary that makes the "
            "claim honest ('within one trace') — cross-SESSION remains out of scope, "
            "and conflating the two overclaims in the other direction"
        )


#: The three sections **verbatim as they shipped**, before this fix. Each is a real
#: violation that lived on `main`, and each defeated an earlier draft of this gate for
#: a *different* reason — which is the whole argument for keeping all three:
#:
#: * `README.md`  — the denial is on the line. Caught by the first draft.
#: * `TASKS.md`   — same, via "Not tasks." Caught by the first draft.
#: * `ROADMAP.md` — **the line carries no denial word at all.** The heading parks it.
#:   The first draft missed this entirely, and the second draft *also* missed it, by
#:   excusing the line for correctly naming cross-session alongside. Two misses, one
#:   line: it earns its place here more than the other two combined.
PRE_FIX: dict[str, str] = {
    "README.md": (
        "## Status\n"
        "\n"
        "v0.1 — the analyzer, four tiers, a real MCP capture, a versioned findings"
        " schema.\n"
        "Out of scope for v1 and named as such: transformed taint, cross-agent"
        " multi-hop,\n"
        "memory poisoning. Next: the action-hijack family, SARIF, a GitHub Action.\n"
    ),
    "TASKS.md": (
        "## North star — parked\n"
        "\n"
        "Not tasks. Transformed taint, cross-agent multi-hop, memory-poisoning,\n"
        "cross-session state; streaming/live mode and action-hook consumers.\n"
    ),
    "ROADMAP.md": (
        "## North star (parked — not promised)\n"
        "Transformed taint, cross-agent multi-hop, memory-poisoning, cross-session"
        " state.\n"
        "Also parked here:\n"
    ),
}


def test_the_gate_bites_on_every_document_that_shipped_the_bug() -> None:
    """A gate never seen red is not a gate.

    Run the scanner against the real pre-fix text of all three docs. Every one must
    be flagged. This runs in CI on every commit, so the proof does not decay into a
    thing someone once did by hand and remembers being fine.

    The bar is not academic: **twice** in this repo a gate was added without checking
    it against the artifact it was written for, and **twice** it turned out to pass a
    planted violation.
    """
    mention = _shipped_capabilities()["cross-agent flow within one trace"]

    for doc, text in PRE_FIX.items():
        hits = scan(text, mention)
        assert hits, (
            f"the gate does not flag the violation {doc} actually shipped — it is "
            f"decoration, not a gate:\n{text}"
        )


def test_the_gate_does_not_flag_the_fixed_documents() -> None:
    """The converse, on the same three files as they stand now.

    Without this, the test above is satisfiable by a scanner that flags everything.
    """
    mention = _shipped_capabilities()["cross-agent flow within one trace"]

    for doc in PRE_FIX:
        assert not scan((REPO / doc).read_text(), mention), (
            f"{doc} still parks cross-agent flow"
        )


def test_the_gate_does_not_flag_the_honest_parked_line() -> None:
    """The converse: cross-SESSION is genuinely out of scope and must stay sayable.

    If this fails, the gate has become a ratchet that forbids the true statement along
    with the false one — which would push the docs into overclaiming, the very thing
    the rest of the suite exists to prevent. The honest line survives for the right
    reason: it does not mention cross-agent at all.
    """
    honest = (
        "Out of scope for v1: transformed taint, memory-poisoning, and anything "
        "crossing sessions — a value stored in one run and read in the next."
    )
    mention = _shipped_capabilities()["cross-agent flow within one trace"]

    assert DENIAL.search(honest)
    assert not mention.search(honest), "the honest parked line must survive the scan"
