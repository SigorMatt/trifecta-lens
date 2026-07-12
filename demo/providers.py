"""demo/providers.py — the transport seam between the loop and a model.

The demo's tool-calling loop (:mod:`demo.agent`) does not talk to a model SDK
directly. It talks to a *provider*: a thin adapter that takes one request —
``(system_prompt, messages, tool_schemas)`` in a provider-neutral internal form
— and returns the model's next assistant turn, again in the neutral form. The
loop owns the conversation, dispatches the real tools, and records the spans;
the provider only decides *how the assistant turn is obtained*.

Two adapters implement the same interface:

* :class:`AnthropicProvider` — the original path, the Anthropic Messages API
  with ``tool_use`` / ``tool_result`` blocks. Imported lazily, exactly as
  before, so this module unit-tests without the SDK or a key.
* :class:`OpenAICompatibleProvider` — an OpenAI-compatible Chat Completions
  endpoint, so the live run can drive an open model. One adapter, two servers:
  a local Ollama ``/v1`` server (dummy key) or the Hugging Face Inference
  Providers router (``https://router.huggingface.co/v1``, real bearer token) —
  selected by ``base_url`` + ``api_key`` alone. Uses the ``openai`` client (the
  ``demo`` extra), also imported lazily.

Both are given the *same* neutral messages and tool schemas and must produce the
*same* neutral :class:`AssistantMessage`, so the recorder downstream emits the
identical OpenInference span shape regardless of provider — the recorded trace
must load through the same core ingester either way (CLAUDE.md: two provider
paths behind one small seam). Network access lives here in ``demo/``, never in
the analyzer core.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
# Hugging Face Inference Providers exposes an OpenAI-compatible router; unlike
# Ollama it requires a real bearer token (HF_TOKEN). The router is a *broker*:
# it forwards each request to a third-party serving provider (observed: Groq,
# which serves the model under its own id "llama-3.3-70b-versatile"). A capture
# must therefore record the actual serving provider/model reported in the
# response, not just the id we requested — the served model can differ from
# DEMO_MODEL.
DEFAULT_HF_BASE_URL = "https://router.huggingface.co/v1"
# Ollama ignores the API key, but the OpenAI client requires a non-empty value.
_OLLAMA_API_KEY = "ollama"


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation the model requested, provider-neutral.

    ``arguments`` is the parsed argument object (a dict), regardless of whether
    the provider delivered it as native structured input (Anthropic) or a JSON
    string (OpenAI/Ollama). The loop dispatches on ``name`` and passes
    ``arguments`` straight to the tool stub.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """The output of one dispatched tool call, keyed back to its ``ToolCall``."""

    call_id: str
    name: str
    content: str


@dataclass
class UserMessage:
    """A plain user turn (the task prompt)."""

    text: str


@dataclass
class AssistantMessage:
    """An assistant turn: optional text plus zero or more tool calls.

    This is both a *history* entry the loop appends and the *return value* of a
    provider request — the neutral "assistant turn" the loop consumes.
    """

    text: str | None
    tool_calls: list[ToolCall]


@dataclass
class ToolResultMessage:
    """The results of the tool calls from the immediately preceding turn."""

    results: list[ToolResult]


#: A neutral conversation entry. The loop keeps a list of these; each adapter
#: translates the list into its own wire format on every request.
Message = UserMessage | AssistantMessage | ToolResultMessage


class Provider(Protocol):
    """The one interface the loop calls. Same request, same neutral response."""

    def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Message],
        tool_schemas: list[dict[str, Any]],
    ) -> AssistantMessage:
        """Obtain the model's next assistant turn for ``messages``."""
        ...


# --- Anthropic adapter (the original path) ----------------------------------


def _to_anthropic_messages(
    messages: Sequence[Message],
) -> list[dict[str, Any]]:
    """Render neutral messages as Anthropic Messages API content blocks."""
    out: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserMessage):
            out.append({"role": "user", "content": message.text})
        elif isinstance(message, AssistantMessage):
            blocks: list[dict[str, Any]] = []
            if message.text:
                blocks.append({"type": "text", "text": message.text})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.arguments,
                }
                for call in message.tool_calls
            )
            out.append({"role": "assistant", "content": blocks})
        else:  # ToolResultMessage
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.call_id,
                            "content": result.content,
                        }
                        for result in message.results
                    ],
                }
            )
    return out


def _assistant_from_anthropic(response: Any) -> AssistantMessage:
    """Translate an Anthropic response into the neutral assistant turn."""
    text_parts = [b.text for b in response.content if b.type == "text"]
    tool_calls = [
        ToolCall(id=b.id, name=b.name, arguments=dict(b.input))
        for b in response.content
        if b.type == "tool_use"
    ]
    return AssistantMessage(text="".join(text_parts) or None, tool_calls=tool_calls)


class AnthropicProvider:
    """The original transport: Anthropic Messages API, SDK imported lazily."""

    def __init__(self, *, model: str, max_tokens: int) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic  # lazy: only a live run needs the SDK

            self._client = anthropic.Anthropic()
        return self._client

    def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Message],
        tool_schemas: list[dict[str, Any]],
    ) -> AssistantMessage:
        response = self._get_client().messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system_prompt,
            tools=tool_schemas,
            messages=_to_anthropic_messages(messages),
        )
        return _assistant_from_anthropic(response)


# --- OpenAI-compatible adapter (Ollama, Hugging Face router) ----------------


