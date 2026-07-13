"""What the catalog sees when it is pointed at the servers people actually run.

The catalog had 16 entries and looked healthy. Then it was pointed at the tool names
the widely-deployed MCP servers really expose, and **71% of them got no label at all**
— including `slack__slack_post_message`, which is the commonest outbound sink in
production MCP, and `brave__brave_web_search` and `puppeteer__puppeteer_navigate`,
which are the commonest untrusted sources. Nothing was lying: D13's coverage report
dutifully listed every one of them as unmatched. The tool simply had no opinion about
anybody's real stack, and no test anywhere said so, because every catalog test used
tools *we* had named.

The cause was not "too few entries". Two entries were **shaped wrong**: real servers
repeat their own name inside the tool name (`slack_post_message`), so the qualified
name is `slack__slack_post_message`, and `(.*__)?post_message` cannot match it — the
`.*__` eats `slack__` and leaves `slack_post_message`. See the header of
`exfil_v1.yaml`.

So this module pins the measurement, in both directions:

* **What we match**, so an over-eager future pattern shows up as a diff here rather
  than as a confident wrong finding in someone's report.
* **What we deliberately do NOT match, and why.** This half is the load-bearing one.
  `postgres__query` is silent *on purpose*: the pattern would have to be
  `search|query|retrieve`, which `CONTRIBUTING.md` explicitly refuses to guess at,
  because a query may read a public price list or the credentials table and the name
  does not say which. Someone will eventually see that silence, read it as a bug, and
  "fix" it. The expected-silence table is the note we leave for them.
"""

from __future__ import annotations

from pathlib import Path

