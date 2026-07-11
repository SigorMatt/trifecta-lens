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

from types import SimpleNamespace

import pytest

from demo import providers


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
    assert isinstance(anthropic_provider, providers.AnthropicProvider)
    assert isinstance(ollama_provider, providers.OllamaProvider)


def test_build_provider_rejects_unknown_endpoint() -> None:
    with pytest.raises(ValueError, match="unknown DEMO_ENDPOINT"):
        providers.build_provider(
            endpoint="openai", model="gpt", max_tokens=1024
        )
