"""ChromaDB vector storage wrapper.

Manages the L2 vector index. Each Drawer gets a unique Chroma document ID
built from wing + room + date so upserts are idempotent.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings


def _doc_id(wing: str, room: str, date_str: str) -> str:
    """Stable document ID from path components."""
    raw = f"{wing}/{room}/{date_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class ChromaStore:
    """Thin wrapper around ChromaDB persistent client."""

    def __init__(self, persist_dir: Path):
        self.persist_dir = persist_dir
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    @property
    def client(self) -> chromadb.PersistentClient:
        return self._client

    def _collection(self, name: str = "strata_memory") -> chromadb.Collection:
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, documents: list[str], metadatas: list[dict],
            ids: list[str], embeddings: list[list[float]]) -> None:
        """Add documents to the vector store (upsert)."""
        col = self._collection()
        col.upsert(
            documents=documents,
            metadatas=metadatas,
            ids=ids,
            embeddings=embeddings,
        )

    def query(self, query_embedding: list[float], top_k: int = 10,
              where: Optional[dict] = None) -> list[dict]:
        """Semantic search returning top-K results."""
        col = self._collection()
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        items = []
        if not results["ids"] or not results["ids"][0]:
            return items
        for i, doc_id in enumerate(results["ids"][0]):
            items.append({
                "id": doc_id,
                "document": results["documents"][0][i] if results["documents"] else "",
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0.0,
            })
        return items

    def delete_by_wing(self, wing: str) -> int:
        """Delete all vectors for a wing."""
        col = self._collection()
        # Find docs with matching wing metadata
        results = col.get(where={"wing": wing})
        if results["ids"]:
            col.delete(ids=results["ids"])
        return len(results["ids"])

    def delete_by_ids(self, ids: list[str]) -> None:
        """Delete specific documents by id."""
        col = self._collection()
        col.delete(ids=ids)

    def count(self) -> int:
        """Return the number of vectors in the store."""
        col = self._collection()
        return col.count()
