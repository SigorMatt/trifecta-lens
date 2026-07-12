"""Unit tests for the demo provider seam (:mod:`demo.providers`).

These exercise the Ollama adapter's *translation layer* with a FAKE
OpenAI-shaped response — no ``openai`` client, no network, no live Ollama. The
point is to prove the transport swap keeps the loop's internal form intact: an
OpenAI ``tool_calls`` response becomes the same neutral :class:`ToolCall` values
the loop already consumes, and a tool result serializes as a ``role: "tool"``
message. The recorded spans downstream are therefore identical to the Anthropic
path (CLAUDE.md: two provider paths behind one small seam).

Nothing here requires a live endpoint; the Anthropic path stays covered by the
existing harness tests and its real behavior by the human-run ``make demo-live``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from demo import agent, providers, tools


def _fake_openai_response(
    *,
    content: str | None,
    tool_calls: list[SimpleNamespace] | None,
) -> SimpleNamespace:
    """Build an object shaped like an OpenAI chat completion response."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _fake_tool_call(
    *, call_id: str, name: str, arguments: str
) -> SimpleNamespace:
    """A single ``message.tool_calls[]`` entry: id + function(name, arguments)."""
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def test_openai_tool_calls_become_neutral_tool_calls() -> None:
    """A tool_calls response converts to the internal form the loop consumes."""
    response = _fake_openai_response(
        content=None,
        tool_calls=[
            _fake_tool_call(
                call_id="call_1",
                name="read_issue",
                arguments='{"issue_id": "issue-2"}',
            ),
            _fake_tool_call(
                call_id="call_2",
                name="webhook",
                arguments='{"url": "http://localhost:9099/collect", '
                '"body": "API_KEY=sk-demo"}',
            ),
        ],
    )

    turn = providers._assistant_from_openai(response)

    assert isinstance(turn, providers.AssistantMessage)
    assert turn.tool_calls == [
        providers.ToolCall(
            id="call_1",
            name="read_issue",
            arguments={"issue_id": "issue-2"},
        ),
        providers.ToolCall(
            id="call_2",
            name="webhook",
            arguments={
                "url": "http://localhost:9099/collect",
                "body": "API_KEY=sk-demo",
            },
        ),
    ]
    # Arguments are parsed via json.loads into a dict the loop passes to the
    # tool stub verbatim — not left as the JSON string OpenAI delivered.
    assert isinstance(turn.tool_calls[0].arguments, dict)


def test_openai_text_only_response_has_no_tool_calls() -> None:
    """A plain assistant message (tool_calls None) ends the loop cleanly."""
    response = _fake_openai_response(content="all triaged", tool_calls=None)

    turn = providers._assistant_from_openai(response)

    assert turn.text == "all triaged"
    assert turn.tool_calls == []


