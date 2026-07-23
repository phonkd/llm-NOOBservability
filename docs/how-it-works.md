# How it works

The pipeline per question:

```
question ──> route ──> generate (grammar-constrained) ──> execute ──┬─> data + summary
                ^                                                   │
                └────────── repair (error text / fuzzy hints) <─────┘  (≤ NOOB_MAX_ATTEMPTS)
```

## Why a small local model is enough

A 7–9B model cannot free-associate correct LogQL/PromQL. Every stage is
deterministic scaffolding that removes ways for it to be wrong:

**Grounding cache.** Label names and values (Loki) and metric names + a few
identity labels like `hostname`/`instance`/`job` (Prometheus/Mimir) are pulled
from the live servers on a TTL (`NOOB_GROUNDING_TTL`, default 300 s) and
injected into the prompt. The model picks from what exists instead of
hallucinating selectors. High-cardinality labels (> 200 values) are dropped
from the prompt. For metrics, only candidates relevant to the question (token
overlap plus a synonym table: "ram" → `memory`, "disk" → `filesystem`, …) are
offered, topped up with everyday staples (`node_cpu_seconds_total`, …).

**Routing.** A separate tiny classification call decides logs vs metrics.
Keeping it out of the generation prompt lets each target get a focused,
few-shot prompt — LogQL and PromQL never share a context.

**Constrained decoding.** Every generation call uses ollama's structured
outputs (JSON-schema grammar), so the *shape* is guaranteed; the model only
supplies the query string and the lookback. Responses are still parsed
defensively (one nudged retry, then give up on that attempt) because grammar
enforcement has proven leaky in some ollama versions — notably, sending
`"think": false` on ollama 0.30.x silently disables `format` entirely.

**Repair loop.** A rejected query gets the server's parse error verbatim. An
empty result gets fuzzy suggestions computed from the grounding cache: for
each label matcher, the nearest real values (`unit="jellyfin"` → *did you mean
`jellyfin.service`?*); for PromQL, near-miss metric names. Repeated identical
queries are detected and called out.

For PromQL, an empty result additionally triggers *per-metric series
grounding*: every real metric in the query gets its actual label sets fetched
from `/api/v1/series` and fed back. This catches the classic small-model trap
where the metric is right but the identity label is wrong — e.g.
`instance=~"203-media.*"` when that metric only carries
`hostname="203-media"` and its `instance` is a scrape address like
`127.0.0.1:9835`. Global label inventories can't catch that; only the
metric's own series can.

If a result is empty but every matcher actually selects values (regex
matchers are evaluated, not string-compared) — and for PromQL, some real
series of the metric satisfies all matchers — the empty result is accepted as
the answer ("no errors in the last hour") instead of burning retries.

**Caps.** Lookback is clamped to `NOOB_MAX_RANGE_HOURS`, Loki line count to
`NOOB_LOKI_LIMIT`, and range-query steps are chosen to keep ~250 points per
series. Only read-only API endpoints are used; nothing in the service can
mutate the datasources.

**Transparency.** The executed query is always part of the output. Wrong
answers are visibly wrong — and reading the queries is how you learn LogQL by
osmosis.

## Summaries

The result is digested before summarization (per-series min/max/mean/last for
matrices, first ~30 lines for log streams) so the summary model sees a small,
faithful view instead of 10k raw points. The summary prompt forbids inventing
data when the digest is empty.
