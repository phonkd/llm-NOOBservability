"""HTTP API: POST /api/ask streams NDJSON events; GET /api/health."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

STATIC_DIR = Path(__file__).parent / "static"

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


def _stream(req: AskRequest) -> StreamingResponse:
    agent: NoobAgent = app.state.agent

    async def gen():
        try:
            async for event in agent.ask(req.question, req.since):
                yield json.dumps(event) + "\n"
        except Exception as e:  # surface, don't hang the stream
            yield json.dumps({"event": "fatal", "error": f"{type(e).__name__}: {e}"}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/ask")
async def ask(request: Request):
    # Deliberately liberal: parse the raw body as JSON whatever the
    # content-type — `curl -d '{...}'` sends x-www-form-urlencoded and a noob
    # tool shouldn't fail on a missing header.
    try:
        body = json.loads(await request.body())
        req = AskRequest.model_validate(body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        raise HTTPException(422, f'body must be JSON like {{"question": "..."}} — {e}')
    return _stream(req)


@app.get("/api/ask")
async def ask_get(q: str, since: str | None = None):
    """One-liner form: /api/ask?q=ram+usage+201-mono (browser- and curl-friendly)."""
    return _stream(AskRequest(question=q, since=since))


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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


def serve():
    uvicorn.run(app, host="0.0.0.0", port=cfg.port)