from trifecta_lens.catalog import default_catalog
from trifecta_lens.engine import FAMILY_TRIFECTA, detect_realized
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_trace
from trifecta_lens.roles import (
    SENSITIVE_DATA,
    SINK_EXFIL,
    SINK_IMPACT,
    UNTRUSTED_SOURCE,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

#: Real tool names, as the servers expose them, qualified as an MCP host presents them.
#: `None` means **expected silence**, with the reason. Nothing here is aspirational: it
#: is what `Catalog.label` returns today, and a change to any of it is a change to what
#: this tool tells a stranger about their own stack.
REAL_STACKS: dict[str, list[tuple[str, frozenset[str] | None, str]]] = {
    "slack": [
        ("slack__slack_post_message", frozenset({SINK_EXFIL}),
         "the commonest outbound sink in production MCP"),
        ("slack__slack_reply_to_thread", frozenset({SINK_EXFIL}),
         "same sink, threaded"),
        ("slack__slack_get_channel_history", frozenset({UNTRUSTED_SOURCE}),
         "other people's messages: third-party text the agent ingests"),
        ("slack__slack_list_channels", None,
         "returns NAMES, not message content — labeling it would make every "
         "channel list a leg, exactly as `list_directory` would"),
    ],
    "brave": [
        ("brave__brave_web_search", frozenset({UNTRUSTED_SOURCE}),
         "web results are third-party content, seedable by whoever wants them read"),
        ("brave__brave_local_search", frozenset({UNTRUSTED_SOURCE}), "same"),
    ],
    "puppeteer": [
        ("puppeteer__puppeteer_navigate", frozenset({UNTRUSTED_SOURCE}),
         "`fetch` with a rendering engine in front of it"),
        ("puppeteer__puppeteer_evaluate", None,
         "executes script in the page — an ACTION, so it belongs to sink:impact, "
         "but no v1 family accepts on impact. Labeling it now would imply we reason "
         "about a family that does not exist. Phase 4."),
    ],
    "gdrive": [
        ("gdrive__read_file", frozenset({SENSITIVE_DATA}),
         "a document out of the company's Drive — the SAME leg the filesystem entry "
         "covers, from the server people actually use"),
        ("gdrive__search", None,
         "`search` is the ambiguous verb — see the module docstring"),
    ],
    "github": [
        ("github__get_issue", frozenset({UNTRUSTED_SOURCE}),
         "the single most-documented real-world injection vector"),
        ("github__create_issue", frozenset({SINK_EXFIL}),
         "a write to a public location publishes the payload"),
        ("github__create_or_update_file", frozenset({SINK_IMPACT}),
         "writes code into a repo — inert in v1, no family accepts on impact"),
        ("github__merge_pull_request", frozenset({SINK_IMPACT}), "same"),
        ("github__search_code", None, "`search` — ambiguous verb"),
    ],
    "notion": [
        ("notion__create_page", frozenset({SINK_EXFIL}),
         "a shared workspace page is a shared location, even though it does not look "
         "like an outbound request"),
        ("notion__append_block_children", frozenset({SINK_EXFIL}), "same"),
        ("notion__search", None, "`search` — ambiguous verb"),
        ("notion__retrieve_page", None,
         "`retrieve` — ambiguous verb; a page may be anything"),
    ],
    "linear": [
        ("linear__list_issues", frozenset({UNTRUSTED_SOURCE}),
         "third-party issue text"),
        ("linear__create_issue", frozenset({SINK_EXFIL}), "public write"),
        ("linear__update_issue", frozenset({SINK_EXFIL}), "public write"),
    ],
    "jira": [
        ("jira__get_issue", frozenset({UNTRUSTED_SOURCE}), "third-party issue text"),
        ("jira__add_comment", frozenset({SINK_EXFIL}), "public write"),
        ("jira__search_issues", None, "`search` — ambiguous verb"),
    ],
    "sentry": [
        ("sentry__get_issue", frozenset({UNTRUSTED_SOURCE}),
         "error reports carry user-supplied strings"),
    ],
    "postgres": [
        ("postgres__query", None,
         "THE deliberate silence. A query may read a public price list or the "
         "credentials table; the name does not say which. Blanket-labeling every "
         "`query` sensitive_data would put a confident leg under a finding for every "
         "agent that has ever read a database. Use a --catalog overlay."),
        ("postgres__read_query", None, "same"),
        ("postgres__list_tables", None, "returns NAMES"),
    ],
    "snowflake": [
        ("snowflake__read_query", None, "same as postgres"),
        ("snowflake__write_query", None,
         "a DB write is an impact sink in principle, but no v1 family accepts on "
         "impact, and `write_query` may be a routine upsert. Phase 4."),
    ],
}


def _labels(tool: str) -> frozenset[str]:
    return frozenset(str(role) for role in default_catalog().label(tool))


def test_the_catalog_labels_the_stacks_people_actually_run() -> None:
    """The positive half: every tool we claim to see, we see — with the right role."""
    wrong: list[str] = []
    for server, tools in REAL_STACKS.items():
        for tool, expected, why in tools:
            if expected is None:
                continue
            got = _labels(tool)
            if got != expected:
                wrong.append(
                    f"  {server}: {tool}\n"
                    f"    expected {sorted(expected)} ({why})\n"
                    f"    got      {sorted(got) or 'NOTHING'}"
                )
    assert not wrong, (
        "the catalog no longer sees a real stack it used to:\n" + "\n".join(wrong)
    )


def test_the_deliberate_silences_stay_silent() -> None:
    """The load-bearing half.

    Each of these is a tool we could label and have decided not to. If one of them
    starts matching, someone has widened a pattern into the `search|query|retrieve`
    collision, and the next report will carry a confident role nobody assigned. That
    is the failure this catalog exists to avoid, and it is worth a red build.
    """
    noisy: list[str] = []
    for server, tools in REAL_STACKS.items():
        for tool, expected, why in tools:
            if expected is not None:
                continue
            got = _labels(tool)
            if got:
                noisy.append(f"  {server}: {tool} now labeled {sorted(got)}\n    {why}")
    assert not noisy, (
        "a tool we deliberately leave unlabeled is now being labeled — a pattern has "
        "been widened past what its name can support:\n" + "\n".join(noisy)
    )


def test_coverage_on_real_stacks_does_not_regress() -> None:
    """The number, tracked.

    It was 29% (9 of 31) when this was first measured, and every one of the misses was
    a server somebody runs in production. It is not a target to game — the deliberate
    silences below can never be converted — but a *drop* means a real regression and
    should never pass review quietly.
    """
    tools = [t for entries in REAL_STACKS.values() for t in entries]
    matched = sum(1 for tool, _, _ in tools if _labels(tool))

    assert matched >= 19, (
        f"catalog coverage on real stacks fell to {matched}/{len(tools)}; it was 19. "
        "An entry was probably narrowed or removed."
    )


def test_the_new_entries_find_a_trifecta_end_to_end() -> None:
    """The positive fixture, and the point of the whole exercise.

    A Brave search, a Drive read, a Slack post — an utterly ordinary 2026 agent stack,
    and one that this catalog scored **zero of three** on until now. The trace is
    hand-authored (`FIXTURES_PROVENANCE.md` says so, and it is not a recording of
    anything). What it demonstrates is not that the flow is common; it is that the
    engine was always able to find it and the *labels* were what stopped it.

    Its benign twin — same three tools, same three labels, agent summarizes instead of
    pasting — is in `test_benign_corpus.py` and stays silent. Neither fixture means
    much without the other.
    """
    events = list(label_events(load_trace(FIXTURES / "modern_stack_trifecta.jsonl")))
    findings = list(detect_realized(events))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.family == FAMILY_TRIFECTA, "all three legs are present in this trace"
    assert finding.sink_tool == "slack__slack_post_message"

    cited = {leg.catalog_entry for leg in finding.legs}
    assert {"web.search", "file.read", "message.send"} <= cited, (
        "the finding must cite the entries that assigned each role — that citation is "
        "how a user who disagrees with a label knows what to edit"
    )
