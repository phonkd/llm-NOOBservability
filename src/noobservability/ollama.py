"""Minimal ollama chat client: JSON-schema-constrained generation + free text."""

import json

import httpx


class Ollama:
    def __init__(self, base_url: str, model: str, client: httpx.AsyncClient):
        self.base = base_url.rstrip("/")
        self.model = model
        self.http = client

    async def _chat(self, system: str, user: str, fmt=None, temperature: float = 0.1) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # Query generation wants determinism, not creativity. num_ctx stays
            # modest: the 9B already fills most of an 8 GB card, KV cache included.
            # NB: do NOT send "think": false here — on ollama 0.30.x it silently
            # disables "format" grammar enforcement for qwen3.5.
            "options": {"temperature": temperature, "num_ctx": 8192},
        }
        if fmt is not None:
            payload["format"] = fmt
        r = await self.http.post(f"{self.base}/api/chat", json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"]

    async def generate_json(self, system: str, user: str, schema: dict) -> dict:
        """Grammar-constrained — but ollama's enforcement has leaked in practice
        (empty replies, ignored schemas), so parse defensively: one nudged retry,
        then {} and let the caller's repair loop deal with it."""
        content = await self._chat(system, user, fmt=schema)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            content = await self._chat(
                system, user + "\n\nReturn ONLY the JSON object, nothing else.", fmt=schema
            )
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {}

    async def generate_text(self, system: str, user: str) -> str:
        return (await self._chat(system, user, temperature=0.3)).strip()
