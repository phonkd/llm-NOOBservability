"""Read-only clients for Loki and Mimir. Nothing here can mutate anything."""

import time

import httpx


class QueryError(Exception):
    """The datasource rejected the query (parse error, bad selector, ...)."""


class Loki:
    def __init__(self, base_url: str, client: httpx.AsyncClient):
        self.base = base_url.rstrip("/")
        self.http = client

    async def labels(self, start: float, end: float) -> list[str]:
        r = await self.http.get(f"{self.base}/loki/api/v1/labels",
                                params={"start": int(start * 1e9), "end": int(end * 1e9)})
        r.raise_for_status()
        return r.json().get("data") or []

    async def label_values(self, name: str, start: float, end: float) -> list[str]:
        r = await self.http.get(f"{self.base}/loki/api/v1/label/{name}/values",
                                params={"start": int(start * 1e9), "end": int(end * 1e9)})
        r.raise_for_status()
        return r.json().get("data") or []

    async def query_range(self, query: str, start: float, end: float, limit: int) -> dict:
        r = await self.http.get(
            f"{self.base}/loki/api/v1/query_range",
            params={
                "query": query,
                "start": int(start * 1e9),
                "end": int(end * 1e9),
                "limit": limit,
                "direction": "backward",
            },
        )
        if r.status_code == 400:
            raise QueryError(r.text.strip()[:2000])
        r.raise_for_status()
        return r.json()["data"]


class Mimir:
    """Talks to Mimir's Prometheus-compatible API; base_url includes /prometheus."""

    def __init__(self, base_url: str, client: httpx.AsyncClient):
        self.base = base_url.rstrip("/")
        self.http = client

    async def metric_names(self, start: float, end: float) -> list[str]:
        r = await self.http.get(f"{self.base}/api/v1/label/__name__/values",
                                params={"start": int(start), "end": int(end)})
        r.raise_for_status()
        return r.json().get("data") or []

    async def label_values(self, name: str, start: float, end: float) -> list[str]:
        r = await self.http.get(f"{self.base}/api/v1/label/{name}/values",
                                params={"start": int(start), "end": int(end)})
        r.raise_for_status()
        return r.json().get("data") or []

    async def query_range(self, query: str, start: float, end: float, step: float) -> dict:
        r = await self.http.get(
            f"{self.base}/api/v1/query_range",
            params={"query": query, "start": int(start), "end": int(end), "step": step},
        )
        if r.status_code == 400:
            body = r.json() if "json" in r.headers.get("content-type", "") else {}
            raise QueryError(body.get("error", r.text.strip()[:2000]))
        r.raise_for_status()
        return r.json()["data"]


def pick_step(start: float, end: float, max_points: int = 250) -> int:
    """A step that keeps a range query under ~max_points samples per series."""
    span = max(end - start, 60)
    step = int(span / max_points)
    # Snap to friendly boundaries so graphs look sane.
    for nice in (15, 30, 60, 120, 300, 600, 1800, 3600, 7200, 21600, 86400):
        if step <= nice:
            return nice
    return step


def now() -> float:
    return time.time()
