"""trifecta-capture — the inventory capture step, OUTSIDE the analyzer core.

The two capability tiers key on a **captured tool inventory**, and that artifact
cannot be read off any file on disk: under MCP, tool definitions exist only at
runtime, returned by ``tools/list`` from a *running* server (``DECISIONS.md`` F1).
Getting them means launching servers and speaking a transport — which the analyzer
core may never do (``CLAUDE.md`` invariant 1: read-only, no network in core).

So the capture lives here, in its own top-level package, installed only with the
``capture`` extra. The gates in ``tests/`` scan ``trifecta_lens/``; this package is
outside that boundary **by design**, exactly as ``demo/`` is. The analyzer then
reads the JSON this writes — a local file, read-only — and never knows a server
existed.

``demo/capture_inventory.py`` remains the *demo's* capture (hard-wired to our
reference topology, and the provenance of the committed fixture). This package is
the one a stranger points at their **own** MCP host config.
"""

__all__ = ["__doc__"]
