"""CLI entrypoint for trifecta-lens (``trifecta-lens`` console script)."""

import argparse
from collections.abc import Sequence
from importlib.metadata import version


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trifecta-lens",
        description=(
            "Read-only analyzer for lethal-trifecta / data-exfil exposure in "
            "MCP-based agent systems. Reads a captured trace and the MCP "
            "manifest; writes findings to stdout/files only."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('trifecta-lens')}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
