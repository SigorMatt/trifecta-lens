"""Task 0.8: honesty + architecture gates (CLAUDE.md invariants 4 and 2).

Gate A (honesty): no string literal in the core package — the material report
text is built from — may contain a causal/attack token. Realized findings say
"tainted data observed reaching <sink>", never that an attack happened or
that untrusted content caused anything. When report rendering lands (Phase 1)
this gate additionally runs over the rendered report text.

Gate B (architecture): detection is one engine over role-labeled data; new
coverage is catalog entries, never per-tool code. The gate fails on any
comparison of a tool-ish expression against a string literal
(``if tool == "webhook"``, ``event.tool in {"fetch", "vault"}``, ...).
"""

import ast
import re
from pathlib import Path

CORE_PACKAGE = Path(__file__).resolve().parent.parent / "trifecta_lens"

# Causal/attack language banned from report text (CLAUDE.md invariant 4).
BANNED_TOKEN_PATTERNS = (
    r"\battack",  # attack, attacks, attacker, attacked
    r"exfiltration\s+occurred",
    r"\bcaused\b",
    r"\bexploit",  # exploit, exploited, exploitation
)
_BANNED = [re.compile(p, re.IGNORECASE) for p in BANNED_TOKEN_PATTERNS]

_TOOL_BRANCH_OPS = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)

# --- Task 2.3 (DECISIONS.md D6): the gate learns the DESIGN §5 stage seam. ---
#
# Gate B caught `if tool == "webhook"` but was blind to a per-tool DICT TABLE.
# A contributor could put {"webhook": ..., "vault": ...} straight into the engine
# and the gate would stay green — while that is precisely the "per-path code" that
# CLAUDE.md invariant 2 forbids.
#
# The boundary the gate should always have been policing is the two-stage seam:
#
#   STAGE 1 (construction / front-end) — MAY key on tool names. This is where the
#   labeling function lives, and naming tools IS its job. Coverage is data here.
#
#   STAGE 2 (the engine) — MUST NOT. It sees roles only. It must be impossible to
#   extend coverage by editing it, which is what makes "catalog, not per-path
#   code" a structural property rather than a habit.
STAGE_1_MODULES = frozenset(
    {
        "loader.py",  # raw spans -> Events
        "catalog.py",  # the catalog: the labeling rules, tool-name-keyed BY DESIGN
        "labeling.py",  # the labeling function (applies the catalog to events)
        "inventory.py",  # inventory JSON -> topology (front-end; tool-name-keyed)
    }
)
STAGE_2_MODULES = frozenset(
    {
        "engine.py",  # the automaton
        "taint.py",  # value extraction + matching: keyed on ROLES and payloads
        "findings.py",  # the findings contract
        "report.py",  # rendering
        "svg.py",  # rendering
    }
)


def banned_tokens_in(text: str) -> list[str]:
    """Return every banned causal/attack token found in ``text``."""
    return [m.group(0) for pattern in _BANNED for m in pattern.finditer(text)]


def _string_literals(tree: ast.AST) -> list[tuple[int, str]]:
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _is_string_const(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return bool(node.elts) and all(_is_string_const(e) for e in node.elts)
    return False


def _mentions_tool(node: ast.expr) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and "tool" in sub.id.lower():
            return True
        if isinstance(sub, ast.Attribute) and "tool" in sub.attr.lower():
            return True
    return False


def per_tool_branches_in(tree: ast.AST) -> list[int]:
    """Line numbers of comparisons between a tool expression and a literal."""
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, _TOOL_BRANCH_OPS) for op in node.ops):
            continue
        sides = [node.left, *node.comparators]
        if any(_is_string_const(s) for s in sides) and any(
            _mentions_tool(s) for s in sides
        ):
            hits.append(node.lineno)
    return hits


def tool_lookups_in(tree: ast.AST) -> list[int]:
    """Line numbers where a tool expression is used as a LOOKUP KEY.

    This is the hole the old gate left open. It caught ``if tool == "webhook"``,
    but a per-tool **table** — ``_SINK_TOOLS = {"webhook": ...}`` consulted as
    ``_SINK_TOOLS[event.tool]`` — sailed straight through, while being exactly the
    per-path code invariant 2 forbids.

    Flagging the *table* is the wrong move: a tool-keyed table is the labeling
    function's entire job, and a table nobody looks up is harmless. What must never
    happen is the **engine looking a tool up in one**. So we flag the lookup:

        TOOL_TABLE[event.tool]        -> subscript keyed by a tool expression
        TOOL_TABLE.get(event.tool)    -> .get()/.pop() keyed by a tool expression

    Together with the comparison gate, this closes the loop: in Stage 2 you can
    neither branch on a tool name nor look one up. The engine cannot learn what a
    "webhook" is, which is what makes "catalog, not per-path code" structural
    rather than a habit.
    """
    hits: list[int] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript) and _mentions_tool(node.slice)) or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "pop", "setdefault"}
            and node.args
            and _mentions_tool(node.args[0])
        ):
            hits.append(node.lineno)
    return hits


def _core_trees() -> dict[str, ast.AST]:
    files = sorted(CORE_PACKAGE.rglob("*.py"))
    assert files, f"no core sources found under {CORE_PACKAGE}"
    return {
        str(p.relative_to(CORE_PACKAGE.parent)): ast.parse(
            p.read_text(encoding="utf-8"), filename=str(p)
        )
        for p in files
    }


def test_no_causal_or_attack_language_in_core_text() -> None:
    offenders: dict[str, list[str]] = {}
    for path, tree in _core_trees().items():
        for lineno, literal in _string_literals(tree):
            found = banned_tokens_in(literal)
            if found:
                offenders.setdefault(path, []).append(f"line {lineno}: {found}")
    assert not offenders, (
        f"banned causal/attack language in core text: {offenders}. "
        "CLAUDE.md invariant 4: we observe flow; we do not prove intent."
    )


