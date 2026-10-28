"""In-process embedding model. Text is not sent to a network API."""

from __future__ import annotations

import asyncio

from .base import EmbeddingProvider
from .vectors import fit_vector

_INSTALL = (
    "Local in-process embeddings need the optional local extra: "
    "uv sync --extra local. "
    "Or point STRATA_EMBEDDING_PROVIDER=openai_compatible and "
    "STRATA_EMBEDDING_BASE_URL at a local OpenAI-compatible server "
    "(Ollama, llama.cpp, TEI, vLLM), for example http://127.0.0.1:11434/v1."
)


class LocalEmbeddingProvider(EmbeddingProvider):
    """Run fastembed or sentence-transformers on this machine."""

    def __init__(
        self,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        base_url: str = "",
        api_key: str = "",
        dimension: int = 384,
    ):
        super().__init__(model, base_url, api_key, dimension)
        self._backend: str | None = None
        self._model: object | None = None

    async def embed(self, text: str) -> list[float]:
        rows = await self.embed_batch([text])
        return rows[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = await asyncio.to_thread(self._embed_sync, texts)
        return [
            fit_vector(
                vec,
                dimension=self.dimension,
                truncate=False,
                model=self.model,
                base_url="",
            )
            for vec in vectors
        ]

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        self._load()
        if self._backend == "fastembed":
            rows = list(self._model.embed(texts))  # type: ignore[union-attr]
            return [list(map(float, row)) for row in rows]
        encoded = self._model.encode(texts, normalize_embeddings=True)  # type: ignore[union-attr]
        return [list(map(float, row)) for row in encoded]

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model)
            self._backend = "fastembed"
            return
        except ImportError:
            pass
        except Exception as exc:
            raise RuntimeError(
                f"fastembed failed to load model {self.model}: {exc}. {_INSTALL}"
            ) from exc
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model)
            self._backend = "sentence_transformers"
            return
        except ImportError as exc:
            raise RuntimeError(
                f"No local embedding library is installed for model {self.model}. {_INSTALL}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"sentence-transformers failed to load model {self.model}: {exc}. {_INSTALL}"
            ) from exc

    async def close(self) -> None:
        self._model = None
        self._backend = None