def _to_openai_tools(
    tool_schemas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Render the neutral tool schemas as OpenAI ``tools`` function specs.

    ``parameters`` is the existing ``input_schema`` verbatim — the JSON Schema
    the tool already advertises; only the envelope differs between providers.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema["description"],
                "parameters": schema["input_schema"],
            },
        }
        for schema in tool_schemas
    ]


def _to_openai_messages(
    system_prompt: str,
    messages: Sequence[Message],
) -> list[dict[str, Any]]:
    """Render neutral messages as OpenAI Chat Completions messages.

    The system prompt is the leading ``system`` message; tool results become
    ``role: "tool"`` messages carrying their ``tool_call_id`` (the OpenAI shape
    the endpoint pairs back to the assistant's ``tool_calls``).
    """
    out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for message in messages:
        if isinstance(message, UserMessage):
            out.append({"role": "user", "content": message.text})
        elif isinstance(message, AssistantMessage):
            entry: dict[str, Any] = {
                "role": "assistant",
                "content": message.text or "",
            }
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(
                                call.arguments, sort_keys=True
                            ),
                        },
                    }
                    for call in message.tool_calls
                ]
            out.append(entry)
        else:  # ToolResultMessage
            out.extend(
                {
                    "role": "tool",
                    "tool_call_id": result.call_id,
                    "content": result.content,
                }
                for result in message.results
            )
    return out


def _parse_arguments(arguments: str | None) -> dict[str, Any]:
    """Parse an OpenAI tool call's JSON-string arguments into a dict.

    A no-argument tool call is delivered inconsistently across OpenAI-compatible
    routers: some send ``"{}"``, some an empty string, and some (observed on the
    HF -> Groq path) the JSON literal ``"null"``. Any parsed value that is not a
    JSON object is treated as "no arguments" and coerced to ``{}`` so the call
    dispatches cleanly instead of crashing; the loop passes this straight to the
    tool stub.
    """
    if not arguments:
        return {}
    parsed = json.loads(arguments)
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _assistant_from_openai(response: Any) -> AssistantMessage:
    """Translate an OpenAI-shaped chat completion into the neutral turn.

    This is the whole translation the loop depends on for the Ollama path:
    ``message.tool_calls[].function`` (``name`` + JSON-string ``arguments``)
    becomes neutral :class:`ToolCall` values with parsed ``arguments``.
    """
    message = response.choices[0].message
    raw_calls = message.tool_calls or []
    tool_calls = [
        ToolCall(
            id=call.id,
            name=call.function.name,
            arguments=_parse_arguments(call.function.arguments),
        )
        for call in raw_calls
    ]
    return AssistantMessage(text=message.content, tool_calls=tool_calls)


class OpenAICompatibleProvider:
    """OpenAI-compatible Chat Completions transport, parameterized per endpoint.

    One adapter serves every OpenAI-compatible server the demo drives: a local
    Ollama ``/v1`` endpoint (dummy key) and the Hugging Face Inference Providers
    router (``https://router.huggingface.co/v1``, real bearer token). Only
    ``base_url`` and ``api_key`` differ between them — the tool-schema
    translation, the ``tool_calls`` parsing, and the ``role:"tool"`` result
    formatting are the *same* code for both (CLAUDE.md: add a transport, not a
    per-provider branch).
    """

    def __init__(
        self,
        *,
        model: str,
        max_tokens: int,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        api_key: str = _OLLAMA_API_KEY,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._base_url = base_url
        self._api_key = api_key
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI  # lazy: only a live run needs the client

            self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)
        return self._client

    def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Message],
        tool_schemas: list[dict[str, Any]],
    ) -> AssistantMessage:
        response = self._get_client().chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=_to_openai_messages(system_prompt, messages),
            tools=_to_openai_tools(tool_schemas),
        )
        return _assistant_from_openai(response)


# --- Selection --------------------------------------------------------------

ANTHROPIC = "anthropic"
OLLAMA = "ollama"
HF = "hf"


def build_provider(
    *,
    endpoint: str,
    model: str,
    max_tokens: int,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    hf_base_url: str = DEFAULT_HF_BASE_URL,
    hf_api_key: str | None = None,
) -> Provider:
    """Select the transport by ``endpoint``.

    ``"anthropic"`` (default) is the Anthropic Messages API. ``"ollama"`` and
    ``"hf"`` are the *same* OpenAI-compatible adapter
    (:class:`OpenAICompatibleProvider`) pointed at different servers: a local
    Ollama endpoint (dummy key) or the Hugging Face Inference Providers router
    (a real ``HF_TOKEN``). Only base URL and auth differ; the translation code is
    shared, never duplicated per provider.
    """
    if endpoint == ANTHROPIC:
        return AnthropicProvider(model=model, max_tokens=max_tokens)
    if endpoint == OLLAMA:
        return OpenAICompatibleProvider(
            model=model,
            max_tokens=max_tokens,
            base_url=ollama_base_url,
            api_key=_OLLAMA_API_KEY,
        )
    if endpoint == HF:
        # The HF router brokers to a third-party serving provider (see the
        # DEFAULT_HF_BASE_URL note); a real token is required, unlike Ollama.
        if not hf_api_key:
            raise ValueError(
                "hf endpoint requires an API token; set HF_TOKEN in the "
                "environment"
            )
        return OpenAICompatibleProvider(
            model=model,
            max_tokens=max_tokens,
            base_url=hf_base_url,
            api_key=hf_api_key,
        )
    raise ValueError(
        f"unknown DEMO_ENDPOINT {endpoint!r}; "
        f"expected {ANTHROPIC!r}, {OLLAMA!r}, or {HF!r}"
    )
