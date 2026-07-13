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
import re
from pathlib import Path
from typing import Any

import pytest

from tests.test_gates import banned_tokens_in
from trifecta_capture.inventory_build import (
    NO_NOTE,
    CaptureConfigError,
    build_inventory,
    load_host_config,
    load_tools_list,
    merge_servers,
    resolve_contexts,
    supplied_servers,
)
from trifecta_lens.catalog import default_catalog, parse_catalog
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


# And a server their host does NOT launch: a hosted wiki, reached over HTTP. It has no
# command, so trifecta-capture cannot start it — the operator fetches its tools/list
# themselves and hands us the file (DECISIONS.md D11). Shaped as the JSON-RPC result an
# operator would actually have saved.
WIKI_TOOLS: dict[str, list[dict[str, Any]]] = {
    "tools": [
        {"name": "publish_page", "description": "publish a page to the company wiki"},
        {"name": "read_page", "description": "read a wiki page"},
    ]
}

# Their own labels for their own stack — the documented extension point. The engine is
# not recompiled and learns no tool name (CONTRIBUTING.md).
CATALOG_WITH_WIKI = default_catalog().overlaid_with(
    parse_catalog(
        """
version: 1
entries:
  - id: acme.wiki.publish
    match: {tool: "wiki__publish_page"}
    role: sink
    subtype: exfil
    note: "publishes a page to the company-wide wiki, readable by everyone"
""",
        source="test overlay",
    )
)


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

    inventory_json = build_inventory(
        contexts, STRANGER_TOOLS, servers, config_path=".mcp.json"
    )
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
    inventory_json = build_inventory(
        contexts, STRANGER_TOOLS, servers, config_path=".mcp.json"
    )
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
        resolve_contexts(servers, [], {}),
        STRANGER_TOOLS,
        servers,
        config_path=".mcp.json",
    )
    provenance = silent["contexts"][0]["provenance"]
    assert NO_NOTE in provenance
    assert "does not know what this context is for" in provenance
    assert "Captured by trifecta-capture from .mcp.json" in provenance

    spoken = build_inventory(
        resolve_contexts(servers, ["a=fetch"], {"a": "our read-only research agent"}),
        STRANGER_TOOLS,
        servers,
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


# --- D11: the servers we cannot launch ---------------------------------------
# trifecta-capture speaks stdio. A remote or hosted MCP server has no command to
# run, and for a whole class of stacks that used to be the end of the road. It is
# not: a tools/list response from a real running server is a capture whoever
# fetched it. These tests hold that path to the same bar as the one we drive.


def _tools_file(tmp_path: Path, name: str, payload: Any) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_server_we_cannot_launch_points_at_the_way_through(tmp_path: Path) -> None:
    """The stdio limit is real. Meeting it must not read like a dead end."""
    path = tmp_path / "remote.json"
    path.write_text(
        json.dumps({"mcpServers": {"hosted": {"url": "https://mcp.example.com/sse"}}}),
        encoding="utf-8",
    )
    with pytest.raises(CaptureConfigError, match="--from-tools-list hosted=") as exc:
        load_host_config(path)
    assert "not a dead end" in str(exc.value)


def test_the_shapes_an_operator_will_actually_be_holding_all_parse(
    tmp_path: Path,
) -> None:
    """We do not control how they fetched it, and no honesty rides on the envelope.

    A raw JSON-RPC response, the result object alone, or the bare array — all mean the
    same thing. What we will NOT do is dig a tool list out of a shape we do not
    recognise: guessing wrong there would put a tool in the inventory that no server
    listed, which is the one thing that must never happen.
    """
    tools = [{"name": "search", "description": "search the wiki"}]
    for label, payload in (
        ("result object", {"tools": tools}),
        ("full JSON-RPC", {"jsonrpc": "2.0", "id": 1, "result": {"tools": tools}}),
        ("bare array", tools),
    ):
        parsed = load_tools_list(
            _tools_file(tmp_path, f"{label.replace(' ', '_')}.json", payload),
            server="wiki",
        )
        assert parsed == tools, label

    for label, payload in (
        ("no tools anywhere", {"servers": []}),
        ("a tool with no name", {"tools": [{"description": "nameless"}]}),
    ):
        with pytest.raises(CaptureConfigError):
            load_tools_list(
                _tools_file(tmp_path, f"bad_{label.replace(' ', '_')}.json", payload),
                server="wiki",
            )


def test_a_server_supplied_twice_or_from_two_sources_fails_rather_than_guessing(
    tmp_path: Path,
) -> None:
    """We will not silently prefer a file over the server itself, or the reverse.

    They can disagree — a config drifts, a file goes stale — and picking one quietly
    would make the inventory describe a stack that does not exist.
    """
    servers = load_host_config(_config_file(tmp_path))
    with pytest.raises(CaptureConfigError, match="both launchable"):
        merge_servers(servers, supplied_servers(["fetch=fetch-tools.json"]))
    with pytest.raises(CaptureConfigError, match="given twice"):
        supplied_servers(["wiki=a.json", "wiki=b.json"])
    with pytest.raises(CaptureConfigError, match=re.escape("<server>=<file.json>")):
        supplied_servers(["wiki"])


def test_a_mixed_stack_captures_and_the_analyzer_reads_it(tmp_path: Path) -> None:
    """The realistic shape: some servers local, some hosted. Both, one inventory.

    The hosted `wiki` publishes pages company-wide — an outbound leg — so the context
    holding it, the vault and fetch is exactly the trifecta topology. The point of the
    test is that a leg supplied from a file counts the same as one we launched for: the
    analyzer joins on tool identity and has no idea, nor any business knowing.
    """
    servers = merge_servers(
        load_host_config(_config_file(tmp_path)),
        supplied_servers([f"wiki={_tools_file(tmp_path, 'wiki.json', WIKI_TOOLS)}"]),
    )
    contexts = resolve_contexts(servers, ["assistant=fetch,vault,wiki"], {})
    listed = {
        **STRANGER_TOOLS,
        "wiki": load_tools_list(servers["wiki"].tools_list_path or "", server="wiki"),
    }
    inventory_json = build_inventory(
        contexts, listed, servers, config_path=str(_config_file(tmp_path))
    )
    stack = label_inventory(_loaded(inventory_json, tmp_path), CATALOG_WITH_WIKI)

    reachable = tuple(detect_reachable(stack))
    assert {f.context for f in reachable} == {"assistant"}
    sinks = {f.sink_tool for f in reachable}
    assert sinks == {"wiki__publish_page"}, (
        "the outbound leg came from a file the operator handed us, and it is a leg "
        f"like any other: {sinks}"
    )


def test_the_provenance_note_never_claims_we_launched_a_server_we_did_not(
    tmp_path: Path,
) -> None:
    """The one place a capture tool can lie without touching a single tool name.

    "Launched over stdio and recorded verbatim" is a claim about what WE did. Said of
    a file the operator handed us, it is a fabrication — small, invisible, and sitting
    in the exact field a reader consults to decide whether to believe the rest of the
    artifact. So the two sources get two sentences, and the supplied one disclaims what
    it cannot attest to (DECISIONS.md D11).
    """
    servers = merge_servers(
        load_host_config(_config_file(tmp_path)),
        supplied_servers([f"wiki={_tools_file(tmp_path, 'wiki.json', WIKI_TOOLS)}"]),
    )
    listed = {**STRANGER_TOOLS, "wiki": WIKI_TOOLS["tools"]}

    # A context whose servers we ALL launched: no disclaimer to make.
    launched = build_inventory(
        resolve_contexts(servers, ["local=fetch,vault"], {}),
        listed,
        servers,
        config_path=".mcp.json",
    )["contexts"][0]["provenance"]
    assert "were launched over stdio" in launched
    assert "did NOT launch" not in launched

    # A context that is ONLY a supplied server: we must claim nothing at all.
    supplied = build_inventory(
        resolve_contexts(servers, ["hosted=wiki"], {}),
        listed,
        servers,
        config_path=".mcp.json",
    )["contexts"][0]["provenance"]
    assert "launched over stdio" not in supplied, (
        "the note claims we launched a server we were handed a file for"
    )
    assert "did NOT launch that server" in supplied
    assert "cannot attest to how the response was obtained" in supplied
    assert "invented none" in supplied

    # Mixed: both claims, each about the servers it is true of, neither borrowing
    # the other's standing.
    mixed = build_inventory(
        resolve_contexts(servers, ["assistant=fetch,vault,wiki"], {}),
        listed,
        servers,
        config_path=".mcp.json",
    )["contexts"][0]["provenance"]
    assert "fetch, vault were launched over stdio" in mixed
    assert "The tools for wiki was supplied by the operator" in mixed
    assert "did NOT launch that server" in mixed
