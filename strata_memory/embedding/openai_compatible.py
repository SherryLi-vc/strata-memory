"""OpenAI-compatible ``POST /embeddings`` client.

SiliconFlow, OpenAI, and any other server that speaks that API
(including a local Ollama, llama.cpp, TEI, or vLLM endpoint) use this client.
Memory text and recall queries are sent to ``base_url``.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .base import EmbeddingProvider
from .vectors import fit_vector


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """Call ``{base_url}/embeddings`` and return float vectors."""

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "",
        dimension: int = 384,
        *,
        truncate: bool = False,
        provider_label: str = "OpenAI-compatible",
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        super().__init__(model, base_url, api_key, dimension)
        self.truncate = truncate
        self.provider_label = provider_label
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            kwargs: dict[str, Any] = {
                "base_url": self.base_url.rstrip("/"),
                "headers": headers,
                "timeout": httpx.Timeout(60.0),
            }
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def embed(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._key_rejected():
            raise RuntimeError(
                f"{self.provider_label} API key missing or redacted "
                f"(length={len(self.api_key or '')}). "
                "Set STRATA_EMBEDDING_API_KEY or STRATA_API_KEY "
                "(no '...' placeholders)."
            )
        resp = await self.client.post(
            "/embeddings",
            json={"model": self.model, "input": texts},
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"{self.provider_label} auth failed HTTP {resp.status_code} "
                f"at {self.base_url}. The key was rejected. "
                "Put the full key in STRATA_API_KEY or STRATA_EMBEDDING_API_KEY "
                "and restart the MCP server."
            )
        if resp.status_code >= 400:
            body = (resp.text or "")[:300]
            raise RuntimeError(f"{self.provider_label} embeddings HTTP {resp.status_code} at {self.base_url}: {body}")
        data = resp.json()
        rows = data.get("data")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError(
                f"{self.provider_label} embeddings response at {self.base_url} did not include data[].embedding."
            )
        embeddings: list[list[float]] = []
        for item in sorted(rows, key=lambda x: x.get("index", 0)):
            raw = item.get("embedding")
            if not isinstance(raw, list) or not raw:
                raise RuntimeError(f"{self.provider_label} returned an empty embedding at {self.base_url}.")
            vec = [float(x) for x in raw]
            embeddings.append(
                fit_vector(
                    vec,
                    dimension=self.dimension,
                    truncate=self.truncate,
                    model=self.model,
                    base_url=self.base_url,
                )
            )
        return embeddings

    def _key_rejected(self) -> bool:
        key = self.api_key or ""
        if not key:
            return False
        if "..." in key or "…" in key or len(key) < 20:
            return True
        return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
