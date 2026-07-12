"""Task 3.4: every documented incident cites a verified PRIMARY source.

`ROADMAP.md` calls this "the bill that comes due": a tool whose moat is not
overclaiming cannot launch on second-hand incident summaries. `INCIDENTS.md` is
the verification record. This test makes the discipline executable — it fails if
an incident is listed without a primary-source URL and a verification date — so a
future contributor cannot add a motivating incident without doing the verification
the file promises.

It checks structure, not truth: it cannot reach the network (CI is offline), and
it does not try to. It guarantees that every claim in the launch material is at
least *anchored* to a cited primary source a reader can follow.
"""

from __future__ import annotations

import re
from pathlib import Path

INCIDENTS = Path(__file__).resolve().parent.parent / "INCIDENTS.md"
HTTPS = re.compile(r"https://\S+")


def _sections(prefix: str) -> list[tuple[str, str]]:
    """(heading, body) for every heading at the given markdown level."""
    text = INCIDENTS.read_text()
    lines = text.splitlines()
    out: list[tuple[str, str]] = []
    heading: str | None = None
    body: list[str] = []
    for line in lines:
        # A new heading at THIS level (or shallower) closes the current section.
        is_this = line.startswith(prefix + " ")
        is_shallower = line.startswith("#") and not line.startswith(prefix) and (
            len(line) - len(line.lstrip("#")) < len(prefix)
        )
        if is_this or is_shallower:
            if heading is not None:
                out.append((heading, "\n".join(body)))
            heading = line[len(prefix):].strip() if is_this else None
            body = []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        out.append((heading, "\n".join(body)))
    return out


def _incident_blocks() -> list[tuple[str, str]]:
    """The `###` incident entries under the "Documented incidents" `##` section."""
    for heading, body in _sections("##"):
        if heading.lower().startswith("documented incidents"):
            # Re-scan just this section's body for its ### entries.
            blocks: list[tuple[str, str]] = []
            sub: str | None = None
            acc: list[str] = []
            for line in body.splitlines():
                if line.startswith("### "):
                    if sub is not None:
                        blocks.append((sub, "\n".join(acc)))
                    sub, acc = line[4:].strip(), []
                elif sub is not None:
                    acc.append(line)
            if sub is not None:
                blocks.append((sub, "\n".join(acc)))
            return blocks
    raise AssertionError("INCIDENTS.md has no '## Documented incidents' section")


def test_incidents_file_exists() -> None:
    assert INCIDENTS.exists(), "INCIDENTS.md is the primary-source verification record"


def test_every_incident_cites_a_primary_source_and_a_verification_date() -> None:
    blocks = _incident_blocks()
    assert len(blocks) >= 2, "expected at least two verified incidents"
    for heading, body in blocks:
        low = body.lower()
        assert "primary source" in low, f"{heading!r} cites no primary source"
        assert HTTPS.search(body), f"{heading!r} has no https:// primary-source URL"
        assert re.search(r"verified:\W*20\d\d-\d\d-\d\d", low), (
            f"{heading!r} carries no 'Verified: YYYY-MM-DD' date"
        )


def test_all_source_urls_are_https() -> None:
    """No http:// primary sources — a citation a reader cannot trust the origin of."""
    text = INCIDENTS.read_text()
    assert "http://" not in text, "a source URL uses http:// — use https://"


def test_the_scope_caveat_is_present() -> None:
    """The limitation must travel WITH the motivation, never be dropped from it."""
    low = INCIDENTS.read_text().lower()
    assert "verbatim-only" in low or "verbatim only" in low
    assert "reachable/posture" in low
