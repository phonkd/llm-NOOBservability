# llm-NOOBservability

Observability for giga noobs: ask your logs and metrics a question in plain
language. A small local LLM (ollama) translates it to LogQL or PromQL, the
service runs it **directly** against Loki / Mimir (no Grafana), self-corrects
using the real label values and metric names when a query parses wrong or
returns nothing, and summarizes the data.

```
$ noob "did jellyfin log any errors in the last hour?"
· attempt 1 [loki] since 1h: {unit="jellyfin.service"} |~ "(?i)error"
  ✓ {"streams": 2, "lines": 14}

Jellyfin logged 14 errors in the last hour, all from ...
```

## How it stays honest at 9B parameters

- **Grounding**: label names/values (Loki) and metric names (Mimir) are pulled
  from the live servers and injected into the prompt — the model picks from
  what exists instead of hallucinating selectors.
- **Constrained decoding**: every generation is JSON-schema-constrained via
  ollama's structured outputs; valid shape is guaranteed by grammar.
- **Repair loop**: parse errors are fed back verbatim; empty results trigger
  fuzzy suggestions ("`unit="jellyfin"` → did you mean `jellyfin.service`?")
  for up to `NOOB_MAX_ATTEMPTS` tries.
- **Caps**: lookback and line limits are clamped server-side; only read-only
  API endpoints are used.
- The executed query is always shown — wrong answers are visibly wrong, and
  it's how you learn LogQL by osmosis.

## Run

`noob-server` serves `POST /api/ask` (`{"question": "...", "since": "1h"?}`,
NDJSON event stream: `grounding`, `attempt`, `query_error`, `empty`, `data`,
`summary`, `done`) and `GET /api/health`. `noob "question" [--since 1h]
[--json] [--save out.json]` is the CLI. Configuration is env vars
(`NOOB_LOKI_URL`, `NOOB_MIMIR_URL` — include Mimir's `/prometheus` prefix,
`NOOB_OLLAMA_URL`, `NOOB_MODEL`, `NOOB_PORT`, `NOOB_EXTRA_CONTEXT[_FILE]`, …);
see `src/noobservability/config.py`. NixOS: `nixosModules.default` →
`services.noobservability.*`.

## Roadmap

Phase 2: tiny chat web UI served from the same process — graph (uPlot) as soon
as data arrives, JSON/CSV download. Phase 3: maybe MCP so other agents can use
it.
