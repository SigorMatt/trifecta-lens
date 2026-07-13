"""Task 3.8: the tool inventory is a **published input contract**.

Until now this repo froze its *output* and left its *input* implicit. The findings
NDJSON is versioned, schema'd, and guarded by a test that fails the build if a field
moves — while the one file we ask the world to *produce* was described in SPEC.md §7
prose and enforced by ad-hoc ``raise InvalidInventoryError`` calls. That asymmetry is
not neutral: ``trifecta-capture`` only speaks stdio, so anyone whose MCP servers are
remote or hosted has to assemble the inventory themselves — and without a contract,
"assemble it yourself" reads like "make something up," which is the one thing this
project will not do.

It isn't. Obtaining a ``tools/list`` response from a real running server by *any*
means is a **capture** (DECISIONS.md D11). The distinction that matters here is
captured-vs-fabricated, never automated-vs-manual.

So this module pins three things together:

1. what ``load_inventory`` actually accepts and rejects,
2. the published contract (``schema/inventory.schema.json``),
3. the prose companion (SPEC.md §7).

And it proves — executably, not by assertion — the claim the contract rests on: an
inventory carrying **only** ``{server, tool: {name}}`` yields the *same findings* as
the full captured artifact. That is what makes the alternative path real rather than
merely permitted.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.test_findings_schema import _validate
from trifecta_lens.engine import detect_posture, detect_reachable
from trifecta_lens.inventory import InvalidInventoryError, load_inventory
from trifecta_lens.labeling import label_inventory

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "fixtures" / "inventory.json"
SCHEMA_PATH = ROOT / "schema" / "inventory.schema.json"
SPEC = ROOT / "SPEC.md"


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _captured() -> dict[str, Any]:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def _write(tmp_path: Path, doc: Any) -> Path:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# --- (1) the committed artifact honours its own published contract ----------


def test_the_real_captured_inventory_conforms_to_the_published_schema() -> None:
    schema = _schema()
    assert _validate(_captured(), schema, schema) == []


def test_the_validator_rejects_an_inventory_that_violates_the_contract() -> None:
    """Guard the guard: if a broken doc passes, conformance above proves nothing."""
    schema = _schema()

    no_contexts: dict[str, Any] = {}
    assert _validate(no_contexts, schema, schema)

    doc = _captured()
    del doc["contexts"][0]["tools"][0]["server"]
    assert _validate(doc, schema, schema), "a tool entry with no server passed"

    doc = _captured()
    del doc["contexts"][0]["tools"][0]["tool"]["name"]
    assert _validate(doc, schema, schema), "a tool with no name passed"


# --- (2) the schema and the loader agree on what is REQUIRED ----------------
# A contract that demands more than the loader does turns working inventories away;
# one that demands less waves through files that then fail deep in a stage seam.


def test_every_key_the_schema_requires_is_a_key_the_loader_enforces(
    tmp_path: Path,
) -> None:
    """Drop each required key in turn; the loader must reject the result."""
    cases: list[tuple[str, list[str | int]]] = [
        ("contexts", ["contexts"]),
        ("context id", ["contexts", 0, "id"]),
        ("tool entry server", ["contexts", 0, "tools", 0, "server"]),
        ("tool entry tool", ["contexts", 0, "tools", 0, "tool"]),
        ("tool name", ["contexts", 0, "tools", 0, "tool", "name"]),
    ]
    for name, path in cases:
        doc = _captured()
        target: Any = doc
        for step in path[:-1]:
            target = target[step]
        del target[path[-1]]

        schema = _schema()
        assert _validate(doc, schema, schema), (
            f"schema accepts an inventory missing its {name} — the contract is looser "
            "than the loader, so it would bless a file that then fails to load"
        )
        with pytest.raises(InvalidInventoryError):
            load_inventory(_write(tmp_path, doc))


def test_the_loader_requires_nothing_the_schema_leaves_optional(
    tmp_path: Path,
) -> None:
    """`provenance` and `servers` are optional — and really are, not just on paper.

    They matter to the *human* (provenance is the audit trail, and it is carried
    verbatim into the report). They are not needed to compute a topology, and a
    contract that pretended otherwise would turn an honest minimal inventory away.
    """
    doc = _captured()
    for context in doc["contexts"]:
        context.pop("provenance", None)
        context.pop("servers", None)

    schema = _schema()
    assert _validate(doc, schema, schema) == []
    inventory = load_inventory(_write(tmp_path, doc))
    assert inventory.posture_tools() == load_inventory(INVENTORY).posture_tools()


# --- (3) the claim the contract rests on, made executable -------------------


def _strip_to_names(doc: dict[str, Any]) -> dict[str, Any]:
    """Reduce every tool entry to the only two things detection reads."""
    minimal = copy.deepcopy(doc)
    for context in minimal["contexts"]:
        context["tools"] = [
            {"server": entry["server"], "tool": {"name": entry["tool"]["name"]}}
            for entry in context["tools"]
        ]
    return minimal


def test_an_inventory_carrying_only_names_yields_the_same_findings(
    tmp_path: Path,
) -> None:
    """The load-bearing test: `{server, tool: {name}}` is genuinely enough.

    Descriptions and `inputSchema`s are recorded verbatim for the human who will
    audit the artifact, and read by no detector — DECISIONS.md F2 is exactly the
    finding that schemas cannot constrain reachability, so nothing downstream *could*
    consume them. This test is what lets the README tell someone with a hosted MCP
    server to assemble an inventory by hand: it demonstrates the result is identical,
    rather than asserting the cost is low and leaving them to find out.
    """
    minimal = _strip_to_names(_captured())
    schema = _schema()
    assert _validate(minimal, schema, schema) == []

    full_stack = label_inventory(load_inventory(INVENTORY))
    lean_stack = label_inventory(load_inventory(_write(tmp_path, minimal)))

    for detect in (detect_posture, detect_reachable):
        full = [json.loads(f.to_json_line()) for f in detect(full_stack)]
        lean = [json.loads(f.to_json_line()) for f in detect(lean_stack)]
        assert full, f"{detect.__name__} found nothing on the real inventory"
        assert lean == full, (
            f"{detect.__name__} disagrees between the full captured inventory and one "
            "carrying only server + tool name. The published contract promises these "
            "are equivalent; if they are not, the contract is wrong."
        )


# --- (4) the prose companion cannot silently drift from the schema ----------


def test_the_spec_points_at_the_published_schema() -> None:
    """SPEC.md §7 is the prose contract; the schema file is the machine one."""
    spec = SPEC.read_text(encoding="utf-8")
    assert "schema/inventory.schema.json" in spec, (
        "SPEC.md §7 does not point at the published inventory schema"
    )
