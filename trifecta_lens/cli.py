"""CLI entrypoint for trifecta-lens (``trifecta-lens`` console script).

Read-only: reads a trace file, writes a report/findings/SVG to stdout or to
files. It never opens a network connection and never delivers a finding
anywhere (DESIGN.md §7) — piping the NDJSON stream onward is the user's job.
"""

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from trifecta_lens.catalog import Catalog, default_catalog, load_catalog
from trifecta_lens.engine import detect_realized
from trifecta_lens.findings import Finding, write_ndjson
from trifecta_lens.labeling import label_events
from trifecta_lens.loader import load_otlp_trace, load_trace
from trifecta_lens.model import Event
from trifecta_lens.report import format_report
from trifecta_lens.svg import render_svg

_SCOPE_HELP = (
    "v1 detects VERBATIM taint only: a value that was encoded, split, "
    "summarized or paraphrased between source and sink will NOT be detected. "
    "Transformed taint, cross-agent multi-hop and memory-poisoning are out of "
    "scope and are not detected. This slice runs the realized tier only."
)


def _load_events(path: Path) -> list[Event]:
    """Pick the trace front-end by looking at the file, not by trusting its name.

    Two Stage-1 front-ends exist (FIXTURES.md): the flat JSONL fixture shape and
    real OTLP/JSON. An OTLP document is a single JSON object with a
    ``resourceSpans`` array; the flat shape is one JSON object per line. That is a
    reliable discriminator, and it means ``--trace`` just works on either.
    """
    head = path.read_text(encoding="utf-8").lstrip()
    if head.startswith("{") and '"resourceSpans"' in head[:4096]:
        return load_otlp_trace(path)
    return load_trace(path)


def _catalog(overlay: Path | None) -> Catalog:
    """The shipped catalog, with the user's overlay consulted first (SPEC.md §4)."""
    catalog = default_catalog()
    if overlay is not None:
        catalog = catalog.overlaid_with(load_catalog(overlay))
    return catalog


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trifecta-lens",
        description=(
            "Read-only analyzer for lethal-trifecta / data-exfil exposure in "
            "MCP-based agent systems. Reads a captured trace and the MCP "
            "manifest; writes findings to stdout/files only."
        ),
        epilog=_SCOPE_HELP,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('trifecta-lens')}",
    )
    parser.add_argument(
        "--trace",
        type=Path,
        help=(
            "captured trace to analyze: flat JSONL spans, or a real OTLP/JSON "
            "document (the format is detected from the file)"
        ),
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        help=(
            "user catalog overlay (YAML) — adds/overrides role entries. The "
            "catalog is the only tunable layer; the engine is fixed."
        ),
    )
    parser.add_argument(
        "--findings",
        type=Path,
        help="write findings NDJSON here (default: alongside the report on stdout)",
    )
    parser.add_argument(
        "--svg",
        type=Path,
        help="write the path SVG here (written only when there is a finding)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.trace is None:
        parser.print_help()
        return 0

    events = label_events(_load_events(args.trace), _catalog(args.catalog))

    # The engine is a generator: findings are written as they are found, so the
    # NDJSON is a true append-stream (DESIGN.md §6) rather than a document
    # assembled at the end.
    findings: list[Finding] = []
    if args.findings is not None:
        args.findings.parent.mkdir(parents=True, exist_ok=True)
        with args.findings.open("w", encoding="utf-8") as stream:
            for finding in detect_realized(events):
                write_ndjson([finding], stream)
                findings.append(finding)
    else:
        findings = list(detect_realized(events))

    print(format_report(findings, events))

    if args.svg is not None and findings:
        args.svg.parent.mkdir(parents=True, exist_ok=True)
        args.svg.write_text(render_svg(findings[0]), encoding="utf-8")
        print(f"wrote {args.svg}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
