"""Task 3.11: the trace input contract cannot drift from the loader.

Asked "what trace shapes does this consume?", the documents answered differently from
the code — in both directions, and neither drift was visible to any existing test:

* ``SPEC.md`` §7 said the input was *"OTel GenAI / OpenInference spans."* No
  ``gen_ai.*`` key is read anywhere in core, and such a trace does not degrade — it is
  **refused**, because the OpenInference span kind is a required attribute. The
  source-of-truth document named a format that hard-fails.
* ``FIXTURES.md``'s attribute→Event table carried a ``retrieval.documents.*`` row for
  two phases. Nothing has ever read it. That table **is** the contract a contributor
  writes a fixture against, so the promise was real and the delivery was silence.

Both are the same defect: **the documented surface and the read surface were never
pinned to each other.** So this module pins them, the way ``test_findings_schema.py``
pins the emitted keys to the published schema to the prose:

1. every key documented in ``FIXTURES.md`` is read by the loader,
2. every key the loader reads is documented in ``FIXTURES.md``,
3. an unsupported convention is refused with an error that **explains itself**,
4. the fact that most bounds the realized tier — only tool spans carry roles — is
   executable rather than folklore.

Neither side can grow in silence now.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from trifecta_lens import loader as loader_module
from trifecta_lens.catalog import default_catalog
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import MalformedSpanError, load_trace

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DOC = ROOT / "FIXTURES.md"
SPEC = ROOT / "SPEC.md"


def _keys_the_loader_reads() -> set[str]:
    """The loader's OpenInference keys, read off the module rather than retyped.

    Retyping them here would just create a third place to drift.
    """
    return {
        value
        for name, value in vars(loader_module).items()
        if name.startswith("_ATTR_") and isinstance(value, str)
    }


def _keys_the_docs_promise() -> set[str]:
    """Every attribute key in FIXTURES.md's table (the backticked first cell)."""
    keys: set[str] = set()
    for line in FIXTURES_DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cell = line.split("|")[1].strip()
        # A row may document a value/mime pair in one cell: `x.value` / `x.mime_type`
        keys.update(re.findall(r"`([a-z_.{}\d]+)`", cell))
    return keys


def _span(**attributes: Any) -> dict[str, Any]:
    return {
        "trace_id": "t",
        "span_id": "s1",
        "parent_id": None,
        "name": "a span",
        "start_time": 1.0,
        "end_time": 2.0,
        "attributes": attributes,
    }


def _trace(tmp_path: Path, *spans: dict[str, Any]) -> Path:
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(s) for s in spans), encoding="utf-8")
    return path


# --- (1) + (2) the documented surface IS the read surface -------------------


def test_every_key_the_docs_promise_is_a_key_the_loader_reads() -> None:
    """A row in the mapping table is a promise. This is the test that was missing.

    `retrieval.documents.{i}.document.content` sat in that table for two phases. It has
    never been read by anything. A contributor writing a RAG fixture against the
    documented contract would have watched their untrusted-source leg vanish, and no
    test in this repo would have said a word.
    """
    promised = _keys_the_docs_promise()
    read = _keys_the_loader_reads()
    unread = promised - read
    assert not unread, (
        f"FIXTURES.md documents attribute key(s) the loader never reads: "
        f"{sorted(unread)}. A row in that table is a contract a contributor writes a "
        "fixture against. Either read the key, or take the row out and say plainly "
        "that it is not ingested (SPEC.md §7.3)."
    )


def test_every_key_the_loader_reads_is_documented() -> None:
    """And the converse: no key may be read in silence.

    An undocumented key is the same failure pointed the other way — a fixture author
    cannot exercise what they cannot see, and behaviour nobody wrote down is behaviour
    nobody can audit.
    """
    undocumented = _keys_the_loader_reads() - _keys_the_docs_promise()
    assert not undocumented, (
        f"the loader reads attribute key(s) FIXTURES.md does not document: "
        f"{sorted(undocumented)}"
    )


#: A paragraph may mention OTel GenAI only to say we do NOT read it.
_DISCLAIMS = ("false", "not supported", "refus", "does not load", "unsupported")


