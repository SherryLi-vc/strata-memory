"""Abstract embedding interface — provider-agnostic design."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers.

    Implementations must provide `embed()` and `embed_batch()`.
    Every provider is configuration-driven — model, base_url, api_key
    are injected at construction time.
    """

    def __init__(self, model: str, base_url: str, api_key: str, dimension: int = 384):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.dimension = dimension

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return a single embedding vector for `text`."""

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a batch of `texts`."""

    @staticmethod
    def create(provider: str, model: str, base_url: str, api_key: str, dimension: int = 384) -> "EmbeddingProvider":
        """Factory: instantiate the right provider based on config."""
        if provider == "siliconflow":
            from .bge3_siliconflow import BGE3SiliconFlowProvider
            return BGE3SiliconFlowProvider(model, base_url, api_key, dimension)
        raise ValueError(f"Unknown embedding provider: {provider}")
