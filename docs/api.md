# API, CLI, and configuration

## HTTP API

### `POST /api/ask`

Body: `{"question": "...", "since": "1h"?}` — any content-type; the raw body
is parsed as JSON. `since` overrides the model's chosen lookback
(`15m`/`1h`/`24h`/`7d`-style).

### `GET /api/ask?q=...&since=...`

Same thing as a one-liner: `curl 'http://host:8095/api/ask?q=ram+usage+last+1h'`.

Both respond with an NDJSON stream, one event per line:

| event | fields | meaning |
|---|---|---|
| `grounding` | `loki_labels`, `metric_names` | schema cache in use |
| `route` | `target` (`loki`\|`mimir`) | datasource decision |
| `attempt` | `n`, `target`, `query`, `since`, `start`, `end`, `step`? | a query about to run |
| `query_error` | `n`, `error` | server rejected the query |
| `empty` | `n`, `suggestions` | zero results; fuzzy hints fed back |
| `data` | `target`, `resultType`, `stats`, `result` | raw Loki/Prometheus result (downloadable as-is) |
| `summary` | `text` | LLM summary of the digested data |
| `done` | `ok`, `attempts`, `target`?, `query`?, `since`?, `error`? | terminal event |
| `fatal` | `error` | unexpected exception |

Only the answer: `... | jq -r 'select(.event=="summary").text'`

### `GET /api/health`

`{"loki": "ok", "mimir": "ok", "ollama": "ok", "model": "qwen3.5:9b"}` — each
dependency probed with a 5 s timeout.

## CLI

```
noob "did jellyfin log any errors in the last hour?" [--since 1h] [--json] [--save out.json]
```

Progress goes to stderr; `--json` prints the `data` event to stdout;
`--save` writes it to a file. Exit code 0 iff the loop produced an answer.
`noob-server` starts the HTTP API.

## Configuration (environment variables)

| variable | default | |
|---|---|---|
| `NOOB_LOKI_URL` | `http://127.0.0.1:3100` | Loki base URL |
| `NOOB_MIMIR_URL` | `http://127.0.0.1:9009/prometheus` | Prometheus-compatible base (Mimir needs `/prometheus`; plain Prometheus doesn't) |
| `NOOB_OLLAMA_URL` | `http://127.0.0.1:11434` | ollama server |
| `NOOB_MODEL` | `qwen3.5:9b` | ollama model tag (must be pulled) |
| `NOOB_PORT` | `8095` | API port |
| `NOOB_EXTRA_CONTEXT` / `NOOB_EXTRA_CONTEXT_FILE` | — | environment-specific hints injected into prompts |
| `NOOB_MAX_ATTEMPTS` | `3` | repair-loop budget |
| `NOOB_MAX_RANGE_HOURS` | `168` | lookback clamp |
| `NOOB_LOKI_LIMIT` | `1000` | max log lines per query |
| `NOOB_GROUNDING_TTL` | `300` | schema cache TTL (seconds) |
| `NOOB_LLM_TIMEOUT` | `180` | per-LLM-call timeout (seconds) |

## NixOS module

`nixosModules.default` exposes `services.noobservability.{enable, port,
lokiUrl, mimirUrl, ollamaUrl, model, extraContext}` and runs `noob-server`
as a hardened `DynamicUser` systemd service. See `examples/flake.nix`.

## Model notes

Any ollama model with decent instruction-following works; the JSON shape is
grammar-enforced either way, the model only determines query quality.
qwen3.5:9b (6.6 GB) is the default; qwen3.5:4b (3.4 GB) is a good fallback on
a GPU shared with other workloads.
