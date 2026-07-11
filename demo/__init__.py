"""demo/ — the vulnerable demo agent + harness (task 1.1).

This package lives **outside** the analyzer core (``trifecta_lens/``). Network
and process side effects are allowed here and ONLY here: the core never opens a
network connection (CLAUDE.md invariant 1), which the no-network guard (task
0.4) enforces by scanning ``trifecta_lens/`` only. Nothing in ``trifecta_lens/``
imports from ``demo/``.

The harness runs an ordinary tool-calling agent against three stub tools and
records payload-level OpenInference spans to a JSONL file. It is boring on
purpose (CLAUDE.md: grateful realism, not a strawman): the agent is not rigged
to leak. Exposure arises only if the model follows an indirect prompt-injection
instruction hidden in fetched page content — the structural shape of the
documented GitHub MCP / GitLab Duo / Writer.com incidents (see README.md).

The single credentialed step is ``make demo-live`` (task 1.2), run by a human
with a model API key in their own environment. The recorded trace
(``fixtures/demo_exfil.jsonl``) is captured from that real run and committed by
the human — it is never hand-authored (FIXTURES.md, CLAUDE.md).
"""
