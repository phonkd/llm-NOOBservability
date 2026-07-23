"""Schema grounding: cached label/metric inventories injected into prompts.

A 9B model cannot guess that logs live under unit="jellyfin.service" on
hostname="203-media" — but it doesn't have to if we hand it the actual label
values. This cache is the main quality lever; the repair loop is the backstop.
"""

import difflib
import re
import time

from .sources import Loki, Mimir

# Labels whose full value list goes into the prompt. Anything above this many
# values is noise for the model and burns context.
MAX_VALUES_PER_LABEL = 200
LOOKBACK_HOURS = 24

# Metric labels that plausibly identify a machine/service; their real values
# go into the PromQL prompt so the model matches on what actually exists.
MIMIR_PROMPT_LABELS = ("hostname", "host", "instance", "job", "nodename", "groupname")


class Grounding:
    def __init__(self, loki: Loki, mimir: Mimir, ttl: int):
        self.loki = loki
        self.mimir = mimir
        self.ttl = ttl
        self._fetched_at = 0.0
        self.loki_labels: dict[str, list[str]] = {}
        self.mimir_labels: dict[str, list[str]] = {}
        self.metric_names: list[str] = []

    async def refresh(self, force: bool = False) -> None:
        if not force and time.time() - self._fetched_at < self.ttl:
            return
        end = time.time()
        start = end - LOOKBACK_HOURS * 3600
        labels = await self.loki.labels(start, end)
        self.loki_labels = {}
        for name in labels:
            values = await self.loki.label_values(name, start, end)
            if len(values) <= MAX_VALUES_PER_LABEL:
                self.loki_labels[name] = values
        self.mimir_labels = {}
        for name in MIMIR_PROMPT_LABELS:
            values = await self.mimir.label_values(name, start, end)
            if values and len(values) <= MAX_VALUES_PER_LABEL:
                self.mimir_labels[name] = values
        self.metric_names = await self.mimir.metric_names(start, end)
        self._fetched_at = time.time()

    # ---- prompt material -------------------------------------------------

    def loki_schema(self) -> str:
        lines = []
        for name, values in sorted(self.loki_labels.items()):
            lines.append(f'  {name}: {", ".join(values)}')
        return "\n".join(lines)

    def mimir_schema(self) -> str:
        lines = []
        for name, values in sorted(self.mimir_labels.items()):
            lines.append(f'  {name}: {", ".join(values)}')
        return "\n".join(lines)

    def metric_candidates(self, question: str, k: int = 80) -> list[str]:
        """Metric names plausibly related to the question, by token overlap."""
        tokens = {t for t in re.split(r"[^a-z0-9]+", question.lower()) if len(t) > 2}
        tokens |= _EXPANSIONS_FOR(tokens)
        scored = []
        for m in self.metric_names:
            score = sum(1 for t in tokens if t in m)
            if score:
                scored.append((score, m))
        scored.sort(key=lambda s: (-s[0], s[1]))
        out = [m for _, m in scored[:k]]
        # Always include the everyday metrics so basic questions never miss.
        for m in _STAPLES:
            if m in self.metric_names and m not in out:
                out.append(m)
        return out[: k + len(_STAPLES)]

    # ---- repair material -------------------------------------------------

    def suggest_values(self, query: str) -> dict[str, list[str]]:
        """For each label matcher in a failed query, nearest real values."""
        suggestions: dict[str, list[str]] = {}
        for label, op, value in _matchers(query):
            if op.startswith("!"):
                continue
            known = self.loki_labels.get(label) or self.mimir_labels.get(label)
            if not known or _matcher_hits(op, value, known):
                continue
            close = difflib.get_close_matches(value, known, n=5, cutoff=0.3)
            # Substring hits matter too: "jellyfin" vs "jellyfin.service".
            subs = [v for v in known if value.lower() in v.lower()]
            merged = list(dict.fromkeys(subs + close))
            if merged:
                suggestions[f'{label}{op}"{value}"'] = merged[:5]
        return suggestions


    def suggest_metrics(self, query: str) -> dict[str, list[str]]:
        """For identifiers in a PromQL query that aren't real metrics, nearest real ones."""
        known = set(self.metric_names)
        suggestions: dict[str, list[str]] = {}
        # Strip quoted strings first: label values aren't metric names.
        bare = re.sub(r'"[^"]*"', '""', query)
        for ident in set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{4,}", bare)):
            if ident in known or ident in _PROMQL_WORDS:
                continue
            close = difflib.get_close_matches(ident, self.metric_names, n=5, cutoff=0.5)
            subs = [m for m in self.metric_names if ident.lower() in m.lower()]
            merged = list(dict.fromkeys(subs + close))
            if merged:
                suggestions[ident] = merged[:5]
        return suggestions

    async def suggest_series(self, query: str, start: float, end: float) -> dict[str, list[str]]:
        """For each real metric in an empty-result PromQL query, its actual label sets.

        This is the fix for the classic small-model trap: the metric is right
        but the identity label is wrong (instance="203-media" when the series
        only carries hostname="203-media"). Global label lists can't catch it —
        only this metric's own series can.
        """
        known = set(self.metric_names)
        bare = re.sub(r'"[^"]*"', '""', query)
        matchers = _matchers(query)
        out: dict[str, list[str]] = {}
        for metric in set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{4,}", bare)) & known:
            series = await self.mimir.series(metric, start, end)
            if not series:
                out[metric] = ["metric has no series in this time range"]
                continue
            # If some series satisfies every matcher, the query is consistent
            # with reality — empty is then a true answer, not a labeling bug.
            if any(_series_matches(s, matchers) for s in series):
                continue
            sets = []
            for s in series[:5]:
                labels = {k: v for k, v in s.items() if k != "__name__"}
                sets.append("{" + ", ".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}")
            out[f"real series of {metric}"] = list(dict.fromkeys(sets))
        return out