def test_no_per_tool_branches_in_core() -> None:
    offenders = {
        path: hits for path, tree in _core_trees().items()
        if (hits := per_tool_branches_in(tree))
    }
    assert not offenders, (
        f"per-tool branches in detection core (lines): {offenders}. "
        "CLAUDE.md invariant 2: coverage goes in the catalog, not the code."
    )


def test_no_causal_or_attack_language_in_rendered_output() -> None:
    """The gate promised in this module's docstring, now that rendering exists.

    Scanning core's string literals is not enough: the text a user actually reads
    is assembled at runtime. Scan the real rendered artifacts — the human report
    and the findings NDJSON — for every fixture we ship.
    """
    import json
    from pathlib import Path

    from trifecta_lens.engine import detect_realized
    from trifecta_lens.labeling import label_events
    from trifecta_lens.loader import load_trace
    from trifecta_lens.report import format_report

    fixture_dir = Path(__file__).resolve().parent.parent / "fixtures"
    fixtures = sorted(fixture_dir.glob("*.jsonl"))
    assert fixtures, "no fixtures to scan"

    for fixture in fixtures:
        events = label_events(load_trace(fixture))
        findings = list(detect_realized(events))

        report = format_report(findings, events)
        assert not banned_tokens_in(report), f"{fixture.name} report: {report}"

        for finding in findings:
            line = finding.to_json_line()
            assert not banned_tokens_in(line), f"{fixture.name} finding: {line}"
            # The masked value is the only form a value may take in output.
            assert "sk-demo-trifecta-lens-DO-NOT-USE-0000" not in line
            assert "sk-demo-trifecta-lens-DO-NOT-USE-0000" not in report
            json.loads(line)


def test_honesty_gate_detects_banned_tokens() -> None:
    """The scanner itself must catch each banned form, or the gate rots."""
    assert banned_tokens_in("tainted data observed reaching webhook") == []
    assert banned_tokens_in("An attacker did this") == ["attack"]
    assert banned_tokens_in("Exfiltration  occurred here") == ["Exfiltration  occurred"]
    assert banned_tokens_in("the fetch caused the leak") == ["caused"]
    assert banned_tokens_in("this run was exploited") == ["exploit"]
    # "because" contains no banned token; word boundaries matter
    assert banned_tokens_in("because of the cause") == []


def test_stage_2_never_looks_up_a_tool() -> None:
    """The engine sees ROLES, never tool names (DECISIONS.md D6, DESIGN.md §5)."""
    offenders: dict[str, list[int]] = {}
    for path, tree in _core_trees().items():
        module = Path(path).name
        if module not in STAGE_2_MODULES:
            continue
        if hits := tool_lookups_in(tree):
            offenders[path] = hits
    assert not offenders, (
        f"Stage-2 module looks a tool up in a table (lines): {offenders}. "
        "The engine must not learn tool names — that is the labeling function's "
        "job (Stage 1). CLAUDE.md invariant 2; DESIGN.md §5."
    )


def test_the_stage_seam_is_fully_covered() -> None:
    """Every core module is classified. A new one cannot slip in unpoliced."""
    modules = {
        Path(p).name
        for p in _core_trees()
        if Path(p).name not in {"__init__.py"}
    }
    classified = STAGE_1_MODULES | STAGE_2_MODULES | {
        "model.py",  # pure data
        "roles.py",  # the alphabet
        "extraction.py",  # declared parameters
        "cli.py",  # wiring
    }
    assert modules <= classified, (
        f"unclassified core module(s): {modules - classified}. "
        "Assign each to Stage 1 or Stage 2 so the gate polices it."
    )


def test_gate_catches_a_tool_table_planted_in_the_engine() -> None:
    """The gate must fail on the exact smuggling it exists to stop."""
    smuggled = ast.parse(
        'SINK_TOOLS = {"webhook": "exfil", "slack": "exfil"}\n'
        "def accept(event):\n"
        "    return SINK_TOOLS[event.tool]\n"
    )
    assert tool_lookups_in(smuggled), "the gate must catch a per-tool table lookup"

    smuggled_get = ast.parse(
        "def accept(event):\n"
        "    return SINK_TOOLS.get(event.tool, None)\n"
    )
    assert tool_lookups_in(smuggled_get)


def test_gate_permits_the_legitimate_table_in_stage_1() -> None:
    """The catalog IS tool-name-keyed, by design. The gate must not flag it.

    This is the asymmetry the old gate could not express: the same tool-keyed
    lookup is correct in Stage 1 and forbidden in Stage 2. Matching tool names is
    the labeling function's entire job (task 2.8 moved the rules into a data file,
    which does not change the principle — it is what the principle was for).
    """
    for module in ("catalog.py", "labeling.py"):
        assert module in STAGE_1_MODULES
        assert module not in STAGE_2_MODULES


def test_architecture_gate_detects_per_tool_branches() -> None:
    flagged = {
        'if tool == "webhook": pass',
        'if event.tool != "vault": pass',
        'if tool in ("fetch", "vault"): pass',
        'x = "webhook" == tool',
    }
    clean = {
        "if tool == other_tool: pass",  # variable vs variable is fine
        "if tool is None: pass",
        'if mime == "application/json": pass',  # not a tool comparison
        'name = attributes.get("tool.name")',  # lookup, not a branch
    }
    for snippet in flagged:
        assert per_tool_branches_in(ast.parse(snippet)), snippet
    for snippet in clean:
        assert not per_tool_branches_in(ast.parse(snippet)), snippet
