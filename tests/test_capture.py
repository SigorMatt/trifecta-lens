"""Task 3.6: the capture step a STRANGER runs against their own MCP config.

``demo/capture_inventory.py`` captures *our* demo topology — it is hard-wired to
the three reference servers, which is right for the fixture's provenance and
useless to anyone else. The Phase 3 exit ("a stranger runs it on their own agent")
needs a capture that reads **their** host config. That is ``trifecta-capture``.

The transport half needs real servers, so it is not unit-testable here. The half
that decides **the shape of the artifact the analyzer depends on** is pure, and it
is tested here — including the property that matters most: the inventory this
writes is the inventory the analyzer reads. The two are joined by an executable
round-trip, not by two modules agreeing in prose.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.test_gates import banned_tokens_in
from trifecta_capture.inventory_build import (
    NO_NOTE,
    CaptureConfigError,
    build_inventory,
    load_host_config,
    resolve_contexts,
)
from trifecta_lens.catalog import default_catalog
from trifecta_lens.engine import detect_posture, detect_reachable, reachable_collapse
from trifecta_lens.inventory import load_inventory
from trifecta_lens.labeling import label_inventory

# A stranger's config: the file their MCP host already loads. Launch config only —
# no tool list anywhere in it, which is the whole reason a capture step exists
# (DECISIONS.md F1).
STRANGER_CONFIG: dict[str, Any] = {
    "mcpServers": {
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
        },
        "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
        "vault": {"command": "vault-mcp", "args": [], "env": {"VAULT_ADDR": "x"}},
    }
}

# What their servers would return from tools/list, verbatim-shaped.
STRANGER_TOOLS: dict[str, list[dict[str, Any]]] = {
    "github": [
        {"name": "get_issue", "description": "read an issue"},
        {"name": "create_comment", "description": "comment on an issue"},
    ],
    "fetch": [{"name": "fetch", "description": "fetch a URL"}],
    "vault": [{"name": "read_secret", "description": "read a secret"}],
}


def _config_file(tmp_path: Path) -> Path:
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(STRANGER_CONFIG), encoding="utf-8")
    return path


def test_the_host_config_parses_into_launch_specs(tmp_path: Path) -> None:
    servers = load_host_config(_config_file(tmp_path))
    assert sorted(servers) == ["fetch", "github", "vault"]
    assert servers["fetch"].command == "uvx"
    assert servers["fetch"].args == ("mcp-server-fetch",)
    assert servers["vault"].env == {"VAULT_ADDR": "x"}


def test_a_config_with_no_servers_fails_loudly(tmp_path: Path) -> None:
    """Guessing a topology is worse than refusing to produce one."""
    path = tmp_path / "empty.json"
    path.write_text('{"other": {}}', encoding="utf-8")
    with pytest.raises(CaptureConfigError, match="mcpServers"):
        load_host_config(path)


def test_the_default_is_one_context_and_that_is_the_honest_default(
    tmp_path: Path,
) -> None:
    """One host config is one agent context unless the operator says otherwise.

    It is also the collapse case: reachable can only restate posture. We do not
    dodge that by inventing a partition — the CLI warns, and the analyzer discloses
    it in the finding itself (DECISIONS.md D1).
    """
    servers = load_host_config(_config_file(tmp_path))
    contexts = resolve_contexts(servers, [], {})
    assert len(contexts) == 1
    assert contexts[0].servers == ("fetch", "github", "vault")

    inventory_json = build_inventory(contexts, STRANGER_TOOLS, config_path=".mcp.json")
    stack = label_inventory(
        _loaded(inventory_json, tmp_path), default_catalog()
    )
    collapse = reachable_collapse(stack)
    assert collapse.collapsed is True


def test_declared_contexts_give_reachable_something_to_say(tmp_path: Path) -> None:
    """The real product of the middle tier: one context could wire it, one cannot.

    The stranger's triage subagent reads web content (untrusted) and secrets
    (sensitive) but is exposed to no outbound tool. Posture cannot see that
    distinction; reachable can.

    Note what is NOT in the triage context: `github`. Its `create_comment` is a
    `sink:exfil` — writing into a public thread publishes the payload as surely as a
    POST does, and the default catalog says so. Giving a "read-only" triage agent the
    GitHub server would hand it an outbound leg, which is precisely the shape of the
    GitHub-MCP incident in `INCIDENTS.md`. The first draft of this test made that
    mistake and the detector caught it, which is the tier doing its job.
    """
    servers = load_host_config(_config_file(tmp_path))
    contexts = resolve_contexts(
        servers,
        ["assistant=github,fetch,vault", "triage=fetch,vault"],
        {"triage": "our issue-triage subagent; deliberately has no outbound tool"},
    )
    inventory_json = build_inventory(contexts, STRANGER_TOOLS, config_path=".mcp.json")
    stack = label_inventory(_loaded(inventory_json, tmp_path), default_catalog())

    reachable = tuple(detect_reachable(stack))
    posture = tuple(detect_posture(stack))
    assert posture, "the union holds all three legs"
    assert {f.context for f in reachable} == {"assistant"}, (
        "only the context with an outbound leg could wire it"
    )

    collapse = reachable_collapse(stack)
    assert collapse.collapsed is False
    assert collapse.narrowed_contexts == ("triage",)


def _loaded(inventory_json: dict[str, Any], tmp_path: Path) -> Any:
    """Write the artifact and load it back with the ANALYZER's own loader.

    The round-trip is the point: the capture tool and the analyzer are separate
    packages that must agree on one file format, and the only way to know they do
    is to make the analyzer read what the capture writes.
    """
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory_json, sort_keys=True, indent=2), "utf-8")
    return load_inventory(path)


def test_the_capture_never_writes_a_note_in_the_operators_voice(tmp_path: Path) -> None:
    """D2 wants a HUMAN provenance note. We will not fake one.

    With no --note, the artifact says a note is missing — it does not describe the
    context. A machine-written sentence that reads like an operator's is a small
    fabrication, and this project's entire moat is not committing those. With a
    --note, the operator's words come first, in their voice, and the method
    sentence that follows describes only what the machine did.
    """
    servers = load_host_config(_config_file(tmp_path))

    silent = build_inventory(
        resolve_contexts(servers, [], {}), STRANGER_TOOLS, config_path=".mcp.json"
    )
    provenance = silent["contexts"][0]["provenance"]
    assert NO_NOTE in provenance
    assert "does not know what this context is for" in provenance
    assert "Captured by trifecta-capture from .mcp.json" in provenance

    spoken = build_inventory(
        resolve_contexts(servers, ["a=fetch"], {"a": "our read-only research agent"}),
        STRANGER_TOOLS,
        config_path=".mcp.json",
    )
    said = spoken["contexts"][0]["provenance"]
    assert said.startswith("our read-only research agent")
    assert NO_NOTE not in said


def test_a_typo_in_a_context_declaration_fails_rather_than_silently_shrinking(
    tmp_path: Path,
) -> None:
    """A context that silently loses a server would UNDER-report reachability."""
    servers = load_host_config(_config_file(tmp_path))
    with pytest.raises(CaptureConfigError, match="not in the config"):
        resolve_contexts(servers, ["assistant=github,githbu"], {})
    with pytest.raises(CaptureConfigError, match="<id>=<server>"):
        resolve_contexts(servers, ["assistant"], {})
    with pytest.raises(CaptureConfigError, match="undeclared context"):
        resolve_contexts(servers, ["a=fetch"], {"b": "note for a context I never made"})


def test_the_capture_package_carries_no_causal_or_attack_language() -> None:
    """Its prose reaches the report: the provenance note is printed verbatim."""
    for module in sorted(Path("trifecta_capture").rglob("*.py")):
        assert not banned_tokens_in(module.read_text(encoding="utf-8")), module
