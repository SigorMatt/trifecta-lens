"""Task 3.3: the findings NDJSON schema is a **frozen public contract**.

The NDJSON append-stream is public API (SPEC.md §7.1). Three things must never
drift apart without a deliberate, reviewed version bump:

1. what the code actually emits (`Finding.to_dict` / `CapabilityFinding.to_dict`),
2. the machine-readable contract (`schema/findings.schema.json`),
3. the prose companion (SPEC.md §7.1).

This module pins (1) against a **frozen key set** written out longhand — so a
field added, removed, or renamed in the code fails a test that names it — and
pins (2) against the same frozen set, so the published schema can never quietly
disagree with the code. Then it validates every committed golden line against the
published schema with a tiny stdlib checker, so the schema is a contract we can
prove we honour, not just a document.

To *intend* a schema change: bump `SCHEMA_VERSION`, update
`schema/findings.schema.json`, update the frozen sets below and SPEC.md §7.1, and
regenerate the goldens (`make golden`) — all in one reviewable commit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trifecta_lens.engine import (
    detect_posture,
    detect_reachable,
    detect_realized,
)
from trifecta_lens.findings import (
    SCHEMA_VERSION,
    TIER_POSTURE,
    TIER_REACHABLE,
    TIER_REALIZED,
)
from trifecta_lens.inventory import load_inventory
from trifecta_lens.labeling import label_events, label_inventory
from trifecta_lens.loader import load_trace

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
GOLDEN = FIXTURES / "golden"
SCHEMA_PATH = ROOT / "schema" / "findings.schema.json"

# The full trifecta realized line (all keys populated).
TRIFECTA_TRACE = FIXTURES / "worked_example.jsonl"
INVENTORY = FIXTURES / "inventory.json"

# --- The frozen key sets (the canonical lockfile) ---------------------------

# v1.1 (D15) added `agents` / `crosses_agents` / `legs[].agent`. ADDITIVE — a minor
# bump under SPEC.md §7.1's policy, and consumers that ignore unknown fields are
# unaffected. The fields exist because the engine has ALWAYS detected a flow that
# crossed an agent boundary (it folds one trace with one taint set and no notion of an
# agent) and the finding never said so — while SPEC.md §8 denied it outright.
REALIZED_KEYS = frozenset({
    "schema_version", "tier", "family", "summary", "note", "scope", "sink",
    "path", "path_edges", "path_basis", "legs", "legs_observed",
    "legs_not_observed", "masked_values", "detected_under",
    "agents", "crosses_agents",
})
REALIZED_LEG_KEYS = frozenset({
    "role", "event", "tool", "note", "catalog_entry", "agent",
})
REALIZED_SINK_KEYS = frozenset({"event", "tool"})
PATH_EDGE_KEYS = frozenset({"from", "to", "basis"})
DETECTED_UNDER_KEYS = frozenset({"match", "min_value_chars", "normalization"})

CAPABILITY_KEYS = frozenset({
    "schema_version", "tier", "family", "summary", "note", "scope", "sink",
    "context", "legs", "legs_present", "legs_absent", "disclosure",
})
CAPABILITY_LEG_KEYS = frozenset({"role", "tools"})
CAPABILITY_TOOL_KEYS = frozenset({"tool", "note", "catalog_entry"})
CAPABILITY_SINK_KEYS = frozenset({"tool"})
CONTEXT_KEYS = frozenset({"id", "provenance"})


def _realized_line() -> dict[str, Any]:
    events = tuple(label_events(load_trace(TRIFECTA_TRACE)))
    findings = list(detect_realized(events))
    assert findings, "the trifecta fixture must yield a realized finding"
    return json.loads(findings[0].to_json_line())


def _capability_lines() -> list[dict[str, Any]]:
    stack = label_inventory(load_inventory(INVENTORY))
    findings = [*detect_posture(stack), *detect_reachable(stack)]
    assert findings, "the real inventory must yield capability findings"
    return [json.loads(f.to_json_line()) for f in findings]


# --- (1) the code emits exactly the frozen keys -----------------------------


def test_realized_line_keys_are_frozen() -> None:
    line = _realized_line()
    assert set(line) == REALIZED_KEYS, (
        "the realized NDJSON keys changed. This is a PUBLIC schema (SPEC.md §7.1): "
        "bump SCHEMA_VERSION, update schema/findings.schema.json, this frozen set, "
        "and regenerate goldens — in one commit."
    )
    assert line["schema_version"] == SCHEMA_VERSION
    assert line["tier"] == TIER_REALIZED
    assert set(line["sink"]) == REALIZED_SINK_KEYS
    assert set(line["detected_under"]) == DETECTED_UNDER_KEYS
    for leg in line["legs"]:
        assert set(leg) == REALIZED_LEG_KEYS
    for edge in line["path_edges"]:
        assert set(edge) == PATH_EDGE_KEYS


def test_capability_line_keys_are_frozen() -> None:
    lines = _capability_lines()
    assert {ln["tier"] for ln in lines} == {TIER_POSTURE, TIER_REACHABLE}
    for line in lines:
        assert set(line) == CAPABILITY_KEYS, (
            "the capability NDJSON keys changed. This is a PUBLIC schema "
            "(SPEC.md §7.1): bump SCHEMA_VERSION, update the schema file, this "
            "frozen set, and regenerate goldens — in one commit."
        )
        assert line["schema_version"] == SCHEMA_VERSION
        assert set(line["sink"]) == CAPABILITY_SINK_KEYS
        assert set(line["context"]) == CONTEXT_KEYS
        for leg in line["legs"]:
            assert set(leg) == CAPABILITY_LEG_KEYS
            for tool in leg["tools"]:
                assert set(tool) == CAPABILITY_TOOL_KEYS


def test_a_capability_line_still_cannot_carry_realized_evidence() -> None:
    """The freeze must not have re-opened the door invariant 3 closed (2.10)."""
    for line in _capability_lines():
        for forbidden in ("path", "path_edges", "path_basis", "masked_values",
                          "legs_observed", "legs_not_observed", "detected_under"):
            assert forbidden not in line, f"capability line carries {forbidden!r}"


# --- (2) the published schema agrees with the frozen keys -------------------


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


def test_schema_file_declares_exactly_the_frozen_keys() -> None:
    """The human-readable contract cannot silently disagree with the code."""
    defs = _schema()["$defs"]
    assert set(defs["realized"]["required"]) == REALIZED_KEYS
    assert set(defs["realized"]["properties"]) == REALIZED_KEYS
    assert set(defs["capability"]["required"]) == CAPABILITY_KEYS
    assert set(defs["capability"]["properties"]) == CAPABILITY_KEYS


def test_schema_version_constant_matches_the_schema_file() -> None:
    schema = _schema()
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    for variant in ("realized", "capability"):
        const = schema["$defs"][variant]["properties"]["schema_version"]["const"]
        assert const == SCHEMA_VERSION


# --- (3) every committed golden line conforms to the published schema -------


def _validate(instance: Any, schema: dict[str, Any], root: dict[str, Any],
              path: str = "$") -> list[str]:
    """A minimal stdlib validator for the JSON-Schema subset this repo uses.

    Supports: $ref (to #/$defs/...), oneOf, const, enum, type (incl. lists),
    required, properties, additionalProperties:false, items. Enough to make
    `schema/findings.schema.json` an enforced contract without a third-party
    dependency (the zero-runtime-dep property is itself a feature, pyproject.toml).
    """
    errors: list[str] = []

    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/$defs/"), f"unsupported $ref {ref}"
        return _validate(instance, root["$defs"][ref[len("#/$defs/"):]], root, path)

    if "oneOf" in schema:
        matches = [i for i, sub in enumerate(schema["oneOf"])
                   if not _validate(instance, sub, root, path)]
        if len(matches) != 1:
            errors.append(f"{path}: matched {len(matches)} of oneOf, want exactly 1")
        return errors

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: {instance!r} != const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in {schema['enum']}")

    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        ok = any(_is_type(instance, t) for t in types)
        if not ok:
            errors.append(f"{path}: {type(instance).__name__} not in {types}")
            return errors  # type mismatch makes deeper checks meaningless

    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required {req!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{path}: unexpected property {key!r}")
        for key, sub in props.items():
            if key in instance:
                errors += _validate(instance[key], sub, root, f"{path}.{key}")

    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            errors += _validate(item, schema["items"], root, f"{path}[{i}]")

    return errors


def _is_type(instance: Any, t: str) -> bool:
    if t == "object":
        return isinstance(instance, dict)
    if t == "array":
        return isinstance(instance, list)
    if t == "string":
        return isinstance(instance, str)
    if t == "boolean":
        return isinstance(instance, bool)
    if t == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if t == "null":
        return instance is None
    raise AssertionError(f"unsupported type keyword {t!r}")


def test_the_validator_rejects_a_line_missing_a_required_field() -> None:
    """Guard the guard: a broken line must actually fail, or conformance is hollow."""
    schema = _schema()
    good = _realized_line()
    assert _validate(good, schema, schema) == []
    broken = {k: v for k, v in good.items() if k != "detected_under"}
    assert _validate(broken, schema, schema), "validator passed a line missing a field"
    extra = {**good, "surprise": 1}
    assert _validate(extra, schema, schema), "validator passed a line with an extra key"


def test_every_golden_findings_line_conforms_to_the_published_schema() -> None:
    schema = _schema()
    checked = 0
    for path in sorted(GOLDEN.glob("*.findings.ndjson")):
        for lineno, raw in enumerate(path.read_text().splitlines(), 1):
            if not raw.strip():
                continue
            errors = _validate(json.loads(raw), schema, schema)
            assert not errors, f"{path.name}:{lineno} violates the schema: {errors}"
            checked += 1
    assert checked, "no golden findings lines were checked — the corpus went missing"
