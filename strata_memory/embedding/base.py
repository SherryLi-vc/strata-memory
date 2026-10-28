"""Abstract embedding interface — provider-agnostic design."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import normalize_embedding_provider, truncate_embeddings


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers.

    Implementations must provide ``embed()`` and ``embed_batch()``.
    Model, base URL, API key, and dimension are injected at construction.
    """

    def __init__(self, model: str, base_url: str, api_key: str, dimension: int = 384):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.dimension = dimension

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return a single embedding vector for ``text``."""

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a batch of ``texts``."""

    @staticmethod
    def create(
        provider: str,
        model: str,
        base_url: str,
        api_key: str,
        dimension: int = 384,
    ) -> "EmbeddingProvider":
        """Factory: SiliconFlow, any OpenAI-compatible endpoint, or a local model."""
        kind = normalize_embedding_provider(provider)
        truncate = truncate_embeddings(kind, model)
        if kind == "local":
            from .local import LocalEmbeddingProvider

            return LocalEmbeddingProvider(model, base_url, api_key, dimension)
        if kind == "siliconflow" and truncate:
            from .bge3_siliconflow import BGE3SiliconFlowProvider

            return BGE3SiliconFlowProvider(model, base_url, api_key, dimension)
        from .openai_compatible import OpenAICompatibleEmbeddingProvider

        label = "SiliconFlow" if kind == "siliconflow" else "OpenAI-compatible"
        return OpenAICompatibleEmbeddingProvider(
            model,
            base_url,
            api_key,
            dimension,
            truncate=truncate,
            provider_label=label,
        )
