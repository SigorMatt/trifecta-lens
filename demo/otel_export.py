"""demo/otel_export.py — record real OpenInference spans as an OTLP file (2.4).

The trace half of the Checkpoint D capture must be a **real** OTLP document, not
a hand-shaped approximation (``DECISIONS.md`` D9): the Phase 2 OTLP front-end
(task 2.7) is built and tested against *this*. So we drive a real OpenTelemetry
``TracerProvider``, tag spans with the OpenInference semantic-convention
attributes the core loader already keys on
(``openinference.span.kind``/``tool.name``/``input.value``/``output.value``),
and serialise them with the **official** OTLP proto encoder. The result is the
canonical nested OTLP/JSON shape — ``resourceSpans[].scopeSpans[].spans[]`` with
``attributes[] = {key, value:{stringValue}}`` — the shape real exporters emit and
the Phase 1 flat loader cannot yet read (that gap is exactly task 2.7's job).

Trace/span ids and timestamps come from the real run, so the file is not
byte-stable across runs; that is correct for a *captured* artifact (the
determinism invariant binds the analyzer, not the capture). Everything here is
imported lazily so the module imports without the ``demo`` extra.

Network/process effects are confined to ``demo/`` (``CLAUDE.md`` invariant 1):
this writes a local file and opens no connection.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer

SERVICE_NAME = "trifecta-lens-demo"


def _otlp_dict(spans: list[Any]) -> dict[str, Any]:
    """Encode captured ReadableSpans to an OTLP ExportTraceServiceRequest dict."""
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

    request = encode_spans(spans)
    # ``preserving_proto_field_name`` keeps OTLP's canonical field names
    # (e.g. ``traceId``) stable regardless of the installed protobuf version.
    return MessageToDict(request)


@contextmanager
def otlp_recorder(output_path: str | Path) -> Iterator[Tracer]:
    """Yield a real OTel tracer; on exit, write the captured spans as OTLP/JSON.

    Usage::

        with otlp_recorder("out.otlp.json") as tracer:
            with tracer.start_as_current_span("agent.run") as span:
                span.set_attribute("openinference.span.kind", "AGENT")
                ...

    The spans are held in memory (a demo capture is small and bounded), encoded
    through the official OTLP encoder, and written as one JSON document.
    """
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
    from opentelemetry.sdk.trace.export import (
        SimpleSpanProcessor,
        SpanExporter,
        SpanExportResult,
    )

    captured: list[ReadableSpan] = []

    class _CapturingExporter(SpanExporter):
        def export(self, spans: Any) -> Any:
            captured.extend(spans)
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            return None

    resource = Resource.create({"service.name": SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(_CapturingExporter()))
    tracer = provider.get_tracer("demo.mcp_client")

    try:
        yield tracer
    finally:
        provider.shutdown()  # flushes every span into ``captured``
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        document = _otlp_dict(captured)
        out.write_text(
            json.dumps(document, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
