Tool inventory — provenance (Checkpoint D, task 2.5)

artifact: fixtures/inventory.json
what it is: a REAL captured tool inventory (DECISIONS.md D2). For each agent
          context, its EFFECTIVE exposed tool set — the verbatim tools/list
          entries a running MCP server returned.

capture:  REAL capture by demo.capture_inventory, 2026-07-12. For each context
          the declared servers were launched over stdio and their tools/list
          responses recorded verbatim. NO model and NO credentials are involved
          in this half — it only lists tools. Servers:
            - fetch       = mcp-server-fetch (uvx)                -> 1 tool
            - filesystem  = @modelcontextprotocol/server-filesystem (npx),
                            scoped to demo/vault                  -> 14 tools
            - notify      = demo.sink_server (our inert sink)     -> 1 tool

contexts (2), deliberately asymmetric (DECISIONS.md D1/D7):
  assistant  servers: fetch + filesystem + notify   (16 tools)
             — a broad-access personal agent; holds the whole trifecta.
  triage     servers: fetch + filesystem            (15 tools)
             — a restricted subagent; the ONLY tool it lacks vs assistant is
               notify__send, the outbound sink.

non-vacuity (the property this artifact exists to establish): triage's tool set
          is a STRICT subset of assistant's, differing by exactly the sink. So
          the union (posture) holds the whole trifecta while triage cannot wire
          it (no outbound leg) — reachable is a STRICT subset of posture, on a
          real captured inventory (DECISIONS.md D1's non-vacuity requirement;
          the D7 constructed fallback is therefore NOT needed).

effective-not-cause (DECISIONS.md D2): the inventory records THAT triage lacks
          the sink, not WHY. A deny list, a subagent allowlist, or simply a
          smaller server loadout would all look identical here — a smaller tool
          set. We do not model the cause (flow-not-causation applied to
          topology). Here the cause happens to be a smaller loadout, stated in
          the provenance note, but the artifact asserts only the effect.

composability: each tool entry is the verbatim tools/list object under `tool`,
          tagged with the `server` that exposed it, so the loader forms the same
          <server>__<tool> name the trace uses. The trace's tool names
          (filesystem__read_text_file, notify__send) are a subset of this
          inventory's names — the join that makes "the three tiers describe one
          system" checkable (task 2.6).

role:     the inventory half of Checkpoint D; input to the posture and reachable
          tiers (Track C, tasks 2.10/2.11). Loaded by core starting at task 2.6.
