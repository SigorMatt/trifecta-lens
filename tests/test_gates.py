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


def test_honesty_gate_detects_banned_tokens() -> None:
    """The scanner itself must catch each banned form, or the gate rots."""
    assert banned_tokens_in("tainted data observed reaching webhook") == []
    assert banned_tokens_in("An attacker did this") == ["attack"]
    assert banned_tokens_in("Exfiltration  occurred here") == ["Exfiltration  occurred"]
    assert banned_tokens_in("the fetch caused the leak") == ["caused"]
    assert banned_tokens_in("this run was exploited") == ["exploit"]
    # "because" contains no banned token; word boundaries matter
    assert banned_tokens_in("because of the cause") == []


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
