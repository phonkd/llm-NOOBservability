"""The core loop: route -> constrained query JSON -> execute -> repair -> summarize.

Deterministic scaffolding around a small model: routing is its own tiny
classification call, every generation is grammar-constrained and target-specific
(LogQL and PromQL never share a prompt), every failure is fed back with *real*
schema facts (API error text, nearest actual label values / metric names), and
hard caps keep a bad query from asking Loki for a month of raw logs.
"""

import json
import re
from statistics import fmean
from typing import AsyncIterator

from .config import Config
from .grounding import Grounding
from .ollama import Ollama
from .sources import Loki, Mimir, QueryError, now, pick_step

ROUTE_SCHEMA = {
    "type": "object",
    "properties": {"datasource": {"type": "string", "enum": ["logs", "metrics"]}},
    "required": ["datasource"],
}

GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "since": {"type": "string", "pattern": "^[0-9]+[smhdw]$"},
    },
    "required": ["query", "since"],
}

_SINCE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

ROUTE_SYSTEM = """Classify the question about a running system.

"metrics" — numeric state over time: CPU usage, memory/RAM, disk space,
filesystem, network traffic/bandwidth, temperature, load, process counts,
uptime, whether something is up/down, "how much/how many/highest/most".

"logs" — text events: errors, warnings, messages, crashes, restarts,
"what happened", "why did X fail", requests that were logged.

Return only JSON."""


def parse_since(since: str, max_hours: int) -> float:
    m = re.fullmatch(r"(\d+)([smhdw])", (since or "").strip())
    seconds = int(m.group(1)) * _SINCE_UNITS[m.group(2)] if m else 3600
    return min(max(seconds, 60), max_hours * 3600)


class NoobAgent:
    def __init__(self, cfg: Config, loki: Loki, mimir: Mimir, llm: Ollama):
        self.cfg = cfg
        self.loki = loki
        self.mimir = mimir
        self.llm = llm
        self.grounding = Grounding(loki, mimir, cfg.grounding_ttl)

    # ---- prompts ---------------------------------------------------------

    def _extra(self) -> str:
        return f"\nEnvironment notes:\n{self.cfg.extra_context}\n" if self.cfg.extra_context else ""

    def _loki_system(self) -> str:
        return f"""You write exactly one LogQL query for Grafana Loki.

Log streams exist ONLY with these labels and values:
{self.grounding.loki_schema()}

Rules:
- A query is a stream selector plus optional filters. LogQL has no sort_desc
  and no SQL; PromQL functions don't apply to raw log lines.
- |= "text" for substring, |~ "regex" for regex; (?i) = case-insensitive.
- Counting/graphing logs: wrap in count_over_time({{...}}[5m]) or rate(...).
- Never invent label names or values not listed above.

Examples:
- errors of one service:        {{unit="jellyfin.service"}} |~ "(?i)error"
- one service on one host:      {{hostname="201-mono", unit="traefik.service"}} |= "404"
- how often per 10m:            count_over_time({{unit="sshd.service"}} |~ "(?i)failed"[10m])
{self._extra()}
"since" = lookback like "15m", "1h", "24h", "7d"; default "1h" if unstated.
Return only JSON."""

    def _mimir_system(self) -> str:
        return f"""You write exactly one PromQL query (Prometheus/Mimir).

These label values exist:
{self.grounding.mimir_schema()}

Rules:
- PromQL ONLY. There are NO `|` pipes and no sort_desc in PromQL.
- Use ONLY metric names from "candidate metrics" in the user message.
- Counters (ending _total) need rate(x[5m]); gauges are used directly.
- Aggregate to few series: sum by (hostname) (...), avg by (...).
- "most / highest / top" -> topk(3, ...).
- Select a machine by its hostname label: {{hostname="203-media"}}. The
  instance label is often a scrape address like 127.0.0.1:9835 — avoid it.

Examples:
- CPU usage per host:  sum by (hostname) (rate(node_cpu_seconds_total{{mode!="idle"}}[5m]))
- free disk per host:  sum by (hostname) (node_filesystem_avail_bytes{{fstype!="tmpfs"}})
- memory used:         node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes
- top cpu processes:   topk(5, sum by (groupname) (rate(namedprocess_namegroup_cpu_seconds_total[5m])))
{self._extra()}
"since" = lookback like "15m", "1h", "24h", "7d"; default "1h" if unstated.
Return only JSON."""

    def _user_prompt(self, question: str, target: str) -> str:
        if target == "loki":
            return f"Question: {question}"
        candidates = self.grounding.metric_candidates(question)
        return (
            f"Question: {question}\n\n"
            "candidate metrics (real names from the live server):\n"
            + "\n".join(f"- {m}" for m in candidates)
        )

    @staticmethod
    def _repair_prompt(base_user: str, prev_query: str, problem: str) -> str:
        return (
            f"{base_user}\n\n"
            f"Your previous query was:\n{prev_query}\n\n"
            f"It failed:\n{problem}\n\n"
            "Produce a corrected, DIFFERENT query. Change what the failure "
            "indicates; keep the rest."
        )

    # ---- the loop ----------------------------------------------------------

    async def ask(self, question: str, since_override: str | None = None) -> AsyncIterator[dict]:
        await self.grounding.refresh()
        g = self.grounding
        yield {
            "event": "grounding",
            "loki_labels": {k: len(v) for k, v in g.loki_labels.items()},
            "metric_names": len(g.metric_names),
        }

        route = await self.llm.generate_json(ROUTE_SYSTEM, f"Question: {question}", ROUTE_SCHEMA)
        target = "mimir" if route.get("datasource") == "metrics" else "loki"
        yield {"event": "route", "target": target}

        system = self._mimir_system() if target == "mimir" else self._loki_system()
        base_user = self._user_prompt(question, target)
        user = base_user
        tried: set[str] = set()
        final: dict | None = None
        data = None

        for attempt in range(1, self.cfg.max_attempts + 1):
            q = await self.llm.generate_json(system, user, GEN_SCHEMA)
            q = {"query": (q.get("query") or "").strip(),
                 "since": since_override or q.get("since") or "1h"}
            span = parse_since(q["since"], self.cfg.max_range_hours)
            end = now()
            start = end - span
            step = pick_step(start, end)
            yield {
                "event": "attempt", "n": attempt, "target": target,
                "query": q["query"], "since": q["since"],
                "start": start, "end": end,
                **({"step": step} if target == "mimir" else {}),
            }

            if q["query"] in tried or not q["query"]:
                user = self._repair_prompt(
                    base_user, q["query"],
                    "You produced the exact same query again (or an empty one). "
                    "It is still wrong. Write a genuinely different query.",
                )
                yield {"event": "query_error", "n": attempt, "error": "repeated query"}
                continue
            tried.add(q["query"])

            try:
                if target == "loki":
                    data = await self.loki.query_range(q["query"], start, end, self.cfg.loki_line_limit)
                else:
                    data = await self.mimir.query_range(q["query"], start, end, step)
            except QueryError as e:
                user = self._repair_prompt(base_user, q["query"], f"The server rejected it: {e}")
                yield {"event": "query_error", "n": attempt, "error": str(e)}
                continue

            if data["result"]:
                final = q
                break

            hints = g.suggest_values(q["query"])
            if target == "mimir":
                hints |= g.suggest_metrics(q["query"])
                hints |= await g.suggest_series(q["query"], start, end)
            if not hints:
                # Every matcher points at values/metrics that really exist, and
                # the result is still empty: that IS the answer ("no errors"),
                # not a broken query. Don't burn retries regenerating it.
                final = q
                break
            user = self._repair_prompt(
                base_user, q["query"],
                "It returned zero results.\nNearest real values for the things "
                "you matched on:\n"
                + "\n".join(f'  {k} -> {", ".join(v)}' for k, v in hints.items()),
            )
            yield {"event": "empty", "n": attempt, "suggestions": hints}

        if final is None:
            yield {"event": "done", "ok": False, "attempts": self.cfg.max_attempts,
                   "error": "no data after all attempts"}
            return

        stats = _stats(data)
        yield {"event": "data", "target": target,
               "resultType": data["resultType"], "stats": stats, "result": data["result"]}

        summary = await self.llm.generate_text(
            "You summarize observability query results, concisely and concretely. "
            "2-5 sentences: answer the question first, then numbers (with units — "
            "convert raw bytes/seconds to human scale) and anything anomalous. "
            "If the digest shows zero results, say plainly that nothing matched; "
            "NEVER invent data. No preamble.",
            f"Question: {question}\nExecuted {target} query: {final['query']} "
            f"(last {final['since']})\n\nResult digest:\n{_digest(data)}",
        )
        yield {"event": "summary", "text": summary}
        yield {"event": "done", "ok": True, "attempts": attempt,
               "target": target, "query": final["query"], "since": final["since"]}


