"""CLI: `noob "why is jellyfin erroring?"` — same loop as the API, human output."""

import argparse
import asyncio
import json
import sys

from .api import build_agent
from .config import Config


async def run(args) -> int:
    agent = build_agent(Config())
    data_event = None
    ok = False
    async for ev in agent.ask(args.question, args.since):
        kind = ev["event"]
        if kind == "grounding":
            labels = ", ".join(f"{k}({n})" for k, n in ev["loki_labels"].items())
            print(f"· grounding: loki labels {labels}; {ev['metric_names']} metrics", file=sys.stderr)
        elif kind == "route":
            print(f"· route: {ev['target']}", file=sys.stderr)
        elif kind == "attempt":
            print(f"· attempt {ev['n']} [{ev['target']}] since {ev['since']}: {ev['query']}", file=sys.stderr)
        elif kind == "query_error":
            print(f"  ✗ rejected: {ev['error'][:300]}", file=sys.stderr)
        elif kind == "empty":
            print(f"  ∅ no data; hints: {json.dumps(ev['suggestions'])[:300]}", file=sys.stderr)
        elif kind == "data":
            data_event = ev
            print(f"  ✓ {json.dumps(ev['stats'])}", file=sys.stderr)
        elif kind == "summary":
            print(f"\n{ev['text']}\n", file=sys.stderr)
        elif kind == "done":
            ok = ev["ok"]
            if not ok:
                print(f"✗ {ev.get('error', 'failed')}", file=sys.stderr)

    if data_event and args.json:
        json.dump(data_event, sys.stdout, indent=None)
        print()
    if data_event and args.save:
        with open(args.save, "w") as f:
            json.dump(data_event, f)
        print(f"· data written to {args.save}", file=sys.stderr)
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(prog="noob", description="Ask your logs and metrics a question.")
    p.add_argument("question")
    p.add_argument("--since", help='override lookback, e.g. "15m", "24h"')
    p.add_argument("--json", action="store_true", help="print the data event as JSON on stdout")
    p.add_argument("--save", metavar="FILE", help="write the data event to FILE")
    sys.exit(asyncio.run(run(p.parse_args())))


if __name__ == "__main__":
    main()
