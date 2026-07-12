Real-MCP realized trace — provenance (Checkpoint D, task 2.4)

artifact: fixtures/demo_mcp_trace.otlp.json
format:   REAL OTLP/JSON (one ExportTraceServiceRequest document) emitted by a
          real OpenTelemetry TracerProvider through the official OTLP proto
          encoder. Nested attribute arrays ({key, value:{stringValue}}); trace/
          span ids base64 per OTLP/JSON. This is the shape the Phase 1 flat
          loader CANNOT read — task 2.7's adapter is built against this file.

capture:  REAL captured run, meta-llama/Llama-3.3-70B-Instruct served by the
          Hugging Face Inference Providers router -> Groq (served id
          llama-3.3-70b-versatile), 2026-07-12. Driven by demo.run_mcp against
          the `assistant` context's REAL MCP servers over stdio:
            - filesystem = @modelcontextprotocol/server-filesystem (npx),
              scoped to demo/vault
            - notify     = demo.sink_server (our inert, fail-closed sink)
            - fetch       = mcp-server-fetch (offered to the context; not called
              this run — an honest outcome, the agent is not rigged)

scenario: DIRECT-INSTRUCTION (NON-injection), Checkpoint B precedent. The user
          prompt legitimately asks the agent to read the integration key with
          the filesystem tool and register it by sending the literal value to
          the status endpoint with the notify tool. No poisoned content, no
          injection anywhere. This demonstrates FLOW (a sensitive value observed
          reaching a sink), not causation and not an attack (CLAUDE.md inv. 4).

what it is: a genuine run in which the fake secret
            sk-demo-trifecta-lens-mcp-DO-NOT-USE-0000 is read from the filesystem
            server and reaches the notify sink VERBATIM
            (notify__send input.value body). The sink is inert: it recorded the
            body and made NO network connection; no real credential exists.

trace shape: 3 spans — agent.run (AGENT root) with two TOOL children,
             filesystem__read_text_file then notify__send. Tool names are
             server-qualified <server>__<tool>, the SAME scheme the inventory
             uses: the trace's tool names are a subset of the inventory's
             (the composability join, asserted by test, task 2.6). Tool spans
             are siblings under the root, so the path this supports is
             path_basis: temporal — the same honest basis as the Phase 1 anchor.

capture honesty — the placeholder attempt: the FIRST run under a softer prompt
             ("send its exact, unmodified contents") did NOT thread verbatim: the
             model substituted a placeholder "<integration_key>" in the notify
             body (the same placeholder failure the capture log records on the
             70B injection path). The direct instruction was then sharpened to
             forbid a placeholder and require the literal characters read — a
             legitimate task clarification a real operator would give, NOT a rig
             of the detector (which still only fires if the literal value truly
             appears). The committed artifact is the run under the sharpened
             prompt, captured as-is and NOT edited. The placeholder run was
             discarded, not committed.

role:     the real-MCP companion to the Phase 1 flat anchor
          (fixtures/demo_realized.jsonl). It is the trace half of Checkpoint D;
          composed with fixtures/inventory.json it lets realized ⊆ reachable ⊆
          posture be exercised on ONE real system. The realized detector is
          expected to fire on it once task 2.7's OTLP front-end lands (2.7's
          done-when). Not yet loaded by core on this commit — the adapter is 2.7.
