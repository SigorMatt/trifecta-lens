"""Task 0.4: the "no network in core" guard (CLAUDE.md invariant 1).

The analyzer core must never open a network connection. This gate fails the
build if any module under the core package imports a network-capable module,
whether via ``import x``, ``import x.y``, ``from x import y``, or
``from x.y import z``.
"""

import ast
from pathlib import Path

CORE_PACKAGE = Path(__file__).resolve().parent.parent / "trifecta_lens"

BANNED_MODULES = frozenset(
    {
        "requests",
        "httpx",
        "aiohttp",
        "socket",
        "urllib.request",
        "http.client",
        "ftplib",
        "smtplib",
    }
)


def _is_banned(name: str) -> bool:
    return any(name == b or name.startswith(b + ".") for b in BANNED_MODULES)


def banned_imports_in(tree: ast.AST) -> list[str]:
    """Return every banned module imported anywhere in ``tree``."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(a.name for a in node.names if _is_banned(a.name))
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if _is_banned(module):
                found.append(module)
            else:
                found.extend(
                    f"{module}.{a.name}"
                    for a in node.names
                    if _is_banned(f"{module}.{a.name}")
                )
    return found


def core_source_files() -> list[Path]:
    files = sorted(CORE_PACKAGE.rglob("*.py"))
    assert files, f"no core sources found under {CORE_PACKAGE}"
    return files


def test_core_has_no_network_imports() -> None:
    offenders: dict[str, list[str]] = {}
    for path in core_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found = banned_imports_in(tree)
        if found:
            offenders[str(path.relative_to(CORE_PACKAGE.parent))] = found
    assert not offenders, (
        f"network-capable imports found in the analysis core: {offenders}. "
        "CLAUDE.md invariant 1: the core never opens a network connection."
    )


def test_guard_detects_each_import_form() -> None:
    """The scanner itself must catch every import spelling, or the gate rots."""
    snippets = {
        "import requests": ["requests"],
        "import urllib.request": ["urllib.request"],
        "from urllib import request": ["urllib.request"],
        "from urllib.request import urlopen": ["urllib.request"],
        "import httpx as hx": ["httpx"],
        "from socket import create_connection": ["socket"],
        "import json": [],
        "from urllib.parse import urlparse": [],
        "from . import request": [],  # relative import, in-package
    }
    for snippet, expected in snippets.items():
        assert banned_imports_in(ast.parse(snippet)) == expected, snippet