def test_tool_result_serializes_as_role_tool_message() -> None:
    """A tool result becomes a role:"tool" message keyed by tool_call_id."""
    conversation: list[providers.Message] = [
        providers.UserMessage("triage the issues"),
        providers.AssistantMessage(
            text=None,
            tool_calls=[
                providers.ToolCall(
                    id="call_1", name="read_issue", arguments={"issue_id": "x"}
                )
            ],
        ),
        providers.ToolResultMessage(
            results=[
                providers.ToolResult(
                    call_id="call_1",
                    name="read_issue",
                    content="issue body text",
                )
            ]
        ),
    ]

    rendered = providers._to_openai_messages("SYSTEM", conversation)

    assert rendered[0] == {"role": "system", "content": "SYSTEM"}
    tool_messages = [m for m in rendered if m["role"] == "tool"]
    assert tool_messages == [
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "issue body text",
        }
    ]
    # The assistant turn carries the OpenAI tool_calls envelope the result
    # message pairs back to.
    assistant = next(m for m in rendered if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert assistant["tool_calls"][0]["function"]["name"] == "read_issue"


def test_tool_schemas_translate_to_openai_function_specs() -> None:
    """input_schema is carried through verbatim as the function parameters."""
    schema = {
        "name": "read_issue",
        "description": "Read one issue by id.",
        "input_schema": {
            "type": "object",
            "properties": {"issue_id": {"type": "string"}},
            "required": ["issue_id"],
        },
    }

    tools_spec = providers._to_openai_tools([schema])

    assert tools_spec == [
        {
            "type": "function",
            "function": {
                "name": "read_issue",
                "description": "Read one issue by id.",
                "parameters": schema["input_schema"],
            },
        }
    ]


def test_empty_arguments_parse_to_empty_dict() -> None:
    """Ollama may return an empty argument string for a no-arg tool."""
    assert providers._parse_arguments("") == {}
    assert providers._parse_arguments(None) == {}
    assert providers._parse_arguments("{}") == {}


def test_build_provider_selects_transport() -> None:
    anthropic_provider = providers.build_provider(
        endpoint="anthropic", model="claude-sonnet-5", max_tokens=1024
    )
    ollama_provider = providers.build_provider(
        endpoint="ollama", model="mistral:7b", max_tokens=1024
    )
    # ollama and hf are the same OpenAI-compatible adapter, differently pointed.
    hf_provider = providers.build_provider(
        endpoint="hf",
        model="meta-llama/Llama-3.3-70B-Instruct",
        max_tokens=1024,
        hf_api_key="hf_token",
    )
    assert isinstance(anthropic_provider, providers.AnthropicProvider)
    assert isinstance(ollama_provider, providers.OpenAICompatibleProvider)
    assert isinstance(hf_provider, providers.OpenAICompatibleProvider)


def test_build_provider_rejects_unknown_endpoint() -> None:
    with pytest.raises(ValueError, match="unknown DEMO_ENDPOINT"):
        providers.build_provider(
            endpoint="openai", model="gpt", max_tokens=1024
        )


def test_hf_endpoint_requires_a_token() -> None:
    """The HF router needs a real bearer token; building without one fails fast."""
    with pytest.raises(ValueError, match="hf endpoint requires an API token"):
        providers.build_provider(
            endpoint="hf",
            model="meta-llama/Llama-3.3-70B-Instruct",
            max_tokens=1024,
        )


def _install_fake_openai(
    monkeypatch: pytest.MonkeyPatch, response: SimpleNamespace
) -> dict[str, Any]:
    """Install a fake ``openai`` module that records the ``OpenAI(...)`` kwargs
    and the ``chat.completions.create`` call, returning ``response``.

    No network and no real ``openai`` package (unavailable under the plain dev
    extra the gate installs): the provider's lazy ``from openai import OpenAI``
    resolves to this stub.
    """
    captured: dict[str, Any] = {}

    class _Completions:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            captured["create_kwargs"] = kwargs
            return response

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _OpenAI:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            self.chat = _Chat()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=_OpenAI))
    return captured