def _matchers(query: str) -> list[tuple[str, str, str]]:
    return re.findall(r'(\w+)\s*(=~|!~|!=|=)\s*"([^"]*)"', query)


def _matcher_hits(op: str, value: str, known: list[str]) -> bool:
    """Does this =/=~ matcher select at least one of the known values?"""
    if op == "=":
        return value in known
    try:  # PromQL/LogQL regex matchers are fully anchored.
        pat = re.compile(value)
    except re.error:
        return False
    return any(pat.fullmatch(v) for v in known)


def _series_matches(series: dict, matchers: list[tuple[str, str, str]]) -> bool:
    for label, op, value in matchers:
        got = series.get(label, "")
        if op in ("=~", "!~"):
            try:
                ok = bool(re.fullmatch(value, got))
            except re.error:
                ok = False
        else:
            ok = got == value
        if op.startswith("!"):
            ok = not ok
        if not ok:
            return False
    return True


_PROMQL_WORDS = {
    "rate", "irate", "increase", "sum", "avg", "min", "max", "count", "topk",
    "bottomk", "histogram_quantile", "quantile", "stddev", "delta", "deriv",
    "label_replace", "without", "group_left", "group_right", "offset", "clamp_max",
    "clamp_min", "count_over_time", "rate_over_time", "bytes_over_time", "absent",
    "avg_over_time", "max_over_time", "min_over_time", "sum_over_time", "instance",
    "hostname", "predict_linear", "time", "vector", "scalar", "round", "floor",
}

_STAPLES = [
    "up",
    "node_cpu_seconds_total",
    "node_memory_MemAvailable_bytes",
    "node_memory_MemTotal_bytes",
    "node_filesystem_avail_bytes",
    "node_filesystem_size_bytes",
    "node_load1",
    "node_network_receive_bytes_total",
    "node_network_transmit_bytes_total",
]

# Colloquial term -> substrings that actually appear in metric names.
_SYNONYMS = {
    "cpu": {"cpu", "load"},
    "ram": {"memory", "mem"},
    "memory": {"memory", "mem"},
    "disk": {"filesystem", "disk"},
    "space": {"filesystem", "avail"},
    "storage": {"filesystem", "disk"},
    "network": {"network", "receive", "transmit"},
    "traffic": {"network", "receive", "transmit", "requests"},
    "bandwidth": {"network", "receive", "transmit"},
    "temperature": {"temp", "thermal", "hwmon"},
    "uptime": {"boot", "time", "up"},
    "processes": {"process", "procs", "namedprocess"},
    "process": {"process", "procs", "namedprocess"},
}


def _EXPANSIONS_FOR(tokens: set[str]) -> set[str]:
    out: set[str] = set()
    for t in tokens:
        out |= _SYNONYMS.get(t, set())
    return out