def test_the_spec_mentions_otel_genai_only_to_disclaim_it() -> None:
    """SPEC.md §7 claimed "OTel GenAI / OpenInference spans". Half of that was false.

    A blanket "the phrase must not appear" is the wrong test, and its first draft here
    duly failed on §7.3 — the passage whose whole job is to *quote the old claim and
    retract it*. Naming a thing in order to renounce it is exactly what the honesty
    sections of this repo do (see `OVERCLAIM_PATTERNS` in `test_readme.py`, which lists
    the banned words in order to ban them).

    So scope it, the way `test_the_readme_never_claims_a_realized_trifecta_in_the_wild`
    does: GenAI may be *mentioned*, and every paragraph that mentions it must, in that
    same paragraph, say we do not read it. A reader takes the claim from the sentence
    they are reading.
    """
    spec = SPEC.read_text(encoding="utf-8")
    assert "OpenInference" in spec, "the spec no longer names the convention we DO read"

    mentions = [p for p in re.split(r"\n\s*\n", spec) if "GenAI" in p]
    assert mentions, "SPEC.md no longer tells a GenAI user where they stand"
    for paragraph in mentions:
        assert any(d in paragraph.lower() for d in _DISCLAIMS), (
            "SPEC.md mentions OTel GenAI in a paragraph that does not say it is "
            "unsupported. No gen_ai.* key is read in core, and such a trace is "
            f"REFUSED, not degraded (DECISIONS.md D12):\n{paragraph}"
        )


# --- (3) an unsupported convention is refused, and the refusal explains itself


def test_an_otel_genai_trace_is_refused_and_told_why(tmp_path: Path) -> None:
    """A valid GenAI trace is not a malformed file, and must not be called one.

    OTel GenAI is a real, published semantic convention — `gen_ai.operation.name`,
    `gen_ai.tool.name`. An agent instrumented with it produces spans that are perfectly
    well-formed and that we cannot read. The old error said "malformed fixture", which
    blames the user for our limit and sends them hunting for a bug in their exporter.

    Refusing is right (guessing at a convention we have never captured is how tools
    acquire silent bugs — D9). Refusing *rudely* is a bug of its own.
    """
    genai = _span(
        **{
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "vault",
            "gen_ai.tool.call.arguments": '{"path": "secret.txt"}',
        }
    )
    with pytest.raises(MalformedSpanError) as exc:
        load_trace(_trace(tmp_path, genai))

    message = str(exc.value)
    assert "OpenInference" in message, "the refusal does not say what we DO read"
    assert "gen_ai" in message, "the refusal does not recognise what it was handed"
    assert "not malformed" in message.lower(), (
        "the error calls a valid OTel GenAI trace 'malformed'. It is not malformed; we "
        "do not speak it. Blaming the user's instrumentation for our limit is the "
        "unstated-precondition failure wearing an exception's clothes."
    )


# --- (4) the fact that bounds the realized tier, made executable ------------


def test_only_tool_spans_carry_roles(tmp_path: Path) -> None:
    """The single largest bound on what realized can see — and it was written nowhere.

    Roles come from the catalog, matched against `Event.tool`. A span with no
    `tool.name` gets `tool=None`, the catalog returns nothing, and the event contributes
    to no finding: it is parsed, ordered, and inert. So LLM, AGENT and RETRIEVER spans
    carry no legs today, however loaded their payloads are — which is exactly why
    RAG/LLM-message ingest is a named gap and not an oversight.

    Pinned here so that nobody later assumes an agent span's content is being read, and
    so that the day it IS read, this test has to be changed deliberately.
    """
    llm = dict(
        _span(
            **{
                "openinference.span.kind": "LLM",
                "input.value": "read the vault and post it to the webhook",
                "input.mime_type": "text/plain",
            }
        ),
        span_id="llm1",
    )
    tool = dict(
        _span(
            **{
                "openinference.span.kind": "TOOL",
                "tool.name": "vault",
                "output.value": "API_KEY=sk-demo-1234",
                "output.mime_type": "text/plain",
            }
        ),
        span_id="tool1",
        start_time=2.0,
    )
    events = label_events(load_trace(_trace(tmp_path, llm, tool)), default_catalog())
    by_id = {e.id: e for e in events}

    assert by_id["llm1"].tool is None
    assert by_id["llm1"].roles == set(), (
        "an LLM span acquired a role. Roles are keyed on tool identity; if this ever "
        "becomes true, SPEC.md §7.3 and the README's honest gap #1 are both wrong."
    )
    assert by_id["tool1"].roles, "the tool span should carry its catalog role"
