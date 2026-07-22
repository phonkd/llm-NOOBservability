import os
from dataclasses import dataclass, field


def _extra_context() -> str:
    path = os.environ.get("NOOB_EXTRA_CONTEXT_FILE")
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read()
    return os.environ.get("NOOB_EXTRA_CONTEXT", "")


@dataclass
class Config:
    loki_url: str = field(default_factory=lambda: os.environ.get("NOOB_LOKI_URL", "http://127.0.0.1:3100"))
    mimir_url: str = field(default_factory=lambda: os.environ.get("NOOB_MIMIR_URL", "http://127.0.0.1:9009/prometheus"))
    ollama_url: str = field(default_factory=lambda: os.environ.get("NOOB_OLLAMA_URL", "http://127.0.0.1:11434"))
    model: str = field(default_factory=lambda: os.environ.get("NOOB_MODEL", "qwen3.5:9b"))
    port: int = field(default_factory=lambda: int(os.environ.get("NOOB_PORT", "8095")))
    extra_context: str = field(default_factory=_extra_context)

    # Guardrails: a mis-generated query must not be able to ask for the world.
    max_attempts: int = field(default_factory=lambda: int(os.environ.get("NOOB_MAX_ATTEMPTS", "3")))
    max_range_hours: int = field(default_factory=lambda: int(os.environ.get("NOOB_MAX_RANGE_HOURS", "168")))
    loki_line_limit: int = field(default_factory=lambda: int(os.environ.get("NOOB_LOKI_LIMIT", "1000")))
    grounding_ttl: int = field(default_factory=lambda: int(os.environ.get("NOOB_GROUNDING_TTL", "300")))
    llm_timeout: float = field(default_factory=lambda: float(os.environ.get("NOOB_LLM_TIMEOUT", "180")))
