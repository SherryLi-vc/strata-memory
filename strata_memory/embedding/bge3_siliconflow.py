"""BGE-M3 embedding provider via SiliconFlow API.

Uses MRL (Matryoshka Representation Learning) client-side truncation:
API returns 1024-dim → we keep first 384 dims for efficiency.
"""

from __future__ import annotations

import httpx

from .base import EmbeddingProvider


class BGE3SiliconFlowProvider(EmbeddingProvider):
    """BGE-M3 embeddings via SiliconFlow's OpenAI-compatible API."""

    def __init__(self, model: str = "BAAI/bge-m3", base_url: str = "https://api.siliconflow.cn/v1",
                 api_key: str = "", dimension: int = 384):
        super().__init__(model, base_url, api_key, dimension)
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def embed(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key or "..." in self.api_key or len(self.api_key) < 20:
            raise RuntimeError(
                "SiliconFlow API key missing or redacted "
                f"(length={len(self.api_key or '')}). "
                "Set full STRATA_API_KEY (no '...' placeholders)."
            )
        resp = await self.client.post(
            "/embeddings",
            json={
                "model": self.model,
                "input": texts,
            },
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"SiliconFlow auth failed HTTP {resp.status_code}. "
                "Key is present but rejected — usually truncated/redacted key "
                "from OpenClaw (sk-xxx...yyy) or revoked key. "
                "Put the FULL key in STRATA_API_KEY and restart MCP."
            )
        if resp.status_code >= 400:
            body = (resp.text or "")[:300]
            raise RuntimeError(
                f"SiliconFlow embeddings HTTP {resp.status_code}: {body}"
            )
        data = resp.json()
        # data["data"] is list of {"embedding": [...], "index": N}
        embeddings = []
        for item in sorted(data["data"], key=lambda x: x["index"]):
            vec = item["embedding"]
            # MRL client-side truncation: 1024 → target dimension
            embeddings.append(vec[:self.dimension])
        return embeddings

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
