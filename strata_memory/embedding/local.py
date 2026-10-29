"""In-process embedding model. Text is not sent to a network API."""

from __future__ import annotations

import asyncio
import logging
import os

from .base import EmbeddingProvider
from .hashing import hash_embed
from .vectors import fit_vector

logger = logging.getLogger("strata_memory.embedding")

_INSTALL = (
    "The semantic local model downloads weights on first use and needs a network. "
    "Offline, set STRATA_LOCAL_EMBED_BACKEND=hash before start to use the hashing "
    "embedder, then strata_rebuild_index(confirm=true) if an index already exists. "
    "A default install with no local extra already uses hashing and does not download. "
    "Optional: uv sync --extra local, or STRATA_EMBEDDING_PROVIDER=openai_compatible "
    "with a loopback STRATA_EMBEDDING_BASE_URL."
)


def _hash_requested(model: str) -> bool:
    choice = (os.environ.get("STRATA_LOCAL_EMBED_BACKEND") or "").strip().lower()
    if choice in {"hash", "hashing"}:
        return True
    return (model or "").strip().lower() in {"hash", "hashing"}


def _hash_fallback_enabled() -> bool:
    flag = (os.environ.get("STRATA_EMBEDDING_HASH_FALLBACK") or "").strip().lower()
    return flag in {"1", "true", "yes"}


def _tighten_download_timeouts() -> None:
    """Fail a cold offline download in seconds instead of hanging."""
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "3")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "5")
    os.environ.setdefault("HF_HUB_CONNECT_TIMEOUT", "3")


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
        self.install_hint = _INSTALL

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
        if self._backend == "hashing":
            return [hash_embed(text, self.dimension) for text in texts]
        if self._backend == "fastembed":
            rows = list(self._model.embed(texts))  # type: ignore[union-attr]
            return [list(map(float, row)) for row in rows]
        encoded = self._model.encode(texts, normalize_embeddings=True)  # type: ignore[union-attr]
        return [list(map(float, row)) for row in encoded]

    def _use_hash(self, reason: str) -> None:
        logger.info("local embedding backend=hashing (%s)", reason)
        self._backend = "hashing"
        self.backend = "hashing"
        self._model = None

    def _semantic_failed(self, exc: Exception, library: str) -> None:
        if _hash_fallback_enabled():
            logger.warning(
                "%s failed to load %s (%s); STRATA_EMBEDDING_HASH_FALLBACK is set, using hashing",
                library,
                self.model,
                exc,
            )
            self._use_hash(f"{library} failed and hash fallback is enabled")
            return
        raise RuntimeError(f"{library} could not load {self.model}: {exc}. {_INSTALL}") from exc

    def _load(self) -> None:
        if self._backend is not None:
            return
        if _hash_requested(self.model):
            self._use_hash("STRATA_LOCAL_EMBED_BACKEND or model=hashing")
            return
        _tighten_download_timeouts()
        # Optional imports: these extras must not be imported at module load.
        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model)
            self._backend = "fastembed"
            self.backend = "fastembed"
            logger.info("local embedding backend=fastembed model=%s", self.model)
            return
        except ImportError:
            pass
        except Exception as exc:
            self._semantic_failed(exc, "fastembed")
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model)
            self._backend = "sentence_transformers"
            self.backend = "sentence_transformers"
            logger.info("local embedding backend=sentence_transformers model=%s", self.model)
            return
        except ImportError:
            pass
        except Exception as exc:
            self._semantic_failed(exc, "sentence-transformers")
            return
        # No semantic library installed. Hashing needs no download.
        self._use_hash("no fastembed or sentence-transformers installed")

    async def close(self) -> None:
        self._model = None
        self._backend = None
