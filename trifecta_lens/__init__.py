"""trifecta-lens: read-only lethal-trifecta / data-exfil exposure analyzer.

Consumes a captured execution trace (OTel / OpenInference spans) plus the
agent's MCP manifest and reports findings across three honesty tiers
(realized / reachable / posture). The analyzer never executes a tool, never
opens a network connection, and never mutates the target system.
"""
