"""SiliconFlow BGE-M3 embeddings.

The API returns 1024 dimensions. BGE-M3 is a Matryoshka model, so the
client keeps the first ``dimension`` values (default 384).
"""

from __future__ import annotations

from typing import Optional

import httpx

from .openai_compatible import OpenAICompatibleEmbeddingProvider


class BGE3SiliconFlowProvider(OpenAICompatibleEmbeddingProvider):
    """BGE-M3 via SiliconFlow, or any base URL that serves that model."""

    def __init__(
        self,
        model: str = "BAAI/bge-m3",
        base_url: str = "https://api.siliconflow.cn/v1",
        api_key: str = "",
        dimension: int = 384,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        super().__init__(
            model,
            base_url,
            api_key,
            dimension,
            truncate=True,
            provider_label="SiliconFlow",
            transport=transport,
        )