def test_hf_endpoint_drives_router_and_parses_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DEMO_ENDPOINT=hf reuses the OpenAI-compatible adapter.

    The client is built against the HF router base_url with the HF token, the
    requested model id is forwarded, and a tool_calls response parses to the
    same neutral ``ToolCall`` form as the ollama path — one shared translation.
    """
    response = _fake_openai_response(
        content=None,
        tool_calls=[
            _fake_tool_call(
                call_id="call_1",
                name="vault",
                arguments='{"path": "secret.txt"}',
            )
        ],
    )
    captured = _install_fake_openai(monkeypatch, response)

    provider = providers.build_provider(
        endpoint="hf",
        model="meta-llama/Llama-3.3-70B-Instruct",
        max_tokens=1024,
        hf_api_key="hf_secret_token",
    )
    assert isinstance(provider, providers.OpenAICompatibleProvider)

    turn = provider.complete(
        system_prompt="SYSTEM",
        messages=[providers.UserMessage("read the key")],
        tool_schemas=[
            {
                "name": "vault",
                "description": "Read a secret.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            }
        ],
    )

    # The client was constructed against the HF router with the bearer token.
    assert captured["base_url"] == providers.DEFAULT_HF_BASE_URL
    assert captured["api_key"] == "hf_secret_token"
    # ...and the model id we requested was forwarded on the request.
    assert (
        captured["create_kwargs"]["model"]
        == "meta-llama/Llama-3.3-70B-Instruct"
    )
    # tool_calls parse to the same neutral form the loop consumes for ollama.
    assert turn.tool_calls == [
        providers.ToolCall(
            id="call_1", name="vault", arguments={"path": "secret.txt"}
        )
    ]


def test_null_string_arguments_dispatch_as_empty_dict() -> None:
    """A no-arg tool call may arrive as ``"null"`` (observed HF -> Groq).

    It must coerce to ``{}`` and dispatch cleanly, not crash — both at the
    low-level parser and through the full assistant translation the loop uses.
    """
    assert providers._parse_arguments("null") == {}

    response = _fake_openai_response(
        content=None,
        tool_calls=[
            _fake_tool_call(
                call_id="call_9", name="list_issues", arguments="null"
            )
        ],
    )
    turn = providers._assistant_from_openai(response)
    assert turn.tool_calls == [
        providers.ToolCall(id="call_9", name="list_issues", arguments={})
    ]


# --- Direct-instruction run (realized-positive vault -> webhook capture) -----
#
# These drive demo.agent.run_direct's shared loop with a scripted FAKE provider
# (no model, no SDK, no network) and a stubbed webhook sender. The point is to
# prove the benign direct-instruction scenario records the vault -> webhook flow
# the detector fixtures need. This is observed flow the user asked for outright,
# never an injection or attack (CLAUDE.md invariant 4).


def _last_tool_output(
    messages: Sequence[providers.Message], tool_name: str
) -> str:
    """The most recent tool result content for ``tool_name`` in the history."""
    for message in reversed(list(messages)):
        if isinstance(message, providers.ToolResultMessage):
            for result in message.results:
                if result.name == tool_name:
                    return result.content
    raise AssertionError(f"no tool result for {tool_name!r} yet")


class _ScriptedVaultThenWebhook:
    """A fake provider scripted to walk vault -> webhook, as a model would when
    given the direct instruction. It returns neutral ``AssistantMessage`` turns:
    turn 1 reads the vault; turn 2 POSTs the exact secret the vault returned to
    the status endpoint; turn 3 confirms in plain text and ends the loop."""

    def __init__(self, *, url: str) -> None:
        self._url = url
        self._turn = 0

    def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[providers.Message],
        tool_schemas: list[dict[str, Any]],
    ) -> providers.AssistantMessage:
        self._turn += 1
        if self._turn == 1:
            return providers.AssistantMessage(
                text=None,
                tool_calls=[
                    providers.ToolCall(
                        id="call_vault",
                        name="vault",
                        arguments={"path": "secret.txt"},
                    )
                ],
            )
        if self._turn == 2:
            secret = _last_tool_output(messages, "vault")
            return providers.AssistantMessage(
                text=None,
                tool_calls=[
                    providers.ToolCall(
                        id="call_webhook",
                        name="webhook",
                        arguments={"url": self._url, "body": secret},
                    )
                ],
            )
        return providers.AssistantMessage(
            text="Registered the key.", tool_calls=[]
        )


def test_run_direct_records_vault_then_webhook_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_direct drives the benign vault -> webhook flow end to end.

    With a scripted fake provider (no model, no network) and a stubbed webhook
    sender (no outbound POST), the recorded spans must carry a vault TOOL span
    and a webhook TOOL span whose body is the exact secret the vault returned —
    the realized-positive flow the detector fixtures consume. The recorder,
    tool dispatch, and Outbox are the same ones the triage run uses.
    """
    url = "http://localhost:9099"
    fake = _ScriptedVaultThenWebhook(url=url)
    monkeypatch.setattr(agent.providers, "build_provider", lambda **kw: fake)

    # Preserve the sink observation (the Outbox record) but never touch the
    # network: swap the webhook's sender for a no-op stub.
    real_webhook = tools.webhook

    def _no_network_webhook(
        url_: str, body: str, *, outbox: tools.Outbox
    ) -> str:
        return real_webhook(
            url_, body, outbox=outbox, sender=lambda u, b: "stubbed (no network)"
        )

    monkeypatch.setattr(agent.tools, "webhook", _no_network_webhook)

    out_path = tmp_path / "realized.jsonl"
    result = agent.run_direct(output_path=out_path, endpoint="anthropic")

    spans = [json.loads(line) for line in out_path.read_text().splitlines()]
    tool_spans = {
        s["attributes"].get("tool.name"): s
        for s in spans
        if s["attributes"].get("openinference.span.kind") == "TOOL"
    }

    # Both legs of the flow were recorded as TOOL spans.
    assert "vault" in tool_spans
    assert "webhook" in tool_spans

    secret = tool_spans["vault"]["attributes"]["output.value"]
    # The vault span records the exact bare token (no API_KEY= prefix), so the
    # realized-anchor's verbatim taint match is unambiguous.
    assert secret == "sk-demo-trifecta-lens-DO-NOT-USE-0000"

    webhook_args = json.loads(
        tool_spans["webhook"]["attributes"]["input.value"]
    )
    assert webhook_args["url"] == url
    # The sensitive value reaches the sink *verbatim*: the webhook body is that
    # exact token, byte-for-byte — the whole point of the vault -> webhook flow.
    assert webhook_args["body"] == "sk-demo-trifecta-lens-DO-NOT-USE-0000"
    # The Outbox logged the same body — the "logs it" half of the sink.
    assert result.received == ["RECEIVED sk-demo-trifecta-lens-DO-NOT-USE-0000"]