# ---- result shaping ---------------------------------------------------------

def _stats(data: dict) -> dict:
    rt = data["resultType"]
    if rt == "streams":
        lines = sum(len(s["values"]) for s in data["result"])
        return {"streams": len(data["result"]), "lines": lines}
    points = sum(len(s.get("values", [])) for s in data["result"])
    return {"series": len(data["result"]), "points": points}


def _digest(data: dict, max_series: int = 15, max_lines: int = 30) -> str:
    """Small-context view of the result: stats per series, sample log lines."""
    rt = data["resultType"]
    out = []
    if rt == "streams":
        total = sum(len(s["values"]) for s in data["result"])
        out.append(f"{len(data['result'])} streams, {total} log lines (newest first, sample):")
        shown = 0
        for s in data["result"]:
            ident = ", ".join(f"{k}={v}" for k, v in list(s["stream"].items())[:4])
            for ts, line in s["values"]:
                if shown >= max_lines:
                    break
                out.append(f"[{ident}] {line[:240]}")
                shown += 1
            if shown >= max_lines:
                out.append(f"... ({total - shown} more lines omitted)")
                break
    else:
        out.append(f"{len(data['result'])} series:")
        for s in data["result"][:max_series]:
            vals = [float(v) for _, v in s.get("values", []) if v != "NaN"]
            labels = json.dumps(s.get("metric", {}))
            if vals:
                out.append(
                    f"{labels}: min={min(vals):.4g} max={max(vals):.4g} "
                    f"mean={fmean(vals):.4g} last={vals[-1]:.4g} ({len(vals)} points)"
                )
        if len(data["result"]) > max_series:
            out.append(f"... ({len(data['result']) - max_series} more series omitted)")
    return "\n".join(out)
