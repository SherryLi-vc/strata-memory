"""SQLite-backed rebuildable L2 vector companion index."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
from pathlib import Path
from typing import Any


def _doc_id(wing: str, room: str, date_str: str) -> str:
    """Stable document ID from path components."""
    raw = f"{wing}/{room}/{date_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class SqliteVectorStore:
    """Persistent vectors stored as float32 blobs and searched in-process."""

    def __init__(self, persist_dir: Path):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.persist_dir / "vectors.sqlite3"
        self._db = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, document TEXT NOT NULL, "
            "metadata TEXT NOT NULL, embedding BLOB NOT NULL, dimension INTEGER NOT NULL)"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS vectors_tenant ON vectors(json_extract(metadata, '$.tenant_id'))")
        self._db.commit()

    def add(self, documents: list[str], metadatas: list[dict], ids: list[str], embeddings: list[list[float]]) -> None:
        if not (len(documents) == len(metadatas) == len(ids) == len(embeddings)):
            raise ValueError("documents, metadatas, ids, and embeddings must have equal lengths")
        rows = []
        for document, metadata, doc_id, embedding in zip(documents, metadatas, ids, embeddings):
            vector = tuple(float(value) for value in embedding)
            blob = struct.pack(f"{len(vector)}f", *vector)
            rows.append((doc_id, document, json.dumps(metadata, separators=(",", ":")), blob, len(vector)))
        with self._db:
            self._db.executemany(
                "INSERT INTO vectors(id, document, metadata, embedding, dimension) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET document=excluded.document, metadata=excluded.metadata, "
                "embedding=excluded.embedding, dimension=excluded.dimension",
                rows,
            )

    def query(self, query_embedding: list[float], top_k: int = 10, where: dict | None = None) -> list[dict]:
        if top_k <= 0:
            return []
        query = tuple(float(value) for value in query_embedding)
        qnorm = math.sqrt(sum(value * value for value in query))
        if not qnorm:
            return []
        results = []
        for doc_id, document, metadata_json, blob, dimension in self._db.execute(
            "SELECT id, document, metadata, embedding, dimension FROM vectors"
        ):
            metadata = json.loads(metadata_json)
            if not _matches(metadata, where):
                continue
            if dimension != len(query):
                continue
            vector = struct.unpack(f"{dimension}f", blob)
            vnorm = math.sqrt(sum(value * value for value in vector))
            denom = qnorm * vnorm
            cosine = sum(left * right for left, right in zip(query, vector)) / denom if denom else 0.0
            distance = 1.0 - cosine
            results.append({"id": doc_id, "document": document, "metadata": metadata, "distance": distance})
        results.sort(key=lambda item: (item["distance"], item["id"]))
        return results[:top_k]

    def _ids_where(self, where: dict | None) -> list[str]:
        rows = self._db.execute("SELECT id, metadata FROM vectors")
        return [row[0] for row in rows if _matches(json.loads(row[1]), where)]

    def delete_by_wing(self, wing: str) -> int:
        return self.delete_where({"wing": wing})

    def delete_by_ids(self, ids: list[str]) -> None:
        if ids:
            with self._db:
                self._db.executemany("DELETE FROM vectors WHERE id = ?", ((item,) for item in ids))

    def count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0])

    def count_where(self, where: dict) -> int:
        return len(self._ids_where(where))

    def delete_where(self, where: dict) -> int:
        ids = self._ids_where(where)
        self.delete_by_ids(ids)
        return len(ids)

    def existing_ids(self, ids: list[str], batch: int = 500) -> set[str]:
        found: set[str] = set()
        for start in range(0, len(ids), batch):
            chunk = ids[start : start + batch]
            if chunk:
                marks = ",".join("?" for _ in chunk)
                found.update(row[0] for row in self._db.execute(f"SELECT id FROM vectors WHERE id IN ({marks})", chunk))
        return found

    def reset(self) -> None:
        with self._db:
            self._db.execute("DELETE FROM vectors")

    def close(self) -> None:
        self._db.close()


def _matches(metadata: dict[str, Any], where: dict | None) -> bool:
    if not where:
        return True
    if "$and" in where:
        return all(_matches(metadata, clause) for clause in where["$and"])
    return all(metadata.get(key) == value for key, value in where.items())
