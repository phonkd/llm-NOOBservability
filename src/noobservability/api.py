"""HTTP API: POST /api/ask streams NDJSON events; GET /api/health."""

import json
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .agent import NoobAgent
from .config import Config
from .ollama import Ollama
from .sources import Loki, Mimir


class AskRequest(BaseModel):
    question: str
    since: str | None = None


def build_agent(cfg: Config) -> NoobAgent:
    data_http = httpx.AsyncClient(timeout=60, trust_env=True)
    llm_http = httpx.AsyncClient(timeout=cfg.llm_timeout, trust_env=True)
    return NoobAgent(
        cfg,
        Loki(cfg.loki_url, data_http),
        Mimir(cfg.mimir_url, data_http),
        Ollama(cfg.ollama_url, cfg.model, llm_http),
    )


cfg = Config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent = build_agent(cfg)
    yield


app = FastAPI(title="llm-NOOBservability", lifespan=lifespan)


@app.post("/api/ask")
async def ask(req: AskRequest):
    agent: NoobAgent = app.state.agent

    async def gen():
        try:
            async for event in agent.ask(req.question, req.since):
                yield json.dumps(event) + "\n"
        except Exception as e:  # surface, don't hang the stream
            yield json.dumps({"event": "fatal", "error": f"{type(e).__name__}: {e}"}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/api/health")
async def health():
    agent: NoobAgent = app.state.agent
    out = {}
    checks = {
        "loki": f"{agent.loki.base}/ready",
        "mimir": f"{agent.mimir.base}/api/v1/labels",
        "ollama": f"{agent.llm.base}/api/tags",
    }
    for name, url in checks.items():
        try:
            r = await agent.loki.http.get(url, timeout=5)
            out[name] = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except Exception as e:
            out[name] = f"error: {type(e).__name__}"
    out["model"] = agent.llm.model
    return out


def serve():
    uvicorn.run(app, host="0.0.0.0", port=cfg.port)
