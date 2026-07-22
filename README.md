# llm-NOOBservability

Observability for giga noobs: ask your logs and metrics a question in plain
language. A small local LLM (ollama) translates it to LogQL or PromQL, runs it
**directly** against Loki / Mimir / Prometheus (no Grafana), self-corrects
against the real label values and metric names, and summarizes the result.
The executed query is always shown — that's also how you learn LogQL.

```
$ noob "did jellyfin log any errors in the last hour?"
· route: loki
· attempt 1 [loki] since 1h: {unit="jellyfin.service"} |~ "(?i)error"
  ✓ {"streams": 2, "lines": 14}

Jellyfin logged 14 errors in the last hour, all from ...
```

Or over HTTP:

```
curl 'http://host:8095/api/ask?q=which+host+used+the+most+cpu+today'
```

## Quick start

- **NixOS**: copy [`examples/flake.nix`](examples/flake.nix) —
  `nixosModules.default` + `services.noobservability.*`.
- **Anything else**: `pip install .`, set `NOOB_LOKI_URL`, `NOOB_MIMIR_URL`,
  `NOOB_OLLAMA_URL`, run `noob-server` (or just `noob "question"`).
- Pull a model first: `ollama pull qwen3.5:9b`.

## Docs

- [How it works](docs/how-it-works.md) — grounding, constrained decoding, the
  repair loop, and why 9B parameters are enough.
- [API, CLI, configuration](docs/api.md) — endpoints, event stream, env vars,
  NixOS options.

MIT licensed.
